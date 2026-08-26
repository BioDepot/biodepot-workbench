"""Trimodal MuData QC report bundle materializer."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from morphic_agent.bundle.containers import write_container_launchers, write_container_manifest
from morphic_agent.bundle.path_bindings import write_path_bindings
from morphic_agent.content.paths import multiomics_suite_root, recipes_tutorials_root
from morphic_agent.graph.params import validate_graph_params

TRIMODAL_QC_GRAPH_ID = "trimodal_qc_report_v0"


def _content_root() -> Path:
    return recipes_tutorials_root()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_graph_id(text: str) -> str:
    keep = []
    for ch in text.lower():
        keep.append(ch if ch.isalnum() else "_")
    value = "".join(keep).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "graph"


def _resolve_input_path(raw: Any, *, repo_root: Path | None = None) -> Path:
    root = repo_root or _content_root()
    path = Path(str(raw or "")).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _find_trimodal_helper() -> Path | None:
    content_root = _content_root()
    candidates: list[Path] = []
    for raw in (
        os.environ.get("MORPHIC_TRIMODAL_QC_HELPER"),
        str(multiomics_suite_root() / "scripts" / "generate_trimodal_qc.py"),
        str(content_root / "scripts" / "generate_trimodal_qc.py"),
    ):
        if raw:
            candidates.append(Path(raw).expanduser())
    for path in candidates:
        if path.is_file():
            return path
    return None


def assess_trimodal_qc_execution_readiness(graph: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    validation = validate_graph_params(graph, params)
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    if not validation["valid"]:
        blockers.append("required parameters are missing or invalid")
        for name in validation.get("missing_required_inputs") or []:
            checks.append({"check": f"required parameter `{name}`", "status": "fail"})
        for name, message in (validation.get("field_errors") or {}).items():
            checks.append({"check": f"{name}: {message}", "status": "fail"})

    mudata = _resolve_input_path(params.get("mudata"))
    mudata_ok = mudata.is_file()
    checks.append({"check": "MuData input exists", "status": "pass" if mudata_ok else "fail", "path": str(mudata)})
    if not mudata_ok:
        blockers.append("MuData input file does not exist")

    output_prefix = str(params.get("output_prefix") or "").strip()
    if output_prefix:
        output_parent = Path(output_prefix).expanduser().parent
        if not output_parent.is_absolute():
            output_parent = _content_root() / output_parent
        existing_parent = output_parent
        while not existing_parent.exists() and existing_parent.parent != existing_parent:
            existing_parent = existing_parent.parent
        writable = existing_parent.exists() and os.access(existing_parent, os.W_OK)
        checks.append(
            {
                "check": "output parent is writable or creatable",
                "status": "pass" if writable else "fail",
                "path": str(output_parent),
            }
        )
        if not writable:
            blockers.append("output directory parent is not writable")
    else:
        checks.append({"check": "output_prefix parameter present", "status": "fail"})
        blockers.append("output_prefix is required")

    helper = _find_trimodal_helper()
    checks.append(
        {
            "check": "trimodal QC helper source exists",
            "status": "pass" if helper else "fail",
            "path": str(helper) if helper else None,
        }
    )
    if helper is None:
        blockers.append("generate_trimodal_qc.py helper was not found")

    try:
        python_ok = subprocess.run(["python3", "--version"], capture_output=True, text=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        python_ok = False
    checks.append({"check": "python3 available", "status": "pass" if python_ok else "fail"})
    if not python_ok:
        blockers.append("python3 is not available")

    inputs_ok = validation["valid"] and mudata_ok and bool(output_prefix)
    executable_ready = inputs_ok and helper is not None and python_ok
    if executable_ready:
        status = "preflight_passed"
    elif inputs_ok:
        status = "inputs_passed"
    else:
        status = "blocked"
    return {
        "status": status,
        "graph_id": graph.get("graph_id"),
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(blockers) if blockers else None,
        "inputs_passed": inputs_ok,
        "executable_ready": executable_ready,
        "validation": validation,
        "helper_source": str(helper) if helper else None,
    }


def _missing_helper_source() -> str:
    return textwrap.dedent(
        """\
        #!/usr/bin/env python3
        raise SystemExit(
            "generate_trimodal_qc.py was not found when this bundle was rendered. "
            "Set MORPHIC_TRIMODAL_QC_HELPER to a real helper or replace this file."
        )
        """
    )


def _preflight_helper() -> str:
    return textwrap.dedent(
        """\
        #!/usr/bin/env python3
        import argparse
        import importlib.util
        import json
        import os
        from pathlib import Path

        parser = argparse.ArgumentParser()
        parser.add_argument("--params", required=True)
        parser.add_argument("--helper", required=True)
        parser.add_argument("--repo-root", required=True)
        parser.add_argument("--out", required=True)
        args = parser.parse_args()

        params = json.loads(Path(args.params).read_text())["params"]
        repo_root = Path(args.repo_root)
        checks = []
        blockers = []

        def resolve(raw):
            path = Path(str(raw or "")).expanduser()
            return path if path.is_absolute() else repo_root / path

        mudata = resolve(params.get("mudata"))
        mudata_ok = mudata.is_file()
        checks.append({"check": "MuData input exists", "status": "pass" if mudata_ok else "fail", "path": str(mudata)})
        if not mudata_ok:
            blockers.append("MuData input file does not exist")

        helper = Path(args.helper)
        helper_ok = helper.is_file()
        checks.append({"check": "trimodal QC helper exists in bundle", "status": "pass" if helper_ok else "fail", "path": str(helper)})
        if not helper_ok:
            blockers.append("trimodal QC helper is missing from bundle")

        output_prefix = str(params.get("output_prefix") or "").strip()
        if output_prefix:
            output_parent = Path(output_prefix).expanduser().parent
            if not output_parent.is_absolute():
                output_parent = repo_root / output_parent
            existing_parent = output_parent
            while not existing_parent.exists() and existing_parent.parent != existing_parent:
                existing_parent = existing_parent.parent
            writable = existing_parent.exists() and os.access(existing_parent, os.W_OK)
            checks.append({"check": "output parent is writable or creatable", "status": "pass" if writable else "fail", "path": str(output_parent)})
            if not writable:
                blockers.append("output directory parent is not writable")
        else:
            checks.append({"check": "output_prefix parameter present", "status": "fail"})
            blockers.append("output_prefix is required")

        for package in ("mudata", "plotly", "scanpy", "pandas", "numpy"):
            ok = importlib.util.find_spec(package) is not None
            checks.append({"check": f"python package importable: {package}", "status": "pass" if ok else "fail"})
            if not ok:
                blockers.append(f"python package is missing: {package}")

        result = {
            "schema": "morphic.preflight_result/v0",
            "status": "preflight_passed" if not blockers else "blocked",
            "inputs_passed": mudata_ok and bool(output_prefix),
            "executable_ready": not blockers,
            "checks": checks,
            "blockers": blockers,
            "run_blocker": "; ".join(blockers) if blockers else None,
        }
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\\n")
        raise SystemExit(0 if not blockers else 2)
        """
    )


def _run_sh(*, repo_root: Path, params: dict[str, Any], helper_source: Path | None) -> str:
    title = str(params.get("title") or "Trimodal QC report")
    helper_note = str(helper_source) if helper_source else "not found; replace helpers/generate_trimodal_qc.py before running"
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        BUNDLE_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
        REPO_ROOT="${{MORPHIC_RECIPES_TUTORIALS_ROOT:-{shlex.quote(str(repo_root))}}}"

        # Helper source copied from: {helper_note}
        # Review params.review.json, manifests/path_bindings.json, and helpers/generate_trimodal_qc.py before running.
        # PNG export is disabled by default because it requires kaleido; set WRITE_PNG=1 to enable it.
        RUNTIME_PARAMS="$BUNDLE_DIR/manifests/runtime_params.json"

        resolve_param() {{
          python3 - "$BUNDLE_DIR" "$REPO_ROOT" "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
key = sys.argv[3]
default = sys.argv[4]

params_path = bundle / "params.review.json"
manifest_path = bundle / "manifests" / "path_bindings.json"
params = {{}}
manifest = {{}}
if params_path.is_file():
    loaded = json.loads(params_path.read_text())
    if isinstance(loaded, dict) and isinstance(loaded.get("params"), dict):
        params = loaded["params"]
if manifest_path.is_file():
    loaded_manifest = json.loads(manifest_path.read_text())
    if isinstance(loaded_manifest, dict):
        manifest = loaded_manifest

def binding_value():
    for binding in manifest.get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        if key not in {{str(binding.get("param") or ""), str(binding.get("field") or ""), str(binding.get("binding_id") or "")}}:
            continue
        raw = str(binding.get("path") or "").strip()
        if not raw:
            return None
        path_kind = str(binding.get("path_kind") or "")
        path = Path(raw).expanduser()
        if path_kind == "bundle_relative":
            return str((bundle / raw).resolve())
        if not path.is_absolute() and manifest.get("execution_location") == "server":
            return str((repo_root / raw).resolve())
        return raw
    return None

value = binding_value() if key in {{"mudata", "output_prefix"}} else None
if value is None:
    value = params.get(key, default)
if isinstance(value, str) and key in {{"mudata", "output_prefix"}}:
    path = Path(value).expanduser()
    if value and not path.is_absolute() and manifest.get("execution_location") == "server":
        value = str((repo_root / value).resolve())
print(value)
PY
        }}

        MUDATA="${{MUDATA:-$(resolve_param mudata '')}}"
        OUTPUT_PREFIX="${{OUTPUT_PREFIX:-$(resolve_param output_prefix "$BUNDLE_DIR/outputs/trimodal_qc")}}"
        TITLE="${{TITLE:-$(resolve_param title {shlex.quote(title)})}}"

        python3 - "$RUNTIME_PARAMS" "$MUDATA" "$OUTPUT_PREFIX" "$TITLE" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
payload = {{
    "params": {{
        "mudata": sys.argv[2],
        "output_prefix": sys.argv[3],
        "title": sys.argv[4],
    }}
}}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n")
PY

        python3 "$BUNDLE_DIR/helpers/preflight_trimodal_qc.py" \\
          --params "$RUNTIME_PARAMS" \\
          --helper "$BUNDLE_DIR/helpers/generate_trimodal_qc.py" \\
          --repo-root "$BUNDLE_DIR" \\
          --out "$BUNDLE_DIR/manifests/preflight_result.json"

        png_args=(--no-png)
        if [[ "${{WRITE_PNG:-0}}" == "1" ]]; then
          png_args=()
        fi

        python3 "$BUNDLE_DIR/helpers/generate_trimodal_qc.py" \\
          --mudata "$MUDATA" \\
          --output-prefix "$OUTPUT_PREFIX" \\
          --title "$TITLE" \\
          "${{png_args[@]}}"

        echo "Trimodal QC report written to $OUTPUT_PREFIX.html and $OUTPUT_PREFIX.json"
        """
    ).lstrip()


