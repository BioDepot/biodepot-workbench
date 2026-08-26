"""STAR Suite adapter helpers.

These functions keep STAR-suite discovery/rendering behind a narrow boundary so
the agent API can expose prototype-compatible endpoints without importing the
prototype workbench app.
"""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import yaml

from morphic_agent.content.paths import star_suite_root

MAX_HELPER_SCRIPT_BYTES = 250_000
HELPER_SOURCE_SUFFIXES = (".sh", ".py", ".R", ".pl", ".awk")
TEXT_SOURCE_SUFFIXES = (*HELPER_SOURCE_SUFFIXES, ".yaml", ".yml", ".json", ".md", ".txt")

RECIPE_CONFIDENCE_CONTRACT = [
    "Core suite binaries and recipe-declared helper scripts are provenance-backed when they come from tested suite recipes.",
    "Dry-runs and materialization checks can prove referenced files and command wiring exist, not that changed biological parameters are correct.",
    "Parameters copied to a different application, assay, reference, host, or sample layout need agent review plus targeted preflight tests.",
    "Helper scripts from outside provenance, or edited after generation, are candidate code until syntax checks, dry-runs, and small tests pass.",
]


def star_root_path(star_root: str | Path | None = None) -> Path:
    if star_root:
        return Path(star_root).expanduser().resolve()
    return star_suite_root()


def validate_workflow_id(workflow_id: str) -> str:
    value = str(workflow_id or "").strip()
    if not re.match(r"^[A-Za-z0-9_.-]+$", value):
        raise ValueError("invalid workflow_id")
    return value


def load_yaml_file(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _safe_rel_path(path_text: str) -> str | None:
    value = str(path_text or "").strip()
    if not value or Path(value).is_absolute():
        return None
    rel = Path(value)
    if any(part in ("", ".", "..") for part in rel.parts):
        return None
    return value


def _is_helper_source_path(path_text: str) -> bool:
    rel = _safe_rel_path(path_text)
    if rel is None:
        return False
    return rel.startswith("scripts/") or rel.endswith(HELPER_SOURCE_SUFFIXES)


def _resolve_under(root: Path, rel_path: str) -> Path | None:
    rel = _safe_rel_path(rel_path)
    if rel is None:
        return None
    try:
        candidate = (root / rel).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def workflow_schema_path(workflow_id: str, star_root: str | Path | None = None) -> Path | None:
    workflow_id = validate_workflow_id(workflow_id)
    root = star_root_path(star_root)
    config_path = root / "mcp_server" / "config.yaml"
    schema_file = ""
    if config_path.is_file():
        config = load_yaml_file(config_path)
        for item in config.get("workflows") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or item.get("workflow_id") or "") == workflow_id:
                schema_file = str(item.get("schema_file") or "").strip()
                break
    if not schema_file:
        schema_file = f"mcp_server/workflows/{workflow_id}.yaml"
    rel = _safe_rel_path(schema_file)
    if rel is None:
        return None
    return _resolve_under(root, rel)


def load_workflow_schema(workflow_id: str, star_root: str | Path | None = None) -> dict[str, Any]:
    path = workflow_schema_path(workflow_id, star_root)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"workflow schema not found: {workflow_id}")
    schema = load_yaml_file(path)
    schema.setdefault("id", workflow_id)
    schema["_schema_path"] = str(path)
    return schema


def list_star_workflows(star_root: str | Path | None = None, *, include_private: bool = True) -> dict[str, Any]:
    root = star_root_path(star_root)
    config_path = root / "mcp_server" / "config.yaml"
    if not config_path.is_file():
        return {"error": True, "code": "STAR_CONFIG_NOT_FOUND", "message": f"STAR config not found: {config_path}", "workflows": []}
    config = load_yaml_file(config_path)
    workflows: list[dict[str, Any]] = []
    for item in config.get("workflows") or []:
        if not isinstance(item, dict):
            continue
        workflow_id = str(item.get("id") or item.get("workflow_id") or "").strip()
        if not workflow_id:
            continue
        visibility = str(item.get("visibility") or "public")
        if visibility == "private" and not include_private:
            continue
        workflows.append(
            {
                "id": workflow_id,
                "workflow_id": workflow_id,
                "title": str(item.get("title") or workflow_id),
                "summary": str(item.get("summary") or ""),
                "kind": str(item.get("kind") or ""),
                "entry_script": item.get("entry_script"),
                "schema_file": item.get("schema_file") or f"mcp_server/workflows/{workflow_id}.yaml",
                "visibility": visibility,
            }
        )
    return {
        "schema": "morphic.star_workflows/v0",
        "suite": "star",
        "star_root": str(root),
        "workflows": workflows,
    }


