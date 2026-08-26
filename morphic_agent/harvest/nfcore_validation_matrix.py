"""Default-safe nf-core recipe validation matrix."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from morphic_agent.bundle.nfcore_pipeline import materialize_nfcore_pipeline_bundle, preflight_nfcore_bundle
from morphic_agent.registry.store import AgentStore

NFCORE_VALIDATION_MATRIX_SCHEMA = "morphic.nfcore_validation_matrix/v0"


def build_nfcore_validation_matrix(
    store: AgentStore,
    *,
    out_root: str | Path | None = None,
    execution_location: str = "server",
    render: bool = True,
    preflight: bool = True,
    limit: int = 100,
) -> dict[str, Any]:
    """Report indexed/render/preflight/reference-validation status for harvested nf-core recipes."""

    results = store.search_graphs(filters={"suite": "nf-core"}, limit=limit)
    rows: list[dict[str, Any]] = []
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if out_root is None and render:
        temp_dir = tempfile.TemporaryDirectory(prefix="morphic-nfcore-matrix-")
        root = Path(temp_dir.name)
        bundles_are_ephemeral = True
    else:
        root = Path(out_root).expanduser() if out_root is not None else None
        bundles_are_ephemeral = False
    try:
        for item in results.get("results") or []:
            graph = item.get("workflow_graph") if isinstance(item.get("workflow_graph"), dict) else {}
            rows.append(
                _matrix_row(
                    graph,
                    search_result=item,
                    out_root=root,
                    execution_location=execution_location,
                    render=render,
                    preflight=preflight,
                    bundles_are_ephemeral=bundles_are_ephemeral,
                )
            )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("overall_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "schema": NFCORE_VALIDATION_MATRIX_SCHEMA,
        "status": "ok",
        "recipe_count": len(rows),
        "status_counts": status_counts,
        "execution_location": execution_location,
        "render_attempted": bool(render),
        "preflight_attempted": bool(preflight),
        "bundles_are_ephemeral": bundles_are_ephemeral,
        "recipes": rows,
    }


def _matrix_row(
    graph: dict[str, Any],
    *,
    search_result: dict[str, Any],
    out_root: Path | None,
    execution_location: str,
    render: bool,
    preflight: bool,
    bundles_are_ephemeral: bool,
) -> dict[str, Any]:
    graph_id = str(graph.get("graph_id") or search_result.get("graph_id") or "")
    params = _default_params(graph)
    schema_valid = _schema_valid(graph)
    latest_validation = graph.get("latest_validation") if isinstance(graph.get("latest_validation"), dict) else search_result.get("latest_validation")
    reference_validated = bool(latest_validation and str(latest_validation.get("status") or "").lower() == "passed")
    row: dict[str, Any] = {
        "schema": "morphic.nfcore_validation_matrix_row/v0",
        "graph_id": graph_id,
        "title": graph.get("title") or search_result.get("title"),
        "indexed": True,
        "schema_valid": schema_valid,
        "required_param_count": len((graph.get("params_schema") or {}).get("required") or []),
        "default_param_count": len(params),
        "path_binding_candidate_count": len(graph.get("path_binding_candidates") or []),
        "materialization_status": graph.get("materialization_status") or search_result.get("materialization_status"),
        "reference_validated": reference_validated,
        "latest_validation": latest_validation,
    }
    bundle_path = None
    if render:
        try:
            if out_root is None:
                raise ValueError("out_root is required when render is enabled")
            bundle_path = materialize_nfcore_pipeline_bundle(
                graph,
                out_root,
                params=params,
                execution_location=execution_location,
            )
            row["render_status"] = "rendered"
            if not bundles_are_ephemeral:
                row["bundle_path"] = str(bundle_path)
        except Exception as exc:
            row["render_status"] = "blocked"
            row["render_blocker"] = str(exc)
    else:
        row["render_status"] = "not_run"

    if preflight:
        if bundle_path is None and render:
            row["preflight_status"] = "blocked"
            row["preflight_blocker"] = row.get("render_blocker") or "bundle was not rendered"
        else:
            try:
                preflight_result = preflight_nfcore_bundle(
                    graph,
                    params,
                    bundle_dir=bundle_path,
                    execution_location_kind=execution_location,
                )
                row["preflight_status"] = preflight_result["status"]
                row["preflight_blocker"] = preflight_result.get("run_blocker")
                row["preflight_checks"] = preflight_result.get("checks") or []
            except Exception as exc:
                row["preflight_status"] = "blocked"
                row["preflight_blocker"] = str(exc)
    else:
        row["preflight_status"] = "not_run"

    row["overall_status"] = _overall_status(row)
    return row


def _default_params(graph: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    schema = graph.get("params_schema") if isinstance(graph.get("params_schema"), dict) else {}
    for field in schema.get("fields") or []:
        if isinstance(field, dict) and field.get("name") and "default" in field:
            params[str(field["name"])] = field["default"]
    return params


def _schema_valid(graph: dict[str, Any]) -> bool:
    schema = graph.get("params_schema") if isinstance(graph.get("params_schema"), dict) else {}
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    return bool(graph.get("graph_id") and schema.get("fields") is not None and runtime.get("kind") == "nfcore_pipeline")


def _overall_status(row: dict[str, Any]) -> str:
    if row.get("reference_validated"):
        return "reference_validated"
    if row.get("preflight_status") == "preflight_passed":
        return "preflight_passed"
    if row.get("render_status") == "rendered":
        return "rendered"
    if row.get("schema_valid"):
        return "indexed"
    return "blocked"
