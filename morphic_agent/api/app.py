
"""Agent API — FastAPI service boundary for chat and BioDepot tools."""

from __future__ import annotations

import os
import hashlib
import io
import json
import mimetypes
import re
import selectors
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from morphic_front.graph_mvp import RecipeGraph, materialize_star_mvp_bundle, run_materialized_bundle

from morphic_agent.bundle.containers import (
    container_manifest_response,
    diagnose_container_manifest,
    load_container_manifest,
)
from morphic_agent.bundle.nfcore_pipeline import is_nfcore_pipeline_graph
from morphic_agent.bundle.path_bindings import (
    load_path_bindings,
    path_bindings_response,
    resolve_params_for_location,
    validate_path_bindings_for_location,
)
from morphic_agent.execution import (
    DEFAULT_EXECUTION_LOCATION_ID,
    annotate_preflight_for_location,
    execution_dispatch_for_location,
    execution_location_gate,
    list_execution_locations,
    resolve_execution_location,
)
from morphic_agent.execution.scheduler import run_scheduler_bundle, run_scheduler_remote_ssh_bundle
from morphic_agent.execution.ssh import run_remote_ssh_bundle
from morphic_agent.execution.nextflow import nextflow_artifact_candidate_paths
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.suites.star import (
    build_helper_bundle_zip,
    helper_bundle_filename,
    list_star_workflows,
    load_star_helper_scripts,
    render_star_workflow,
)
from morphic_agent.api.workbench_html import WORKBENCH_HTML
from morphic_agent.workbench import WorkbenchService


def _recipe_graph_from_payload(graph: dict[str, Any]) -> RecipeGraph:
    return RecipeGraph(
        graph_id=str(graph["graph_id"]),
        title=str(graph.get("title") or graph["graph_id"]),
        nodes=graph.get("nodes") or [],
        edges=graph.get("edges") or [],
        inputs=graph.get("inputs") or [],
        outputs=graph.get("outputs") or [],
        capabilities=graph.get("capabilities") or [],
        evidence=graph.get("evidence") or [],
        lifecycle_state=str(graph.get("lifecycle_state") or "candidate"),
        confidence_tier=str(graph.get("confidence_tier") or "source_derived"),
        materialization_status=str(graph.get("materialization_status") or "runnable_smoke_bundle"),
        planner_trace=graph.get("planner_trace") or [],
        projection=graph.get("projection") or {},
        execution=graph.get("execution") or {},
    )