def _script_language(path_text: str, declared: Any = None) -> str:
    declared_text = str(declared or "").strip()
    if declared_text:
        return declared_text
    suffix = Path(path_text).suffix.lower()
    return {
        ".sh": "bash",
        ".py": "python",
        ".r": "r",
        ".pl": "perl",
        ".awk": "awk",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".txt": "text",
    }.get(suffix, "text")


def _read_helper_source(path: Path) -> tuple[str, int, bool]:
    raw = path.read_bytes()
    size = len(raw)
    truncated = size > MAX_HELPER_SCRIPT_BYTES
    if truncated:
        raw = raw[:MAX_HELPER_SCRIPT_BYTES]
    return raw.decode("utf-8", errors="replace"), size, truncated


def load_star_helper_scripts(workflow_id: str, star_root: str | Path | None = None) -> dict[str, Any]:
    try:
        workflow_id = validate_workflow_id(workflow_id)
        schema = load_workflow_schema(workflow_id, star_root)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"error": True, "code": "NOT_FOUND", "message": str(exc), "workflow_id": workflow_id}

    root = star_root_path(star_root)
    raw_scripts = schema.get("scripts") or []
    if not raw_scripts and isinstance(schema.get("entry_script"), str):
        raw_scripts = [{"role": "entry", "path": schema["entry_script"], "description": "Entry script"}]

    scripts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_scripts:
        if not isinstance(item, dict):
            continue
        rel_path = str(item.get("path") or "").strip()
        if rel_path in seen or not _is_helper_source_path(rel_path):
            continue
        seen.add(rel_path)
        abs_path = _resolve_under(root, rel_path)
        payload: dict[str, Any] = {
            "role": str(item.get("role") or "helper"),
            "path": rel_path,
            "description": str(item.get("description") or ""),
            "language": _script_language(rel_path, item.get("language")),
            "exists": bool(abs_path and abs_path.is_file()),
            "content": "",
            "size_bytes": None,
            "truncated": False,
            "editable": rel_path.endswith(TEXT_SOURCE_SUFFIXES),
        }
        if abs_path and abs_path.is_file() and rel_path.endswith(TEXT_SOURCE_SUFFIXES):
            try:
                content, size, truncated = _read_helper_source(abs_path)
                payload.update({"content": content, "size_bytes": size, "truncated": truncated})
            except OSError as exc:
                payload["error"] = str(exc)
        elif abs_path and abs_path.is_file():
            payload["size_bytes"] = abs_path.stat().st_size
            payload["editable"] = False
        scripts.append(payload)

    return {
        "schema": "morphic.star_helper_scripts/v0",
        "workflow_id": workflow_id,
        "schema_path": schema.get("_schema_path"),
        "scripts": scripts,
        "confidence_contract": RECIPE_CONFIDENCE_CONTRACT,
    }


def _safe_download_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return safe or "star-workflow"


def helper_bundle_filename(workflow_id: str) -> str:
    return f"star-helper-bundle-{_safe_download_stem(workflow_id)}.zip"