def materialize_trimodal_qc_bundle(
    graph: dict[str, Any],
    out_root: str | Path,
    *,
    params: dict[str, Any] | None = None,
    execution_location: str = "server",
) -> Path:
    out_root = Path(out_root)
    bundle = out_root / _safe_graph_id(str(graph["graph_id"]))
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "helpers").mkdir(parents=True)
    (bundle / "manifests").mkdir(parents=True)
    (bundle / "outputs").mkdir(parents=True)

    merged = dict(params or {})
    merged.setdefault("title", "Trimodal QC report")
    helper_source = _find_trimodal_helper()

    graph_payload = dict(graph)
    graph_payload["canonical_graph_hash"] = _sha256_json(
        {
            "graph_id": graph["graph_id"],
            "nodes": graph.get("nodes"),
            "edges": graph.get("edges"),
        }
    )

    recipe_payload = {
        "schema": "morphic.materialized_recipe/v0",
        "graph_id": graph["graph_id"],
        "title": graph.get("title"),
        "canonical_graph_hash": graph_payload["canonical_graph_hash"],
        "nodes": graph.get("nodes"),
        "edges": graph.get("edges"),
    }
    params_review_payload = {"params": merged}

    (bundle / "workflow_graph.json").write_text(json.dumps(graph_payload, indent=2, sort_keys=True) + "\n")
    (bundle / "recipe.json").write_text(json.dumps(recipe_payload, indent=2, sort_keys=True) + "\n")
    (bundle / "params.schema.json").write_text(json.dumps(graph.get("params_schema") or {}, indent=2, sort_keys=True) + "\n")
    (bundle / "params.review.json").write_text(json.dumps(params_review_payload, indent=2, sort_keys=True) + "\n")
    write_path_bindings(
        bundle,
        graph,
        merged,
        execution_location=execution_location,
        recipe_payload=recipe_payload,
        params_review_payload=params_review_payload,
    )
    write_container_manifest(bundle, str(graph["graph_id"]))
    (bundle / "manifests" / "projection_manifest.json").write_text(
        json.dumps(
            {
                "schema": "morphic.graph_projection_manifest/v0",
                "canonical_store": "postgres",
                "graph_index": "arcadedb",
                "materialized_at": _utc_now(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (bundle / "manifests" / "source_manifest.json").write_text(
        json.dumps(
            {
                "schema": "morphic.source_manifest/v0",
                "graph_id": graph["graph_id"],
                "sources": [
                    {
                        "role": "trimodal_qc_helper",
                        "source_path": str(helper_source),
                        "bundle_path": "helpers/generate_trimodal_qc.py",
                    }
                ]
                if helper_source
                else [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    helper_target = bundle / "helpers" / "generate_trimodal_qc.py"
    helper_target.write_text(helper_source.read_text(encoding="utf-8") if helper_source else _missing_helper_source())
    helper_target.chmod(helper_target.stat().st_mode | stat.S_IXUSR)

    helpers = {
        "preflight_trimodal_qc.py": _preflight_helper(),
    }
    manifest_lines = ["helper_id\tbundle_path\tsource_path"]
    manifest_lines.append(f"generate_trimodal_qc.py\thelpers/generate_trimodal_qc.py\t{str(helper_source) if helper_source else ''}")
    for name, source in helpers.items():
        path = bundle / "helpers" / name
        path.write_text(source)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        manifest_lines.append(f"{name}\thelpers/{name}\t")
    (bundle / "helper_manifest.tsv").write_text("\n".join(manifest_lines) + "\n")

    run_sh = bundle / "run.sh"
    run_sh.write_text(_run_sh(repo_root=_content_root(), params=merged, helper_source=helper_source))
    run_sh.chmod(0o755)
    write_container_launchers(bundle, str(graph["graph_id"]))
    (bundle / "README.md").write_text(
        "\n".join(
            [
                f"# {graph.get('title') or graph['graph_id']}",
                "",
                "Reviewable folder bundle for the trimodal MuData QC report.",
                "",
                "1. Review params.review.json, manifests/path_bindings.json, and run.sh.",
                "2. Edit helpers/generate_trimodal_qc.py if the report needs small local changes.",
                "3. For caller-local runs, adjust manifests/path_bindings.json to paths visible from that shell.",
                "4. Run ./run.sh after preflight passes, or run ./run.docker.sh / ./run.apptainer.sh to use the declared container image.",
                "5. The container contract lives in manifests/container.json.",
                "6. The default script writes HTML and JSON. Set WRITE_PNG=1 to request PNG export.",
                "",
            ]
        )
    )
    return bundle


def preflight_trimodal_qc_bundle(graph: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return assess_trimodal_qc_execution_readiness(graph, params)