def _resolve_path_lenient(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_star_mvp_bundle_root(raw: Any = None) -> Path:
    default_root = Path("/tmp/morphic-star-graph-mvp-agent")
    configured_root = os.environ.get("MORPHIC_AGENT_STAR_MVP_BUNDLE_ROOT")
    root = Path(str(raw or configured_root or default_root)).expanduser()
    resolved = _resolve_path_lenient(root)
    allowed_roots = [_resolve_path_lenient(default_root)]
    if configured_root:
        allowed_roots.append(_resolve_path_lenient(Path(configured_root).expanduser()))
    if not any(resolved == allowed or _path_is_under(resolved, allowed) for allowed in allowed_roots):
        resolved = _resolve_path_lenient(default_root)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _execution_location_from_body(body: dict[str, Any]):
    raw = body.get("execution_location") if "execution_location" in body else body.get("execution_profile")
    return resolve_execution_location(raw)


def _bundle_under_allowed_root(bundle: Path, allowed_root: Path) -> bool:
    try:
        bundle.resolve().relative_to(allowed_root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _composition_problem_signature(goal: str, body: dict[str, Any]) -> dict[str, Any]:
    requested_outputs = [str(item) for item in body.get("requested_outputs") or [] if str(item).strip()]
    capabilities = [str(item) for item in body.get("capabilities") or [] if str(item).strip()]
    input_artifacts = [str(item) for item in body.get("input_artifacts") or [] if str(item).strip()]
    text = goal.lower()
    if not requested_outputs and any(term in text for term in ("deg", "degs", "deseq", "differential expression")):
        requested_outputs.append("differential_expression_table")
    if not capabilities and any(term in text for term in ("deg", "degs", "deseq", "differential expression")):
        capabilities.append("deg")
    if "volcano" in text:
        capabilities.append("volcano_plot")
        requested_outputs.extend(["png", "plotly_html"])
    return {
        "goal": goal,
        "input_artifacts": input_artifacts,
        "requested_outputs": requested_outputs,
        "capabilities": sorted(set(capabilities)),
    }


def _workflow_graph_suite(graph: dict[str, Any] | None, catalog: ModuleCatalog) -> str:
    if not isinstance(graph, dict):
        return "morphic"
    suite = str(graph.get("suite") or "").strip()
    if suite:
        return suite
    suites: set[str] = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        module_id = str(node.get("module_id") or "").strip()
        if not module_id:
            continue
        module = catalog.get_module(module_id)
        runtime = module.get("runtime") if isinstance(module, dict) else {}
        node_suite = str(runtime.get("suite") or "").strip() if isinstance(runtime, dict) else ""
        if node_suite:
            suites.add(node_suite)
    return suites.pop() if len(suites) == 1 else "morphic"


def _tail_text(text: str, *, limit: int = 12000) -> str:
    return text if len(text) <= limit else text[-limit:]


def _safe_slug(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text).strip(".-")
    return text[:80] or fallback


def _first_header(request: Request, names: tuple[str, ...]) -> str:
    for name in names:
        value = str(request.headers.get(name) or "").strip()
        if value:
            return value
    return ""


def _unix_user_hint_from_email(email: str) -> str:
    domain = str(os.environ.get("MORPHIC_AGENT_UNIX_USER_EMAIL_DOMAIN") or "").strip().lower()
    value = str(email or "").strip().lower()
    if not domain or not value or "@" not in value:
        return ""
    local, email_domain = value.split("@", 1)
    if domain and email_domain != domain:
        return ""
    return _safe_slug(local, "")


def _request_context(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    raw_email = _first_header(
        request,
        (
            "x-auth-request-email",
            "x-forwarded-email",
            "x-remote-email",
        ),
    )
    raw_user = _first_header(
        request,
        (
            "x-remote-user",
            "x-auth-request-preferred-username",
            "x-forwarded-user",
            "x-auth-request-user",
            "remote-user",
        ),
    )
    identity = raw_email or raw_user or "anonymous"
    unix_user_hint = _unix_user_hint_from_email(raw_email)
    raw_session = (
        str(body.get("client_session_id") or body.get("session_id") or "").strip()
        or _first_header(request, ("x-morphic-session", "x-workbench-session"))
        or str(request.cookies.get("morphic_session") or "").strip()
        or str(body.get("thread_id") or "").strip()
    )
    session_supplied = bool(raw_session)
    if not raw_session:
        raw_session = f"request-{uuid.uuid4().hex[:12]}"
    return {
        "user": identity,
        "user_slug": _safe_slug(identity, "anonymous"),
        "email": raw_email,
        "auth_user": raw_user,
        "unix_user_hint": unix_user_hint,
        "storage_user": unix_user_hint or _safe_slug(identity, "anonymous"),
        "auth_provider": _first_header(request, ("x-auth-provider",)) or ("trusted_proxy" if raw_email or raw_user else ""),
        "session_id": raw_session,
        "session_slug": _safe_slug(raw_session, "session"),
        "session_supplied": session_supplied,
        "conversation_id": str(body.get("conversation_id") or body.get("thread_id") or "").strip(),
        "trusted_proxy": _first_header(request, ("x-morphic-trusted-proxy",)),
        "client_host": request.client.host if request.client else "",
    }


def _bundle_out_root(
    request: Request,
    body: dict[str, Any],
    *,
    graph_id: str,
    env_var: str,
    default_root: str,
) -> tuple[Path, dict[str, Any]]:
    context = _request_context(request, body)
    base = Path(str(os.environ.get(env_var) or default_root)).expanduser()
    run_id = _safe_slug(body.get("run_id") or f"run-{uuid.uuid4().hex[:12]}", "run")
    root = base / context["storage_user"] / context["session_slug"] / run_id
    root.mkdir(parents=True, exist_ok=True)
    return root, context


def _bundle_owner_allows_request(bundle_record: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str | None]:
    manifest = bundle_record.get("manifest") if isinstance(bundle_record.get("manifest"), dict) else {}
    owner = manifest.get("request_context") if isinstance(manifest.get("request_context"), dict) else {}
    owner_user = str(owner.get("user") or "anonymous")
    request_user = str(context.get("user") or "anonymous")
    if owner_user != "anonymous" and request_user != owner_user:
        return False, f"Bundle is owned by `{owner_user}`, but this request is from `{request_user}`."
    owner_session = str(owner.get("session_id") or "")
    request_session = str(context.get("session_id") or "")
    if bool(owner.get("session_supplied")) and bool(context.get("session_supplied")) and owner_session != request_session:
        return False, "Bundle was generated by a different workbench session."
    return True, None


def _bundle_zip_bytes(bundle: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(bundle)
            if "__pycache__" in rel.parts or rel.name.endswith((".pyc", ".pyo")):
                continue
            archive.write(path, f"{bundle.name}/{rel.as_posix()}")
    return buffer.getvalue()


def _append_unique(items: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _execution_owner_allows_request(execution_result: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str | None]:
    owner = execution_result.get("request_context") if isinstance(execution_result.get("request_context"), dict) else {}
    owner_user = str(owner.get("user") or "anonymous")
    request_user = str(context.get("user") or "anonymous")
    if owner_user != "anonymous" and request_user != owner_user:
        return False, f"Execution is owned by `{owner_user}`, but this request is from `{request_user}`."
    return True, None


def _artifact_id_for_path(path: Path) -> str:
    return f"artifact-{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:16]}"


def _resolve_output_candidate(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _output_candidates_from_params(params: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for raw_key, raw_value in params.items():
        if not isinstance(raw_value, (str, os.PathLike)):
            continue
        key = str(raw_key).lower()
        text = str(raw_value).strip()
        if not text:
            continue
        if key in {"design", "reference", "skip_star", "bam_sort", "title"}:
            continue
        if text.startswith("~"):
            continue
        path = _resolve_output_candidate(text)
        if key == "output_prefix" or key.endswith("_output_prefix"):
            for suffix in (".html", ".json", ".png", ".log"):
                try:
                    candidates.append(path.with_suffix(suffix))
                except ValueError:
                    continue
        elif "output" in key or key.endswith(("_html", "_json", "_png", "_csv", "_tsv", "_txt", "_dir")):
            candidates.append(path)
    return candidates


def _output_candidate_role(path: Path, params: dict[str, Any], bundle: Path) -> str:
    try:
        path.relative_to(bundle / "outputs")
        return "run_output"
    except ValueError:
        pass
    for raw_key, raw_value in params.items():
        if not isinstance(raw_value, (str, os.PathLike)):
            continue
        key = str(raw_key).lower()
        text = str(raw_value).strip()
        if not text:
            continue
        candidate = _resolve_output_candidate(text)
        if key == "output_prefix" or key.endswith("_output_prefix"):
            try:
                if path == candidate.with_suffix(path.suffix):
                    return key
            except ValueError:
                pass
        elif path == candidate:
            return key
    return "run_output"


def _artifact_type_for_output(path: Path, *, role: str = "") -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    role_text = role.lower()
    if suffix in {".html", ".htm"}:
        return "html_report" if "report" in name or "qc" in name or "prefix" in role_text else "html"
    if suffix == ".json":
        return "structured_report_data" if "report" in name or "qc" in name or "prefix" in role_text else "json"
    if suffix == ".png":
        return "static_plot"
    if suffix == ".svg":
        return "vector_plot"
    if suffix in {".jpg", ".jpeg", ".gif", ".webp"}:
        return "image"
    if suffix == ".csv":
        return "table_csv"
    if suffix in {".tsv", ".tab"}:
        return "table_tsv"
    if suffix in {".h5ad", ".h5mu", ".h5"}:
        return "single_cell_data"
    if suffix in {".bam", ".sam", ".cram"}:
        return "alignment_file"
    if suffix in {".log", ".txt"}:
        return "text_log"
    return "file"


def _describe_output_file(path: Path, *, role: str = "") -> str:
    artifact_type = _artifact_type_for_output(path, role=role)
    descriptions = {
        "html_report": "Interactive HTML report produced by the run.",
        "html": "HTML file produced by the run.",
        "structured_report_data": "Structured JSON data/metadata backing the generated report.",
        "json": "JSON output produced by the run.",
        "static_plot": "Static plot image produced by the run.",
        "vector_plot": "Vector plot image produced by the run.",
        "image": "Image output produced by the run.",
        "table_csv": "Comma-separated table produced by the run.",
        "table_tsv": "Tab-separated table produced by the run.",
        "single_cell_data": "Single-cell or multimodal analysis object produced by the run.",
        "alignment_file": "Read alignment output produced by the run.",
        "text_log": "Text log or summary produced by the run.",
        "file": "Output file produced by the run.",
    }
    return descriptions.get(artifact_type, "Output file produced by the run.")


def _iter_files(paths: list[Path], *, max_files: int = 5000) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        if resolved.is_file():
            key = str(resolved)
            if key not in seen:
                files.append(resolved)
                seen.add(key)
        elif resolved.is_dir():
            for child in resolved.rglob("*"):
                if len(files) >= max_files:
                    return files
                if not child.is_file():
                    continue
                try:
                    child_resolved = child.resolve()
                except OSError:
                    child_resolved = child.absolute()
                key = str(child_resolved)
                if key in seen:
                    continue
                files.append(child_resolved)
                seen.add(key)
        if len(files) >= max_files:
            break
    return files


def _artifact_candidate_paths(bundle: Path, params: dict[str, Any]) -> list[Path]:
    return [bundle / "outputs", *nextflow_artifact_candidate_paths(bundle, params), *_output_candidates_from_params(params)]


def _snapshot_artifact_files(bundle: Path, params: dict[str, Any]) -> dict[str, dict[str, int]]:
    snapshot: dict[str, dict[str, int]] = {}
    for file_path in _iter_files(_artifact_candidate_paths(bundle, params)):
        try:
            stat = file_path.stat()
        except OSError:
            continue
        snapshot[str(file_path)] = {"mtime_ns": stat.st_mtime_ns, "size_bytes": stat.st_size}
    return snapshot


def _viewer_for_artifact(path: Path) -> tuple[str | None, str]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html", "text/html"
    if suffix == ".json":
        return "json", "application/json"
    if suffix in {".txt", ".log", ".tsv", ".csv", ".md"}:
        return "text", mimetypes.guess_type(path.name)[0] or "text/plain"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        return "image", mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return None, mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _relative_artifact_path(path: Path, bundle: Path) -> str:
    try:
        return str(path.relative_to(bundle))
    except ValueError:
        return path.name


def _build_artifact_manifest(
    bundle: Path,
    params: dict[str, Any],
    *,
    before: dict[str, dict[str, int]],
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for file_path in _iter_files(_artifact_candidate_paths(bundle, params)):
        try:
            stat = file_path.stat()
        except OSError:
            continue
        key = str(file_path)
        previous = before.get(key)
        if previous and previous.get("mtime_ns") == stat.st_mtime_ns and previous.get("size_bytes") == stat.st_size:
            continue
        viewer, media_type = _viewer_for_artifact(file_path)
        role = _output_candidate_role(file_path, params, bundle)
        artifact_type = _artifact_type_for_output(file_path, role=role)
        files.append(
            {
                "artifact_id": _artifact_id_for_path(file_path),
                "name": file_path.name,
                "relative_path": _relative_artifact_path(file_path, bundle),
                "path": str(file_path),
                "role": role,
                "artifact_type": artifact_type,
                "description": _describe_output_file(file_path, role=role),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "media_type": media_type,
                "viewer": viewer,
                "viewable": viewer is not None,
            }
        )
    files.sort(key=lambda item: (str(item.get("relative_path") or ""), str(item.get("path") or "")))
    return {
        "schema": "morphic.execution_artifact_manifest/v0",
        "manifest_kind": "produced_outputs",
        "bundle_path": str(bundle),
        "file_count": len(files),
        "files": files,
    }


def _artifact_manifest_with_links(execution_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    linked = {**manifest, "files": []}
    for item in manifest.get("files") or []:
        if not isinstance(item, dict):
            continue
        artifact_id = str(item.get("artifact_id") or "")
        payload = dict(item)
        if artifact_id:
            payload["download_url"] = f"/api/executions/{execution_id}/artifacts/{artifact_id}?download=1"
            if item.get("viewable"):
                payload["view_url"] = f"/api/executions/{execution_id}/artifacts/{artifact_id}"
        linked["files"].append(payload)
    return linked


def _load_execution_result_file(result_path: Path) -> dict[str, Any]:
    if not result_path.is_file():
        return {}
    loaded = json.loads(result_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _top_execution_status(execution_result: dict[str, Any]) -> str:
    if execution_result.get("status") == "verified":
        return "verified"
    if execution_result.get("status") == "completed":
        return "completed"
    return "failed"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _split_root_list(value: str) -> list[str]:
    roots: list[str] = []
    for chunk in value.replace("\n", os.pathsep).replace(",", os.pathsep).split(os.pathsep):
        text = chunk.strip()
        if text:
            roots.append(text)
    return roots


def _file_browser_roots() -> list[dict[str, str]]:
    repo_root = _repo_root()
    candidates: list[tuple[str, Path]] = []
    configured = os.environ.get("MORPHIC_AGENT_FILE_BROWSER_ROOTS", "")
    for index, raw in enumerate(_split_root_list(configured), start=1):
        candidates.append((f"configured {index}", Path(raw).expanduser()))
    for label, env_var in (
        ("bundle root", "MORPHIC_AGENT_BUNDLE_ROOT"),
        ("STAR MVP bundle root", "MORPHIC_AGENT_STAR_MVP_BUNDLE_ROOT"),
        ("STAR Suite", "STAR_SUITE_ROOT"),
        ("CHROMAP Suite", "CHROMAP_SUITE_ROOT"),
        ("Multiomics Suite", "MULTIOMICS_SUITE_ROOT"),
    ):
        raw = os.environ.get(env_var)
        if raw:
            candidates.append((label, Path(raw).expanduser()))
    candidates.extend(
        [
            ("Demo data", repo_root / "data"),
            ("Generated run directories", Path("/tmp/morphic-agent-bundles")),
            ("STAR MVP run directories", Path("/tmp/morphic-star-graph-mvp-agent")),
        ]
    )
    roots: list[dict[str, str]] = []
    seen: set[str] = set()
    for label, path in candidates:
        resolved = _resolve_path_lenient(path)
        if not resolved.is_dir():
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append({"label": label, "path": key})
    return roots


def _allowed_file_browser_root(path: Path, roots: list[dict[str, str]]) -> Path | None:
    for root in roots:
        root_path = _resolve_path_lenient(Path(root["path"]))
        if path == root_path or _path_is_under(path, root_path):
            return root_path
    return None


def _path_has_hidden_component(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return any(part.startswith(".") for part in relative.parts)


def _file_browser_entry(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        stat = None
    kind = "directory" if path.is_dir() else "file"
    if path.is_symlink():
        kind = f"{kind}_symlink"
    return {
        "name": path.name or str(path),
        "path": str(_resolve_path_lenient(path)),
        "kind": kind,
        "is_dir": path.is_dir(),
        "size_bytes": stat.st_size if stat and path.is_file() else None,
        "mtime_ns": stat.st_mtime_ns if stat else None,
    }


def _list_file_browser_directory(path: Path, roots: list[dict[str, str]], *, limit: int = 500) -> tuple[list[dict[str, Any]], bool]:
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except PermissionError:
        raise
    except OSError:
        children = []
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            child_resolved = _resolve_path_lenient(child)
        except OSError:
            continue
        if _allowed_file_browser_root(child_resolved, roots) is None:
            continue
        entries.append(_file_browser_entry(child_resolved))
        if len(entries) >= limit:
            truncated = True
            break
    return entries, truncated


def create_app(
    *,
    db_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
) -> Starlette:
    service = WorkbenchService.create(
        db_path=db_path or os.environ.get("MORPHIC_AGENT_DB") or tempfile.mktemp(prefix="morphic-agent-", suffix=".sqlite3"),
        catalog_path=catalog_path,
    )
    store = service.store
    catalog = service.catalog
    graph_index = service.graph_index
    graph_tools = service.graph_tools
    bundle_tools = service.bundle_tools
    star_mvp_bundles: dict[str, str] = {}

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "morphic-agent"})

    async def model_status(request: Request) -> JSONResponse:
        probe = str(request.query_params.get("probe") or "").strip().lower() in {"1", "true", "yes"}
        return JSONResponse(service.model_status(probe=probe))

    async def index(_: Request) -> HTMLResponse:
        return HTMLResponse(WORKBENCH_HTML)

    async def session_info(request: Request) -> JSONResponse:
        body: dict[str, Any] = {}
        context = _request_context(request, body)
        response = JSONResponse(
            {
                "status": "ok",
                "request_context": context,
                "auth_note": (
                    "X-Remote-User/X-Forwarded-User are trusted only when set by the reverse proxy. "
                    "The app uses them for bundle isolation and audit, not as a complete authorization system."
                ),
            }
        )
        if not context["session_supplied"]:
            response.set_cookie("morphic_session", context["session_id"], httponly=False, samesite="lax")
        return response

    async def file_browser(request: Request) -> JSONResponse:
        roots = _file_browser_roots()
        if not roots:
            return JSONResponse({"status": "blocked", "error": "no file browser roots are configured"}, status_code=503)
        raw_path = str(request.query_params.get("path") or "").strip()
        if raw_path:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = (Path.cwd() / candidate).resolve()
            target = _resolve_path_lenient(candidate)
            allowed_root = _allowed_file_browser_root(target, roots)
            if allowed_root is None:
                return JSONResponse(
                    {
                        "status": "blocked",
                        "error": "path is outside the configured file browser roots",
                        "path": str(target),
                        "roots": roots,
                    },
                    status_code=403,
                )
            if _path_has_hidden_component(target, allowed_root):
                return JSONResponse({"status": "blocked", "error": "hidden paths are not browsable", "path": str(target), "roots": roots}, status_code=403)
            if not target.exists():
                return JSONResponse({"status": "not_found", "error": "path does not exist", "path": str(target), "roots": roots}, status_code=404)
            browse_dir = target if target.is_dir() else target.parent
            parent = browse_dir.parent
            parent_path = str(parent) if _allowed_file_browser_root(_resolve_path_lenient(parent), roots) else None
            try:
                entries, truncated = _list_file_browser_directory(browse_dir, roots)
            except PermissionError:
                return JSONResponse({"status": "blocked", "error": "permission denied", "path": str(browse_dir), "roots": roots}, status_code=403)
            return JSONResponse(
                {
                    "status": "ok",
                    "path": str(browse_dir),
                    "selected_path": str(target) if target.is_file() else "",
                    "parent": parent_path,
                    "roots": roots,
                    "entries": entries,
                    "truncated": truncated,
                }
            )
        return JSONResponse(
            {
                "status": "ok",
                "path": "",
                "parent": None,
                "roots": roots,
                "entries": [
                    {"name": root["label"], "path": root["path"], "kind": "directory", "is_dir": True, "size_bytes": None, "mtime_ns": None}
                    for root in roots
                ],
                "truncated": False,
            }
        )

    async def suites(_: Request) -> JSONResponse:
        return JSONResponse(service.suites())

    async def suite_recipes(request: Request) -> JSONResponse:
        suite_id = str(request.path_params.get("suite_id") or "").strip().lower()
        payload, status = service.suite_recipes(suite_id)
        return JSONResponse(payload, status_code=status)

    async def agent_chat(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        payload, status = service.assistant_message(body, request_context=_request_context(request, body))
        return JSONResponse(payload, status_code=status)

    async def thread_turns(request: Request) -> JSONResponse:
        thread_id = str(request.path_params.get("thread_id") or "").strip()
        raw_limit = str(request.query_params.get("limit") or "50")
        try:
            limit = max(1, min(200, int(raw_limit)))
        except ValueError:
            limit = 50
        if not thread_id:
            return JSONResponse({"error": "thread_id is required"}, status_code=400)
        context = _request_context(request, {})
        payload, status = service.thread_turns(thread_id, owner_user=context["storage_user"], limit=limit)
        return JSONResponse(payload, status_code=status)

    async def conversations_collection(request: Request) -> JSONResponse:
        context = _request_context(request, {})
        if request.method == "GET":
            try:
                limit = int(request.query_params.get("limit") or 50)
                payload = service.list_conversations(
                    owner_user=context["storage_user"],
                    status=str(request.query_params.get("status") or "active"),
                    query=str(request.query_params.get("q") or request.query_params.get("query") or ""),
                    limit=limit,
                )
            except ValueError as exc:
                return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
            return JSONResponse(payload)
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        context = _request_context(request, body)
        payload = service.create_conversation(
            owner_user=context["storage_user"],
            session_id=context["session_slug"],
            title=str(body.get("title") or ""),
            metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
        )
        return JSONResponse(payload, status_code=201)

    async def conversation_item(request: Request) -> JSONResponse:
        conversation_id = str(request.path_params.get("conversation_id") or "").strip()
        context = _request_context(request, {})
        if request.method == "GET":
            try:
                turn_limit = int(request.query_params.get("turn_limit") or 100)
                run_limit = int(request.query_params.get("run_limit") or 25)
            except ValueError:
                return JSONResponse({"status": "error", "error": "limits must be integers"}, status_code=400)
            payload, status = service.get_conversation(
                conversation_id,
                owner_user=context["storage_user"],
                turn_limit=turn_limit,
                run_limit=run_limit,
            )
            return JSONResponse(payload, status_code=status)
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        context = _request_context(request, body)
        payload, status = service.update_conversation(
            conversation_id,
            owner_user=context["storage_user"],
            session_id=context["session_slug"],
            title=str(body.get("title")) if "title" in body else None,
            status=str(body.get("status")) if "status" in body else None,
        )
        return JSONResponse(payload, status_code=status)

    async def conversation_fork(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        context = _request_context(request, body)
        payload, status = service.fork_conversation(
            str(request.path_params.get("conversation_id") or ""),
            owner_user=context["storage_user"],
            session_id=context["session_slug"],
            title=str(body.get("title") or ""),
            include_history=body.get("include_history") is not False,
        )
        return JSONResponse(payload, status_code=status)

    async def list_modules(request: Request) -> JSONResponse:
        query = str(request.query_params.get("q") or "")
        return JSONResponse(service.list_modules(query))

    async def get_module(request: Request) -> JSONResponse:
        module_id = str(request.path_params.get("module_id") or "")
        payload, status = service.get_module(module_id)
        return JSONResponse(payload, status_code=status)

    async def nfcore_harvest(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        try:
            timeout = float(body.get("timeout") or 20.0)
        except (TypeError, ValueError):
            timeout = 20.0
        try:
            payload = service.harvest_nfcore_pipeline(
                pipeline_path=str(body.get("pipeline_path") or body.get("pipeline") or ""),
                schema_path=body.get("schema_path"),
                modules_json_path=body.get("modules_json_path") or body.get("modules_json"),
                release=str(body.get("release") or "").strip() or None,
                cache_root=body.get("cache_root"),
                allow_network=bool(body.get("allow_network")),
                timeout=timeout,
                decompose_source=bool(body.get("decompose_source", True)),
                strict_decomposition=bool(body.get("strict_decomposition", False)),
                provenance={"harvested_by": "api_nfcore_harvest", "request_context": _request_context(request, body)},
            )
        except (FileNotFoundError, ValueError, TypeError) as exc:
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
        status_code = 201 if payload.get("status") == "ok" else 400
        return JSONResponse(payload, status_code=status_code)

    async def nfcore_decompose(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        pipeline_path = str(body.get("pipeline_path") or "").strip()
        if not pipeline_path:
            return JSONResponse({"status": "error", "error": "pipeline_path is required"}, status_code=400)
        try:
            payload = service.decompose_nfcore_pipeline(
                pipeline_path,
                strict=bool(body.get("strict", False)),
            )
        except (FileNotFoundError, ValueError, TypeError, OSError) as exc:
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
        return JSONResponse(payload)

    async def nfcore_register(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        schema_path = str(body.get("schema_path") or "").strip()
        if not schema_path:
            return JSONResponse({"status": "error", "error": "schema_path is required"}, status_code=400)
        try:
            payload = service.register_nfcore_recipe(
                schema_path=schema_path,
                modules_json_path=body.get("modules_json_path") or body.get("modules_json"),
                cache_root=body.get("cache_root"),
                provenance={"harvested_by": "api_nfcore_register", "request_context": _request_context(request, body)},
            )
        except (FileNotFoundError, ValueError, TypeError) as exc:
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
        status_code = 201 if payload.get("status") == "ok" else 400
        return JSONResponse(payload, status_code=status_code)

    async def nfcore_pipelines(request: Request) -> JSONResponse:
        query = str(request.query_params.get("q") or request.query_params.get("query") or "")
        try:
            limit = max(1, min(100, int(request.query_params.get("limit") or 20)))
        except ValueError:
            limit = 20
        return JSONResponse(service.list_nfcore_pipelines(query=query, limit=limit))

    async def nfcore_recipe(request: Request) -> JSONResponse:
        identifier = str(request.path_params.get("identifier") or "").strip()
        payload, status = service.get_nfcore_recipe(identifier)
        return JSONResponse(payload, status_code=status)

    async def nfcore_validation_matrix(request: Request) -> JSONResponse:
        try:
            limit = max(1, min(500, int(request.query_params.get("limit") or 100)))
        except ValueError:
            limit = 100
        render = str(request.query_params.get("render") or "1").strip().lower() not in {"0", "false", "no"}
        preflight = str(request.query_params.get("preflight") or "1").strip().lower() not in {"0", "false", "no"}
        payload = service.nfcore_validation_matrix(
            out_root=str(request.query_params.get("out_root") or "").strip() or None,
            execution_location=str(request.query_params.get("execution_location") or "server"),
            render=render,
            preflight=preflight,
            limit=limit,
        )
        return JSONResponse(payload)

    async def nfcore_validations(request: Request) -> JSONResponse:
        try:
            limit = max(1, min(500, int(request.query_params.get("limit") or 100)))
        except ValueError:
            limit = 100
        payload = service.list_nfcore_validations(
            graph_id=str(request.query_params.get("graph_id") or ""),
            status=str(request.query_params.get("status") or ""),
            comparator_kind=str(request.query_params.get("comparator_kind") or ""),
            executor=str(request.query_params.get("executor") or ""),
            fixture_id=str(request.query_params.get("fixture_id") or ""),
            profile=str(request.query_params.get("profile") or ""),
            source_manifest_hash=str(request.query_params.get("source_manifest_hash") or ""),
            limit=limit,
        )
        return JSONResponse(payload)

    async def nfcore_reference_validation(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(body.get("graph_id") or "").strip()
        run_id = str(body.get("run_id") or "").strip()
        manifest = body.get("comparison_manifest") if isinstance(body.get("comparison_manifest"), dict) else body.get("manifest")
        if not graph_id:
            return JSONResponse({"status": "error", "error": "graph_id is required"}, status_code=400)
        if not isinstance(manifest, dict):
            return JSONResponse({"status": "error", "error": "comparison_manifest is required"}, status_code=400)
        try:
            payload, status = service.record_nfcore_reference_validation(
                graph_id=graph_id,
                comparison_manifest=manifest,
                run_id=run_id or None,
            )
        except ValueError as exc:
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
        return JSONResponse(payload, status_code=status)

    async def graph_draft(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        goal = str(body.get("goal") or "").strip()
        include_launchpad = bool(body.get("include_launchpad", True))
        thread_id = str(body.get("thread_id") or "").strip()
        log_interaction = bool(body.get("log_interaction") or thread_id)
        try:
            payload = service.draft_graph(
                goal,
                include_launchpad=include_launchpad,
                thread_id=thread_id,
                log_interaction=log_interaction,
                request_context=_request_context(request, body),
            )
        except PermissionError as exc:
            return JSONResponse({"status": "forbidden", "error": str(exc)}, status_code=403)
        except ValueError as exc:
            return JSONResponse({"status": "blocked", "error": str(exc)}, status_code=409)
        return JSONResponse(payload)

    async def graph_get(request: Request) -> JSONResponse:
        graph_id = str(request.path_params.get("graph_id") or "")
        payload, status = service.get_graph(graph_id)
        return JSONResponse(payload, status_code=status)

    async def graph_projection_rebuild(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        projection_version = str(body.get("projection_version") or "morphic-agent-v0")
        return JSONResponse(service.rebuild_graph_projection(projection_version))

    async def graph_projection_status(request: Request) -> JSONResponse:
        projection_version = str(request.path_params.get("projection_version") or "morphic-agent-v0")
        return JSONResponse(service.projection_status(projection_version))

    async def graph_verified_search(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        return JSONResponse(service.find_verified_subgraphs(body))

    async def graph_search(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        filters = body.get("filters") if isinstance(body.get("filters"), dict) else {}
        try:
            limit = int(body.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        return JSONResponse(
            service.search_graphs(
                query=str(body.get("query") or ""),
                filters=filters,
                limit=limit,
            )
        )

    async def graph_store_verified(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "")
        execution_manifest = body.get("execution_manifest") if isinstance(body.get("execution_manifest"), dict) else {}
        payload, status = service.store_verified_recipe(graph_id, execution_manifest)
        return JSONResponse(payload, status_code=status)

    async def graph_params_schema(request: Request) -> JSONResponse:
        graph_id = str(request.path_params.get("graph_id") or "")
        payload, status = service.params_schema(graph_id)
        return JSONResponse(payload, status_code=status)

    async def graph_params_validate(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "")
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        return JSONResponse(service.validate_params(graph_id, params))

    async def graph_render(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "")
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        try:
            execution_location = _execution_location_from_body(body)
        except ValueError as exc:
            return JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        if body.get("out_root"):
            out_root = Path(str(body.get("out_root"))).expanduser()
            context = _request_context(request, body)
        else:
            out_root, context = _bundle_out_root(
                request,
                body,
                graph_id=graph_id,
                env_var="MORPHIC_AGENT_BUNDLE_ROOT",
                default_root="/tmp/morphic-agent-bundles",
            )
        return JSONResponse(
            service.render_bundle(
                graph_id,
                params,
                out_root=out_root,
                request_context=context,
                execution_location=execution_location.as_dict(),
                run_id=str(body.get("run_id") or "").strip() or None,
            )
        )

    async def graph_preflight(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "")
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        try:
            execution_location = _execution_location_from_body(body)
        except ValueError as exc:
            return JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        return JSONResponse(
            service.preflight_bundle(
                graph_id,
                params,
                execution_location=execution_location.as_dict(),
                bundle_path=body.get("bundle_path"),
                run_id=str(body.get("run_id") or "").strip() or None,
            )
        )

    async def graph_execution_review(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "").strip()
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        context = _request_context(request, body)
        try:
            execution_location = _execution_location_from_body(body)
        except ValueError as exc:
            return JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        review = service.execution_review_request(
            graph_id,
            params,
            proposed_execution_location=execution_location.as_dict(),
            bundle_path=body.get("bundle_path"),
            review_stage=str(body.get("review_stage") or "before_render"),
            request_context=context,
            run_id=str(body.get("run_id") or "").strip() or None,
        )
        if review.get("status") == "not_found":
            return JSONResponse(review, status_code=404)
        human_review = body.get("human_review") if isinstance(body.get("human_review"), dict) else None
        if human_review is None and not body.get("review_action"):
            return JSONResponse(
                {
                    **review,
                    "status": "needs_user_input",
                    "interaction": {
                        "mode": "http_form",
                        "action": "request",
                        "response_schema": review.get("response_schema"),
                    },
                    "human_review": None,
                    "run_blocker": "User review is required before this Workbench step can proceed.",
                }
            )
        payload = service.complete_execution_review(
            review,
            human_review,
            action=str(body.get("review_action") or "accept"),
            interaction_mode="http_form",
        )
        return JSONResponse(payload)

    def _registered_bundle_for_graph(
        graph_id: str,
        raw_bundle_path: Any,
        context: dict[str, Any],
    ) -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None, int]:
        bundle_path = str(raw_bundle_path or "").strip()
        if not graph_id:
            return None, None, {"error": "graph_id is required"}, 400
        if not bundle_path:
            return None, None, {"error": "bundle_path is required", "run_blocker": "Generate a run directory first."}, 400

        bundle = Path(bundle_path).expanduser()
        try:
            bundle = bundle.resolve()
        except OSError:
            bundle = bundle.absolute()
        if not bundle.is_dir():
            return None, None, {"status": "blocked", "run_blocker": "Bundle path is not a directory.", "bundle_path": str(bundle)}, 400

        bundle_record = store.get_bundle_by_path(bundle)
        if bundle_record is None:
            return (
                None,
                None,
                {
                    "status": "blocked",
                    "run_blocker": "Bundle path is not registered as a generated workbench bundle.",
                    "bundle_path": str(bundle),
                },
                400,
            )
        if str(bundle_record.get("graph_id") or "") != graph_id:
            return (
                None,
                None,
                {
                    "status": "blocked",
                    "run_blocker": "Bundle graph does not match requested graph.",
                    "graph_id": graph_id,
                    "bundle_graph_id": bundle_record.get("graph_id"),
                },
                400,
            )
        owner_allowed, owner_blocker = _bundle_owner_allows_request(bundle_record, context)
        if not owner_allowed:
            return (
                None,
                None,
                {
                    "status": "blocked",
                    "graph_id": graph_id,
                    "bundle_path": str(bundle),
                    "run_blocker": owner_blocker,
                    "request_context": context,
                },
                403,
            )
        return bundle, bundle_record, None, 200

    async def graph_execution_diagnostic(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "").strip()
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        context = _request_context(request, body)
        try:
            execution_location = _execution_location_from_body(body)
        except ValueError as exc:
            return JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        payload, status = service.execution_diagnostic(
            graph_id,
            params,
            execution_location=execution_location.as_dict(),
            bundle_path=body.get("bundle_path"),
            request_context=context,
            run_id=str(body.get("run_id") or "").strip() or None,
        )
        return JSONResponse(payload, status_code=status)

    async def graph_bundle_zip(request: Request) -> Response:
        graph_id = str(request.path_params.get("graph_id") or "").strip()
        context = _request_context(request, {"client_session_id": request.query_params.get("client_session_id") or ""})
        bundle, _, bundle_error, status_code = _registered_bundle_for_graph(
            graph_id,
            request.query_params.get("bundle_path"),
            context,
        )
        if bundle_error is not None or bundle is None:
            return JSONResponse(bundle_error or {"error": "bundle_path is required"}, status_code=status_code)

        filename = f"{_safe_slug(bundle.name, 'morphic-bundle')}.zip"
        return Response(
            _bundle_zip_bytes(bundle),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def execution_locations(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "schema": "morphic.execution_locations/v0",
                "default_location_id": DEFAULT_EXECUTION_LOCATION_ID,
                "locations": list_execution_locations(),
            }
        )

    async def runs_collection(request: Request) -> JSONResponse:
        if request.method == "GET":
            graph_id = str(request.query_params.get("graph_id") or "").strip() or None
            try:
                limit = int(request.query_params.get("limit") or 25)
            except (TypeError, ValueError):
                limit = 25
            context = _request_context(request, {})
            return JSONResponse(
                service.list_runs(graph_id=graph_id, limit=limit, owner_user=context["storage_user"])
            )

        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(body.get("graph_id") or "").strip()
        if not graph_id:
            return JSONResponse({"status": "blocked", "error": "graph_id is required"}, status_code=400)
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        try:
            execution_location = _execution_location_from_body(body)
        except ValueError as exc:
            return JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        try:
            run = service.start_run(
                graph_id,
                params,
                execution_location=execution_location.as_dict(),
                request_context=_request_context(request, body),
            )
        except PermissionError as exc:
            return JSONResponse({"status": "forbidden", "error": str(exc)}, status_code=403)
        except ValueError as exc:
            return JSONResponse({"status": "blocked", "error": str(exc)}, status_code=400)
        return JSONResponse({"status": "created", "run_id": run["run_id"], "run": run}, status_code=201)

    async def run_get(request: Request) -> JSONResponse:
        context = _request_context(request, {})
        payload, status = service.get_run(
            str(request.path_params.get("run_id") or ""),
            owner_user=context["storage_user"],
        )
        return JSONResponse(payload, status_code=status)

    async def run_attach_validation(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        payload, status = service.attach_validation_to_run(
            run_id=str(request.path_params.get("run_id") or ""),
            validation_id=str(body.get("validation_id") or ""),
            owner_user=_request_context(request, body)["storage_user"],
        )
        return JSONResponse(payload, status_code=status)

    async def star_mvp_plan(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        goal = str(body.get("goal") or "post MEX h5ad QC and plots").strip()
        try:
            graph = graph_index.plan_star_mvp(goal)
        except Exception as exc:
            return JSONResponse({"error": "STAR MVP plan failed", "message": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "status": "planned",
                "graph_id": graph.get("graph_id"),
                "workflow_graph": graph,
                "projection": graph_index.rebuild_graph_index("star-mvp-api-v0"),
            }
        )

    async def star_mvp_materialize(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(body.get("graph_id") or "").strip()
        goal = str(body.get("goal") or "post MEX h5ad QC and plots").strip()
        try:
            graph_payload = graph_tools.get_graph(graph_id) if graph_id else graph_index.plan_star_mvp(goal)
            if not graph_payload:
                return JSONResponse({"error": "STAR MVP graph not found", "graph_id": graph_id}, status_code=404)
            graph = _recipe_graph_from_payload(graph_payload)
        except Exception as exc:
            return JSONResponse({"error": "STAR MVP graph not found", "message": str(exc)}, status_code=404)
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        if body.get("out_root"):
            out_root = _safe_star_mvp_bundle_root(body.get("out_root"))
            context = _request_context(request, body)
        else:
            candidate_root, context = _bundle_out_root(
                request,
                body,
                graph_id=graph.graph_id,
                env_var="MORPHIC_AGENT_STAR_MVP_BUNDLE_ROOT",
                default_root="/tmp/morphic-star-graph-mvp-agent",
            )
            out_root = _safe_star_mvp_bundle_root(candidate_root)
        bundle_path = materialize_star_mvp_bundle(graph, out_root, params=params)
        star_mvp_bundles[graph.graph_id] = str(bundle_path)
        star_mvp_bundles[f"{context['session_id']}:{graph.graph_id}"] = str(bundle_path)
        bundle_record = store.record_bundle(
            graph.graph_id,
            bundle_path,
            {
                "schema": "morphic.star_mvp_bundle_manifest/v0",
                "graph_id": graph.graph_id,
                "request_context": context,
                "files": sorted(item.name for item in bundle_path.iterdir()),
            },
        )
        return JSONResponse(
            {
                "status": "materialized",
                "graph_id": graph.graph_id,
                "bundle_path": str(bundle_path),
                "bundle_id": bundle_record.get("bundle_id"),
                "request_context": context,
                "files": sorted(item.name for item in bundle_path.iterdir()),
                "workflow_graph": graph.as_dict(),
                "headless": {
                    "command": f"bash {bundle_path / 'run.sh'}",
                    "script": (bundle_path / "run.sh").read_text(encoding="utf-8"),
                    "script_filename": "run.sh",
                },
            }
        )

    def build_star_mvp_preflight_result(
        graph_id: str,
        goal: str,
        params_override: dict[str, Any] | None = None,
        execution_location_request: Any = None,
    ) -> tuple[RecipeGraph, dict[str, Any]]:
        execution_location = resolve_execution_location(execution_location_request)
        graph_payload = graph_tools.get_graph(graph_id) if graph_id else graph_index.plan_star_mvp(goal)
        if not graph_payload:
            raise LookupError(f"STAR MVP graph not found: {graph_id}")
        graph = _recipe_graph_from_payload(graph_payload)

        defaults = graph.execution.get("default_params") if isinstance(graph.execution.get("default_params"), dict) else {}
        params = {**defaults, **(params_override or {})}
        checks: list[dict[str, Any]] = []
        blockers: list[str] = []
        mode = str(graph.execution.get("mode") or "")
        if mode == "verify_artifacts":
            for key in graph.execution.get("required_paths") or []:
                raw = params.get(key)
                path = Path(str(raw or "")).expanduser()
                exists = path.exists()
                checks.append({"check": f"path exists: {key}", "status": "pass" if exists else "fail", "path": str(path)})
                if not exists:
                    blockers.append(f"missing path: {key}")
        elif mode == "external_script":
            script = Path(str(graph.execution.get("script") or "")).expanduser()
            script_ok = script.is_file()
            checks.append({"check": "external smoke script exists", "status": "pass" if script_ok else "fail", "path": str(script)})
            if not script_ok:
                blockers.append("external smoke script is missing")
            outdir = str(params.get("outdir") or "").strip()
            if outdir:
                parent = Path(outdir).expanduser().parent
                existing_parent = parent
                while not existing_parent.exists() and existing_parent.parent != existing_parent:
                    existing_parent = existing_parent.parent
                writable = existing_parent.exists() and os.access(existing_parent, os.W_OK)
                checks.append({"check": "output parent is writable or creatable", "status": "pass" if writable else "fail", "path": str(parent)})
                if not writable:
                    blockers.append("output parent is not writable")
            else:
                checks.append({"check": "outdir is set or bundle default will be used", "status": "pass"})
        else:
            blockers.append(f"no STAR MVP preflight adapter for execution mode: {mode or 'unknown'}")
            checks.append({"check": "preflight adapter registered", "status": "fail"})

        status = "preflight_passed" if not blockers else "blocked"
        result = {
            "schema": "morphic.preflight_result/v0",
            "status": status,
            "graph_id": graph.graph_id,
            "execution_profile": "production",
            "mode": mode,
            "checks": checks,
            "blockers": blockers,
            "run_blocker": "; ".join(blockers) if blockers else None,
            "inputs_passed": not blockers,
            "executable_ready": not blockers,
        }
        result = annotate_preflight_for_location(result, execution_location)
        store.record_preflight(graph.graph_id, params, result)
        return graph, result

    async def star_mvp_preflight(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(body.get("graph_id") or "").strip()
        goal = str(body.get("goal") or "post MEX h5ad QC and plots").strip()
        try:
            _, result = build_star_mvp_preflight_result(
                graph_id,
                goal,
                body.get("params") if isinstance(body.get("params"), dict) else {},
                body.get("execution_location") if "execution_location" in body else body.get("execution_profile"),
            )
        except ValueError as exc:
            return JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": "STAR MVP graph not found", "message": str(exc)}, status_code=404)
        return JSONResponse(result)

    async def star_mvp_execute(request: Request) -> JSONResponse:
        if os.environ.get("MORPHIC_AGENT_ENABLE_LOCAL_SMOKE_EXECUTION") != "1":
            return JSONResponse(
                {
                    "status": "blocked",
                    "run_blocker": "Set MORPHIC_AGENT_ENABLE_LOCAL_SMOKE_EXECUTION=1 to allow local smoke execution.",
                },
                status_code=403,
            )
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(body.get("graph_id") or "").strip()
        context = _request_context(request, body)
        try:
            execution_location = _execution_location_from_body(body)
        except ValueError as exc:
            return JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        run_gate = execution_location_gate(execution_location, "execute")
        if not run_gate.allowed:
            return JSONResponse(
                {
                    "status": "blocked",
                    "graph_id": graph_id,
                    "execution_location": execution_location.as_dict(),
                    "execution_dispatch": execution_dispatch_for_location(execution_location),
                    "execution_run_gate": run_gate.as_dict(),
                    "run_blocker": run_gate.run_blocker,
                },
                status_code=400,
            )
        bundle_path = str(body.get("bundle_path") or star_mvp_bundles.get(graph_id) or "").strip()
        if not bundle_path:
            return JSONResponse({"error": "bundle_path is required"}, status_code=400)
        bundle = Path(bundle_path).expanduser().resolve()
        allowed_root = _safe_star_mvp_bundle_root()
        materialized = {str(Path(path).expanduser().resolve()) for path in star_mvp_bundles.values()}
        if str(bundle) not in materialized and not _bundle_under_allowed_root(bundle, allowed_root):
            return JSONResponse({"error": "bundle_path is outside the STAR MVP bundle root"}, status_code=400)
        bundle_record = store.get_bundle_by_path(bundle)
        if bundle_record is not None:
            owner_allowed, owner_blocker = _bundle_owner_allows_request(bundle_record, context)
            if not owner_allowed:
                return JSONResponse(
                    {
                        "status": "blocked",
                        "bundle_path": str(bundle),
                        "run_blocker": owner_blocker,
                        "request_context": context,
                    },
                    status_code=403,
                )
        timeout = int(body.get("timeout") or 120)
        try:
            result = run_materialized_bundle(bundle, timeout=timeout)
            result["execution_location"] = execution_location.as_dict()
            result["execution_dispatch"] = execution_dispatch_for_location(execution_location)
            graph_payload = json.loads((bundle / "workflow_graph.json").read_text(encoding="utf-8"))
            execution_record = store.record_execution(str(result.get("graph_id") or graph_payload["graph_id"]), result)
            verified_record = None
            if result.get("status") == "verified" and result.get("verified_recipe") is True:
                verified_record = graph_index.store_verified_recipe(graph_payload, result)
        except Exception as exc:
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=500)
        return JSONResponse(
            {
                "status": "verified" if result.get("status") == "verified" else "failed",
                "graph_id": result.get("graph_id"),
                "bundle_path": str(bundle),
                "execution_result": result,
                "execution_id": execution_record.get("execution_id"),
                "verified_recipe": verified_record,
            }
        )

    def prepare_graph_production_execution(
        request: Request,
        body: dict[str, Any],
        graph_id: str,
    ) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        bundle_path = str(body.get("bundle_path") or "").strip()
        context = _request_context(request, body)
        try:
            execution_location = _execution_location_from_body(body)
        except ValueError as exc:
            return None, JSONResponse({"error": "unsupported execution location", "message": str(exc)}, status_code=400)
        run_gate = execution_location_gate(execution_location, "execute")
        if not run_gate.allowed:
            return None, JSONResponse(
                {
                    "status": "blocked",
                    "graph_id": graph_id,
                    "bundle_path": bundle_path or None,
                    "execution_location": execution_location.as_dict(),
                    "execution_dispatch": execution_dispatch_for_location(execution_location),
                    "execution_run_gate": run_gate.as_dict(),
                    "run_blocker": run_gate.run_blocker,
                },
                status_code=400,
            )
        if not graph_id:
            return None, JSONResponse({"error": "graph_id is required"}, status_code=400)
        graph_payload = graph_tools.get_graph(graph_id)
        if isinstance(graph_payload, dict) and is_nfcore_pipeline_graph(graph_payload):
            env_allows_nfcore = os.environ.get("MORPHIC_RUN_NFCORE_EXECUTION") == "1"
            request_allows_nfcore = body.get("allow_nfcore_execution") is True
            if not (env_allows_nfcore and request_allows_nfcore):
                return None, JSONResponse(
                    {
                        "schema": "morphic.nfcore_execution_opt_in_gate/v0",
                        "status": "blocked",
                        "graph_id": graph_id,
                        "run_blocker": (
                            "nf-core production execution is opt-in. Set MORPHIC_RUN_NFCORE_EXECUTION=1 "
                            "on the Workbench server and pass allow_nfcore_execution=true after user review."
                        ),
                        "required_next_step": {
                            "environment": "MORPHIC_RUN_NFCORE_EXECUTION=1",
                            "body": {"allow_nfcore_execution": True},
                        },
                    },
                    status_code=403,
                )
        if not bundle_path:
            return None, JSONResponse({"error": "bundle_path is required"}, status_code=400)

        bundle = Path(bundle_path).expanduser()
        try:
            bundle = bundle.resolve()
        except OSError:
            bundle = bundle.absolute()
        bundle_record = store.get_bundle_by_path(bundle)
        if bundle_record is None:
            return None, JSONResponse(
                {
                    "status": "blocked",
                    "run_blocker": "Bundle path is not registered as a generated workbench bundle.",
                    "bundle_path": str(bundle),
                },
                status_code=400,
            )
        if str(bundle_record.get("graph_id") or "") != graph_id:
            return None, JSONResponse(
                {
                    "status": "blocked",
                    "run_blocker": "Bundle graph does not match requested graph.",
                    "graph_id": graph_id,
                    "bundle_graph_id": bundle_record.get("graph_id"),
                },
                status_code=400,
            )
        owner_allowed, owner_blocker = _bundle_owner_allows_request(bundle_record, context)
        if not owner_allowed:
            return None, JSONResponse(
                {
                    "status": "blocked",
                    "graph_id": graph_id,
                    "bundle_path": str(bundle),
                    "run_blocker": owner_blocker,
                    "request_context": context,
                },
                status_code=403,
            )
        run_sh = bundle / "run.sh"
        if not run_sh.is_file():
            return None, JSONResponse(
                {"status": "blocked", "run_blocker": "Generated bundle does not contain run.sh.", "bundle_path": str(bundle)},
                status_code=400,
            )

        bundle_params: dict[str, Any] = {}
        params_path = bundle / "params.review.json"
        if params_path.is_file():
            try:
                loaded = json.loads(params_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("params"), dict):
                    bundle_params = loaded["params"]
            except json.JSONDecodeError:
                return None, JSONResponse(
                    {"status": "blocked", "run_blocker": "params.review.json is not valid JSON.", "bundle_path": str(bundle)},
                    status_code=400,
                )
        request_params = body.get("params") if isinstance(body.get("params"), dict) else {}
        params = {**bundle_params, **request_params}
        try:
            path_bindings_manifest = load_path_bindings(bundle)
        except (OSError, json.JSONDecodeError) as exc:
            return None, JSONResponse(
                {"status": "blocked", "run_blocker": f"path_bindings.json is not valid JSON: {exc}", "bundle_path": str(bundle)},
                status_code=400,
            )
        path_bindings_metadata = path_bindings_response(bundle)
        container_metadata = container_manifest_response(bundle)
        params = resolve_params_for_location(
            params,
            path_bindings_manifest,
            bundle_dir=bundle,
            execution_location=execution_location.location_id,
        )

        try:
            if graph_id.startswith("star_"):
                _, preflight_result = build_star_mvp_preflight_result(
                    graph_id,
                    "",
                    params,
                    body.get("execution_location") if "execution_location" in body else body.get("execution_profile"),
                )
            else:
                preflight_response = bundle_tools.preflight_bundle(
                    graph_id,
                    params,
                    execution_location=execution_location.as_dict(),
                    bundle_path=bundle,
                )
                preflight_result = annotate_preflight_for_location(preflight_response.payload, execution_location)
        except Exception as exc:
            return None, JSONResponse({"status": "blocked", "run_blocker": str(exc), "bundle_path": str(bundle)}, status_code=400)
        preflight_passed = preflight_result.get("status") == "preflight_passed" or preflight_result.get("executable_ready") is True
        if not preflight_passed:
            return None, JSONResponse(
                {
                    "status": "blocked",
                    "graph_id": graph_id,
                    "bundle_path": str(bundle),
                    "preflight": preflight_result,
                    "run_blocker": preflight_result.get("run_blocker") or "Preflight did not pass.",
                },
                status_code=403,
            )
        run_id = str(body.get("run_id") or "").strip()
        if run_id:
            run_payload, run_status = service.get_run(run_id)
            run = run_payload.get("run") if isinstance(run_payload.get("run"), dict) else None
            if run_status != 200 or not run:
                return None, JSONResponse(
                    {"status": "blocked", "run_id": run_id, "run_blocker": "run_id was not found."},
                    status_code=400,
                )
            if str(run.get("graph_id") or "") != graph_id:
                return None, JSONResponse(
                    {
                        "status": "blocked",
                        "run_id": run_id,
                        "run_blocker": f"run_id `{run_id}` belongs to graph `{run.get('graph_id')}`, not `{graph_id}`.",
                    },
                    status_code=400,
                )
            updated_run = store.update_workbench_run(
                run_id,
                {
                    "status": "execution_running",
                    "current_step": "execute",
                    "params": params,
                    "execution_location": execution_location.as_dict(),
                    "bundle": {
                        "bundle_id": bundle_record.get("bundle_id"),
                        "bundle_path": str(bundle),
                    },
                    "preflight": {
                        "status": preflight_result.get("status"),
                        "run_blocker": preflight_result.get("run_blocker"),
                        "executable_ready": preflight_result.get("executable_ready"),
                    },
                },
                event="execution_started",
            )
        else:
            updated_run = store.create_workbench_run(
                graph_id,
                params,
                execution_location=execution_location.as_dict(),
                request_context=context,
                status="execution_running",
                current_step="execute",
            )
            run_id = str(updated_run["run_id"])
        return {
            "graph_id": graph_id,
            "run_id": run_id,
            "run": updated_run,
            "bundle": bundle,
            "run_sh": run_sh,
            "params": params,
            "context": context,
            "preflight_result": preflight_result,
            "execution_location": execution_location,
            "execution_dispatch": execution_dispatch_for_location(execution_location),
            "execution_run_gate": run_gate.as_dict(),
            "path_bindings_metadata": {**path_bindings_metadata, **container_metadata},
        }, None

    def finalize_graph_production_execution(
        prepared: dict[str, Any],
        *,
        returncode: int | None,
        stdout: str,
        stderr: str,
        before_artifacts: dict[str, dict[str, int]],
        timeout_seconds: int,
        timed_out: bool = False,
    ) -> dict[str, Any]:
        graph_id = str(prepared["graph_id"])
        bundle = Path(prepared["bundle"])
        params = prepared["params"] if isinstance(prepared.get("params"), dict) else {}
        context = prepared["context"] if isinstance(prepared.get("context"), dict) else {}
        preflight_result = prepared["preflight_result"] if isinstance(prepared.get("preflight_result"), dict) else {}
        execution_location = prepared.get("execution_location")
        execution_location_payload = execution_location.as_dict() if hasattr(execution_location, "as_dict") else {}
        execution_dispatch = prepared.get("execution_dispatch") if isinstance(prepared.get("execution_dispatch"), dict) else {}
        execution_run_gate = prepared.get("execution_run_gate") if isinstance(prepared.get("execution_run_gate"), dict) else {}
        path_bindings_metadata = prepared.get("path_bindings_metadata") if isinstance(prepared.get("path_bindings_metadata"), dict) else {}
        result_path = bundle / "execution_result.json"
        stdout_tail = _tail_text(stdout or "")
        stderr_tail = _tail_text(stderr or "")
        execution_result: dict[str, Any]
        if timed_out:
            execution_result = {
                "schema": "morphic.local_execution_result/v0",
                "status": "failed",
                "failure_kind": "timeout",
                "graph_id": graph_id,
                "bundle_path": str(bundle),
                "returncode": None,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "timeout_seconds": timeout_seconds,
            }
        else:
            loaded_result = _load_execution_result_file(result_path)
            if returncode == 0:
                execution_result = {
                    "schema": "morphic.local_execution_result/v0",
                    "status": loaded_result.get("status") or "completed",
                    "graph_id": loaded_result.get("graph_id") or graph_id,
                    "bundle_path": str(bundle),
                    **loaded_result,
                    "returncode": returncode,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                }
            else:
                execution_result = {
                    "schema": "morphic.local_execution_result/v0",
                    "graph_id": loaded_result.get("graph_id") or graph_id,
                    "bundle_path": str(bundle),
                    **loaded_result,
                    "status": "failed",
                    "returncode": returncode,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                }
        artifact_manifest = _build_artifact_manifest(bundle, params, before=before_artifacts)
        execution_result["artifact_manifest"] = artifact_manifest
        execution_result["request_context"] = context
        execution_result["execution_location"] = execution_location_payload
        execution_result["execution_dispatch"] = execution_dispatch
        execution_result.update(path_bindings_metadata)
        execution_record = store.record_execution(graph_id, execution_result, params=params)
        execution_id = str(execution_record.get("execution_id") or "")
        linked_manifest = _artifact_manifest_with_links(execution_id, artifact_manifest)
        verified_record = None
        graph_path = bundle / "workflow_graph.json"
        if execution_result.get("status") == "verified" and execution_result.get("verified_recipe") is True and graph_path.is_file():
            try:
                verified_record = graph_index.store_verified_recipe(json.loads(graph_path.read_text(encoding="utf-8")), execution_result)
            except Exception:
                verified_record = None
        response_execution_result = {**execution_result, "artifact_manifest": linked_manifest}
        payload = {
            "status": _top_execution_status(execution_result),
            "graph_id": graph_id,
            "run_id": prepared.get("run_id"),
            "bundle_path": str(bundle),
            "request_context": context,
            "preflight": preflight_result,
            "execution_location": execution_location_payload,
            "execution_dispatch": execution_dispatch,
            "execution_run_gate": execution_run_gate,
            **path_bindings_metadata,
            "execution_result": response_execution_result,
            "artifact_manifest": linked_manifest,
            "execution_id": execution_id,
            "verified_recipe": verified_record,
        }
        run_id = str(prepared.get("run_id") or "").strip()
        if run_id:
            updated_run = store.update_workbench_run(
                run_id,
                {
                    "status": payload["status"],
                    "current_step": "execution",
                    "execution": {
                        "execution_id": execution_id,
                        "status": payload["status"],
                        "returncode": execution_result.get("returncode"),
                        "bundle_path": str(bundle),
                    },
                    "artifact_manifest": linked_manifest,
                },
                event="execution_completed",
                event_payload={"execution_id": execution_id, "execution_status": payload["status"]},
            )
            payload["run"] = updated_run
        return payload

    async def graph_execute_production(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "").strip()
        prepared, error_response = prepare_graph_production_execution(request, body, graph_id)
        if error_response is not None:
            return error_response
        assert prepared is not None

        timeout = int(body.get("timeout") or 120)
        bundle = Path(prepared["bundle"])
        run_sh = Path(prepared["run_sh"])
        before_artifacts = _snapshot_artifact_files(bundle, prepared["params"])
        try:
            location_kind = getattr(prepared["execution_location"], "kind", "")
            if location_kind == "remote_ssh":
                remote_result = run_remote_ssh_bundle(bundle=bundle, location=prepared["execution_location"], timeout=timeout)
                proc_returncode = remote_result.get("returncode")
                stdout = str(remote_result.get("stdout") or "")
                stderr = str(remote_result.get("stderr") or "")
            elif location_kind == "scheduler_remote_ssh":
                scheduler_result = run_scheduler_remote_ssh_bundle(bundle=bundle, location=prepared["execution_location"], timeout=timeout)
                proc_returncode = scheduler_result.get("returncode")
                stdout = str(scheduler_result.get("stdout") or "")
                stderr = str(scheduler_result.get("stderr") or "")
            elif location_kind == "scheduler_temporal":
                scheduler_result = run_scheduler_bundle(bundle=bundle, location=prepared["execution_location"], timeout=timeout)
                proc_returncode = scheduler_result.get("returncode")
                stdout = str(scheduler_result.get("stdout") or "")
                stderr = str(scheduler_result.get("stderr") or "")
            else:
                proc = subprocess.run(["bash", str(run_sh)], cwd=str(bundle), capture_output=True, text=True, timeout=timeout)
                proc_returncode = proc.returncode
                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
            payload = finalize_graph_production_execution(
                prepared,
                returncode=proc_returncode,
                stdout=stdout,
                stderr=stderr,
                before_artifacts=before_artifacts,
                timeout_seconds=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            payload = finalize_graph_production_execution(
                prepared,
                returncode=None,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                before_artifacts=before_artifacts,
                timeout_seconds=timeout,
                timed_out=True,
            )
        except Exception as exc:
            return JSONResponse({"status": "failed", "message": str(exc), "bundle_path": str(bundle)}, status_code=500)
        return JSONResponse(payload)

    async def graph_execute_production_stream(request: Request) -> Response:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(request.path_params.get("graph_id") or "").strip()
        prepared, error_response = prepare_graph_production_execution(request, body, graph_id)
        if error_response is not None:
            return error_response
        assert prepared is not None
        timeout = int(body.get("timeout") or 120)
        bundle = Path(prepared["bundle"])
        run_sh = Path(prepared["run_sh"])
        before_artifacts = _snapshot_artifact_files(bundle, prepared["params"])

        def ndjson(payload: dict[str, Any]) -> str:
            return json.dumps(payload, separators=(",", ":")) + "\n"

        def event_stream():
            stdout_parts: list[str] = []
            stderr_parts: list[str] = []
            timed_out = False
            proc: subprocess.Popen[str] | None = None
            location_kind = getattr(prepared["execution_location"], "kind", "")
            yield ndjson({"event": "log", "stream": "system", "text": f"Starting production run in {bundle}\n"})
            try:
                if location_kind == "remote_ssh":
                    yield ndjson({"event": "log", "stream": "system", "text": "Copying bundle to remote SSH destination and running container launcher.\n"})
                    remote_result = run_remote_ssh_bundle(bundle=bundle, location=prepared["execution_location"], timeout=timeout)
                    if remote_result.get("stdout"):
                        stdout_parts.append(str(remote_result.get("stdout") or ""))
                        yield ndjson({"event": "log", "stream": "stdout", "text": str(remote_result.get("stdout") or "")})
                    if remote_result.get("stderr"):
                        stderr_parts.append(str(remote_result.get("stderr") or ""))
                        yield ndjson({"event": "log", "stream": "stderr", "text": str(remote_result.get("stderr") or "")})
                    payload = finalize_graph_production_execution(
                        prepared,
                        returncode=remote_result.get("returncode"),
                        stdout="".join(stdout_parts),
                        stderr="".join(stderr_parts),
                        before_artifacts=before_artifacts,
                        timeout_seconds=timeout,
                    )
                    yield ndjson({"event": "result", "payload": payload})
                    return
                if location_kind == "scheduler_remote_ssh":
                    yield ndjson({"event": "log", "stream": "system", "text": "Submitting bundle to the Temporal scheduler SSH Docker workflow.\n"})
                    scheduler_result = run_scheduler_remote_ssh_bundle(bundle=bundle, location=prepared["execution_location"], timeout=timeout)
                    if scheduler_result.get("stdout"):
                        stdout_parts.append(str(scheduler_result.get("stdout") or ""))
                        yield ndjson({"event": "log", "stream": "stdout", "text": str(scheduler_result.get("stdout") or "")})
                    if scheduler_result.get("stderr"):
                        stderr_parts.append(str(scheduler_result.get("stderr") or ""))
                        yield ndjson({"event": "log", "stream": "stderr", "text": str(scheduler_result.get("stderr") or "")})
                    payload = finalize_graph_production_execution(
                        prepared,
                        returncode=scheduler_result.get("returncode"),
                        stdout="".join(stdout_parts),
                        stderr="".join(stderr_parts),
                        before_artifacts=before_artifacts,
                        timeout_seconds=timeout,
                    )
                    yield ndjson({"event": "result", "payload": payload})
                    return
                if location_kind == "scheduler_temporal":
                    yield ndjson({"event": "log", "stream": "system", "text": "Submitting bundle to the local Temporal scheduler.\n"})
                    scheduler_result = run_scheduler_bundle(bundle=bundle, location=prepared["execution_location"], timeout=timeout)
                    if scheduler_result.get("stdout"):
                        stdout_parts.append(str(scheduler_result.get("stdout") or ""))
                        yield ndjson({"event": "log", "stream": "stdout", "text": str(scheduler_result.get("stdout") or "")})
                    if scheduler_result.get("stderr"):
                        stderr_parts.append(str(scheduler_result.get("stderr") or ""))
                        yield ndjson({"event": "log", "stream": "stderr", "text": str(scheduler_result.get("stderr") or "")})
                    payload = finalize_graph_production_execution(
                        prepared,
                        returncode=scheduler_result.get("returncode"),
                        stdout="".join(stdout_parts),
                        stderr="".join(stderr_parts),
                        before_artifacts=before_artifacts,
                        timeout_seconds=timeout,
                    )
                    yield ndjson({"event": "result", "payload": payload})
                    return
                proc = subprocess.Popen(
                    ["bash", str(run_sh)],
                    cwd=str(bundle),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                selector = selectors.DefaultSelector()
                if proc.stdout is not None:
                    selector.register(proc.stdout, selectors.EVENT_READ, data="stdout")
                if proc.stderr is not None:
                    selector.register(proc.stderr, selectors.EVENT_READ, data="stderr")
                deadline = time.monotonic() + timeout
                while selector.get_map():
                    if time.monotonic() > deadline:
                        timed_out = True
                        proc.kill()
                    events = selector.select(timeout=0.2)
                    if not events and proc.poll() is not None:
                        for key in list(selector.get_map().values()):
                            try:
                                selector.unregister(key.fileobj)
                            except Exception:
                                pass
                        break
                    for key, _ in events:
                        stream_name = str(key.data)
                        line = key.fileobj.readline()
                        if line:
                            if stream_name == "stderr":
                                stderr_parts.append(line)
                            else:
                                stdout_parts.append(line)
                            yield ndjson({"event": "log", "stream": stream_name, "text": line})
                        else:
                            try:
                                selector.unregister(key.fileobj)
                            except Exception:
                                pass
                returncode = proc.wait(timeout=1)
                payload = finalize_graph_production_execution(
                    prepared,
                    returncode=None if timed_out else returncode,
                    stdout="".join(stdout_parts),
                    stderr="".join(stderr_parts),
                    before_artifacts=before_artifacts,
                    timeout_seconds=timeout,
                    timed_out=timed_out,
                )
                yield ndjson({"event": "result", "payload": payload})
            except Exception as exc:
                if proc is not None and proc.poll() is None:
                    proc.kill()
                yield ndjson(
                    {
                        "event": "result",
                        "payload": {"status": "failed", "message": str(exc), "bundle_path": str(bundle)},
                    }
                )

        return StreamingResponse(event_stream(), media_type="application/x-ndjson")

    async def execution_artifact(request: Request) -> Response:
        execution_id = str(request.path_params.get("execution_id") or "")
        artifact_id = str(request.path_params.get("artifact_id") or "")
        execution = store.get_execution(execution_id)
        if execution is None:
            return JSONResponse({"error": "execution not found"}, status_code=404)
        result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
        context = _request_context(request, {})
        owner_allowed, owner_blocker = _execution_owner_allows_request(result, context)
        if not owner_allowed:
            return JSONResponse({"error": owner_blocker}, status_code=403)
        manifest = result.get("artifact_manifest") if isinstance(result.get("artifact_manifest"), dict) else {}
        files = [item for item in manifest.get("files") or [] if isinstance(item, dict)]
        match = next((item for item in files if str(item.get("artifact_id") or "") == artifact_id), None)
        if match is None:
            return JSONResponse({"error": "artifact not found"}, status_code=404)
        path = Path(str(match.get("path") or "")).expanduser()
        try:
            path = path.resolve()
        except OSError:
            path = path.absolute()
        if _artifact_id_for_path(path) != artifact_id:
            return JSONResponse({"error": "artifact path/id mismatch"}, status_code=403)
        if not path.is_file():
            return JSONResponse({"error": "artifact file is missing"}, status_code=404)
        download = str(request.query_params.get("download") or "").lower() in {"1", "true", "yes"}
        media_type = str(match.get("media_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        disposition = "attachment" if download else "inline"
        filename = path.name.replace('"', "")
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        )

    async def star_workflows(_: Request) -> JSONResponse:
        return JSONResponse(list_star_workflows())

    async def star_helper_scripts(request: Request) -> JSONResponse:
        workflow_id = str(request.query_params.get("workflow_id") or "star_bulk_pe_batch")
        payload = load_star_helper_scripts(workflow_id)
        return JSONResponse(payload, status_code=404 if payload.get("error") else 200)

    async def star_helper_bundle(request: Request) -> Response:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        workflow_id = str(body.get("workflow_id") or "star_bulk_pe_batch")
        scripts = body.get("scripts")
        if not isinstance(scripts, list):
            loaded = load_star_helper_scripts(workflow_id)
            if loaded.get("error"):
                return JSONResponse(loaded, status_code=404)
            scripts = loaded.get("scripts") or []
        zip_bytes = build_helper_bundle_zip(workflow_id, [script for script in scripts if isinstance(script, dict)])
        return Response(
            zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{helper_bundle_filename(workflow_id)}"'},
        )

    async def star_render(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        workflow_id = str(body.get("workflow_id") or "star_bulk_pe_batch")
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        check_paths = bool(body.get("check_paths", False))
        result = render_star_workflow(workflow_id, params, check_paths=check_paths)
        return JSONResponse(result, status_code=400 if not (result.get("validation") or {}).get("valid", False) and result.get("render") is None else 200)

    async def compose_modules(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        goal = str(body.get("goal") or body.get("message") or "").strip()
        if not goal:
            return JSONResponse({"error": "goal is required"}, status_code=400)
        signature = _composition_problem_signature(goal, body)
        draft = graph_tools.draft_graph(goal, include_launchpad=bool(body.get("include_launchpad", False)))
        candidate_graphs = []
        workflow_graph = None
        if draft.status == "graph_draft":
            workflow_graph = draft.payload.get("workflow_graph")
            candidate_graphs = [workflow_graph]
        else:
            candidate_response = graph_tools.find_candidate_graphs(signature)
            candidate_graphs = candidate_response.payload.get("candidate_graphs") or []
            workflow_graph = candidate_graphs[0] if candidate_graphs else None
        params_schema = workflow_graph.get("params_schema") if isinstance(workflow_graph, dict) else {}
        params_json = None
        if isinstance(params_schema, dict):
            params_json = {
                "graph_id": workflow_graph.get("graph_id") if isinstance(workflow_graph, dict) else None,
                "params": {
                    str(field.get("name")): field.get("default")
                    for field in params_schema.get("fields") or []
                    if isinstance(field, dict) and field.get("name") and field.get("default") is not None
                },
            }
        return JSONResponse(
            {
                "status": "composition",
                "suite": _workflow_graph_suite(workflow_graph, catalog),
                "goal": goal,
                "problem_signature": signature,
                "workflow_graph": workflow_graph,
                "candidate_graphs": candidate_graphs,
                "params_json": params_json,
                "composition_input_status": "drafted_skeleton" if workflow_graph else "needs_human_intervention",
                "missing_required_inputs": (params_schema or {}).get("required") if isinstance(params_schema, dict) else [],
                "assistant_message": (
                    "I found a candidate graph and drafted a reviewable parameter skeleton. "
                    "Approve or edit the parameters before asking for a recipe draft."
                    if workflow_graph
                    else "I could not find a local graph that composes this request. The agent should explain the gap and may fall back to broader search."
                ),
                "composition": {
                    "source_workflow_id": body.get("workflow_id") or "star_bulk_pe_batch",
                    "target_workflow_ids": body.get("target_workflow_ids") or [],
                    "confidence": "review-only composition plan; no runnable script is generated here",
                },
                "headless": {"command": None, "script": None, "script_filename": None},
                "run_blocker": "Approve parameters, then generate a bundle through the graph render/materialize endpoint.",
            }
        )

    async def compose_recipe_draft(request: Request) -> JSONResponse:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        graph_id = str(body.get("graph_id") or body.get("composition_graph_id") or "").strip()
        if not graph_id and body.get("profile_id"):
            graph_id = "bulk_pe_deseq2_v0"
        if not graph_id:
            return JSONResponse(
                {
                    "status": "error",
                    "detail": "graph_id or composition_graph_id is required to draft a composed recipe",
                    "headless": {"command": None, "script": None, "script_filename": None},
                },
                status_code=400,
            )
        graph = graph_tools.get_graph(graph_id)
        if not graph:
            return JSONResponse({"status": "not_found", "graph_id": graph_id}, status_code=404)
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        validation = bundle_tools.validate_parameters(graph_id, params)
        return JSONResponse(
            {
                "status": "composition_recipe_draft",
                "suite": _workflow_graph_suite(graph, catalog),
                "graph_id": graph_id,
                "recipe_draft": {
                    "schema": "morphic.composed_recipe_draft/v0",
                    "graph_id": graph_id,
                    "workflow_graph": graph,
                    "params": params,
                    "parameter_validation": validation.payload,
                    "missing_contracts": graph_index.find_missing_contracts(graph),
                },
                "assistant_message": (
                    "Built a composed recipe draft from the approved inputs. "
                    "This endpoint intentionally does not generate a runnable script; use graph render/materialize after review."
                ),
                "run_blocker": "Recipe draft exists, but local execution requires rendering/materializing a bundle from the approved graph.",
                "headless": {"command": None, "script": None, "script_filename": None},
            }
        )

    routes = [
        Route("/", index, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
        Route("/healthz", health, methods=["GET"]),
        Route("/api/model/status", model_status, methods=["GET"]),
        Route("/api/session", session_info, methods=["GET"]),
        Route("/api/conversations", conversations_collection, methods=["GET", "POST"]),
        Route("/api/conversations/{conversation_id}/fork", conversation_fork, methods=["POST"]),
        Route("/api/conversations/{conversation_id}", conversation_item, methods=["GET", "PATCH"]),
        Route("/api/files/browse", file_browser, methods=["GET"]),
        Route("/api/suites", suites, methods=["GET"]),
        Route("/api/suites/{suite_id}/recipes", suite_recipes, methods=["GET"]),
        Route("/v1/agent/chat", agent_chat, methods=["POST"]),
        Route("/api/chat", agent_chat, methods=["POST"]),
        Route("/api/threads/{thread_id}/turns", thread_turns, methods=["GET"]),
        Route("/api/execution/locations", execution_locations, methods=["GET"]),
        Route("/api/runs", runs_collection, methods=["GET", "POST"]),
        Route("/api/runs/{run_id}/validations", run_attach_validation, methods=["POST"]),
        Route("/api/runs/{run_id}", run_get, methods=["GET"]),
        Route("/api/modules", list_modules, methods=["GET"]),
        Route("/api/modules/{module_id}", get_module, methods=["GET"]),
        Route("/api/nfcore/harvest", nfcore_harvest, methods=["POST"]),
        Route("/api/nfcore/decompose", nfcore_decompose, methods=["POST"]),
        Route("/api/nfcore/register", nfcore_register, methods=["POST"]),
        Route("/api/nfcore/pipelines", nfcore_pipelines, methods=["GET"]),
        Route("/api/nfcore/validation-matrix", nfcore_validation_matrix, methods=["GET"]),
        Route("/api/nfcore/pipelines/{identifier}", nfcore_recipe, methods=["GET"]),
        Route("/api/nfcore/validations", nfcore_validations, methods=["GET"]),
        Route("/api/nfcore/validations/reference", nfcore_reference_validation, methods=["POST"]),
        Route("/api/graphs/draft", graph_draft, methods=["POST"]),
        Route("/api/graphs/projection/rebuild", graph_projection_rebuild, methods=["POST"]),
        Route("/api/graphs/projection/{projection_version}", graph_projection_status, methods=["GET"]),
        Route("/api/graphs/verified/search", graph_verified_search, methods=["POST"]),
        Route("/api/graphs/search", graph_search, methods=["POST"]),
        Route("/api/graphs/{graph_id}", graph_get, methods=["GET"]),
        Route("/api/graphs/{graph_id}/verified-recipes", graph_store_verified, methods=["POST"]),
        Route("/api/graphs/{graph_id}/params/schema", graph_params_schema, methods=["GET"]),
        Route("/api/graphs/{graph_id}/params/validate", graph_params_validate, methods=["POST"]),
        Route("/api/graphs/{graph_id}/execution-review", graph_execution_review, methods=["POST"]),
        Route("/api/graphs/{graph_id}/render", graph_render, methods=["POST"]),
        Route("/api/graphs/{graph_id}/preflight", graph_preflight, methods=["POST"]),
        Route("/api/graphs/{graph_id}/execution-diagnostic", graph_execution_diagnostic, methods=["POST"]),
        Route("/api/graphs/{graph_id}/bundle.zip", graph_bundle_zip, methods=["GET"]),
        Route("/api/graphs/{graph_id}/execute-production/stream", graph_execute_production_stream, methods=["POST"]),
        Route("/api/graphs/{graph_id}/execute-production", graph_execute_production, methods=["POST"]),
        Route("/api/executions/{execution_id}/artifacts/{artifact_id}", execution_artifact, methods=["GET"]),
        Route("/api/star-mvp/plan", star_mvp_plan, methods=["POST"]),
        Route("/api/star-mvp/preflight", star_mvp_preflight, methods=["POST"]),
        Route("/api/star-mvp/materialize", star_mvp_materialize, methods=["POST"]),
        Route("/api/star-mvp/execute", star_mvp_execute, methods=["POST"]),
        Route("/api/suites/star/workflows", star_workflows, methods=["GET"]),
        Route("/api/suites/star/helper-scripts", star_helper_scripts, methods=["GET"]),
        Route("/api/suites/star/helper-scripts/bundle", star_helper_bundle, methods=["POST"]),
        Route("/api/suites/star/render", star_render, methods=["POST"]),
        Route("/api/compose", compose_modules, methods=["POST"]),
        Route("/api/compose/draft", compose_recipe_draft, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.state.workbench_service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    return app


app = create_app()