def helper_bundle_readme(workflow_id: str) -> str:
    return "\n".join(
        [
            "STAR Launchpad helper source bundle",
            f"workflow_id: {workflow_id}",
            "",
            "Contents:",
            "- helper_sources/: editable helper scripts using STAR-suite-relative paths.",
            "- helper_manifest.tsv: original path to bundle path mapping.",
            "",
            "Suggested local run flow:",
            "1. Generate or materialize the run recipe folder from the workbench.",
            "2. Unzip this bundle into the run recipe folder.",
            "3. Review/edit helper_sources/ and run the generated local command.",
            "",
            "Confidence boundary:",
            *[f"- {line}" for line in RECIPE_CONFIDENCE_CONTRACT],
            "",
            "The agent service does not write edits back into the STAR-suite checkout.",
            "",
        ]
    )


def build_helper_bundle_zip(workflow_id: str, scripts: list[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    manifest = ["original_path\tbundle_path\trole\tlanguage\tmodified"]
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", helper_bundle_readme(workflow_id))
        for script in scripts:
            if not isinstance(script, dict):
                continue
            rel_path = str(script.get("path") or "").strip()
            if not _is_helper_source_path(rel_path):
                continue
            content = script.get("content")
            if not isinstance(content, str):
                content = ""
            role = str(script.get("role") or "helper")
            language = str(script.get("language") or "text")
            modified = "1" if bool(script.get("modified")) else "0"
            bundle_path = f"helper_sources/{rel_path}"
            archive.writestr(bundle_path, content.encode("utf-8"))
            manifest.append(f"{rel_path}\t{bundle_path}\t{role}\t{language}\t{modified}")
        archive.writestr("helper_manifest.tsv", "\n".join(manifest) + "\n")
    return buffer.getvalue()


def render_star_workflow(
    workflow_id: str,
    params: dict[str, Any],
    *,
    star_root: str | Path | None = None,
    check_paths: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    workflow_id = validate_workflow_id(workflow_id)
    root = star_root_path(star_root)
    workflows_py = root / "mcp_server" / "tools" / "workflows.py"
    if not workflows_py.is_file():
        return {
            "workflow_id": workflow_id,
            "validation": {"valid": False, "errors": [f"STAR workflow tools not found: {workflows_py}"]},
            "render": None,
        }

    script = r"""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
workflow_id = sys.argv[2]
params = json.loads(sys.argv[3])
check_paths = bool(json.loads(sys.argv[4]))

sys.path.insert(0, str(root))
from mcp_server.config import load_config
from mcp_server.tools.workflows import render_workflow_command, validate_workflow_parameters

def dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return obj

load_config(root / "mcp_server" / "config.yaml")
validation = dump(validate_workflow_parameters(workflow_id, params, check_paths=check_paths))
render = None
if validation.get("valid", True):
    normalized = validation.get("normalized_params") or validation.get("params") or params
    render = dump(render_workflow_command(workflow_id, normalized))
print(json.dumps({"workflow_id": workflow_id, "validation": validation, "render": render}, default=str))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(root), workflow_id, json.dumps(params), json.dumps(check_paths)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "workflow_id": workflow_id,
            "validation": {"valid": False, "errors": [str(exc)]},
            "render": None,
        }

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "STAR workflow render failed").strip()
        return {
            "workflow_id": workflow_id,
            "validation": {"valid": False, "errors": [message]},
            "render": None,
        }
    try:
        payload = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError as exc:
        return {
            "workflow_id": workflow_id,
            "validation": {"valid": False, "errors": [f"invalid STAR renderer JSON: {exc}"]},
            "render": None,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    render = payload.get("render")
    if isinstance(render, dict) and render.get("argv"):
        render.setdefault("run_script_filename", f"run-{workflow_id}.sh")
        if not render.get("run_script"):
            lines = [
                "#!/usr/bin/env bash",
                f"# Generated by STAR Launchpad for {workflow_id}",
                "set -euo pipefail",
                "",
            ]
            env = render.get("env_overrides") if isinstance(render.get("env_overrides"), dict) else {}
            for key, value in sorted(env.items()):
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)):
                    lines.append(f"export {key}={shlex.quote(str(value))}")
            if env:
                lines.append("")
            lines.extend([f"exec {shlex.join(str(item) for item in render['argv'])}", ""])
            render["run_script"] = "\n".join(lines)
    return payload
