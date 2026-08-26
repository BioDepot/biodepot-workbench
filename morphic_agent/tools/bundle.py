"""Bundle render, validation, and preflight tools."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from morphic_front.graph_mvp import RecipeGraph, materialize_star_mvp_bundle

from morphic_agent.bundle.containers import container_manifest_response
from morphic_agent.bundle.path_bindings import (
    load_path_bindings,
    path_bindings_response,
    resolve_params_for_location,
    validate_path_bindings_for_location,
    write_path_bindings,
)
from morphic_agent.bundle.bulk_deg import (
    BULK_DEG_PLOTS_GRAPH_ID,
    MATERIALIZABLE_BULK_DEG_GRAPH_IDS,
    materialize_bulk_deseq_bundle,
    preflight_bulk_deseq_bundle,
    validate_bulk_deseq_params,
)
from morphic_agent.bundle.trimodal_qc import (
    TRIMODAL_QC_GRAPH_ID,
    materialize_trimodal_qc_bundle,
    preflight_trimodal_qc_bundle,
)
from morphic_agent.bundle.nfcore_pipeline import (
    is_nfcore_pipeline_graph,
    materialize_nfcore_pipeline_bundle,
    preflight_nfcore_bundle,
)
from morphic_agent.contracts.envelopes import ToolResponse
from morphic_agent.execution import execution_dispatch_for_location, execution_location_gate, resolve_execution_location
from morphic_agent.execution.scheduler import localize_bundle_manifest_for_scheduler, scheduler_preflight
from morphic_agent.execution.ssh import localize_bundle_manifest, remote_ssh_preflight
from morphic_agent.graph.params import validate_graph_params
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore
from morphic_agent.tools.graph import GraphTools

BULK_DEG_GRAPH_IDS = frozenset({"bulk_pe_deseq2_v0", "bulk_pe_deseq2_plots_v0"})


class BundleTools:
    def __init__(
        self,
        catalog: ModuleCatalog | None = None,
        graph_tools: GraphTools | None = None,
        *,
        store: AgentStore | None = None,
    ) -> None:
        self.catalog = catalog or ModuleCatalog()
        self.graph_tools = graph_tools or GraphTools(self.catalog)
        self.store = store

    def validate_parameters(self, graph_id: str, params: dict[str, Any]) -> ToolResponse:
        graph = self.graph_tools.get_graph(graph_id)
        if not graph:
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="validate_parameters",
                stable_id=f"validate:{graph_id}",
                status="not_found",
                payload={"graph_id": graph_id},
                summary=f"Graph `{graph_id}` was not found.",
                blockers=["graph not found"],
            )
        validation = validate_graph_params(graph, params)
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="validate_parameters",
            stable_id=f"validate:{graph_id}",
            status="valid" if validation["valid"] else "invalid",
            payload={"graph_id": graph_id, **validation},
            summary="Parameters are valid." if validation["valid"] else f"Missing: {', '.join(validation['missing_required_inputs'])}",
            blockers=[f"missing `{name}`" for name in validation["missing_required_inputs"]],
        )

    def render_bundle(
        self,
        graph_id: str,
        params: dict[str, Any] | None = None,
        *,
        out_root: str | Path | None = None,
        request_context: dict[str, Any] | None = None,
        execution_location: Any = None,
    ) -> ToolResponse:
        location = resolve_execution_location(execution_location)
        graph = self.graph_tools.get_graph(graph_id)
        if not graph:
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="render_bundle",
                stable_id=f"render:{graph_id}",
                status="not_found",
                payload={"graph_id": graph_id},
                summary="Graph not found.",
                blockers=["graph not found"],
            )

        params = params or {}
        validation = (
            validate_bulk_deseq_params(graph, params)
            if graph_id in MATERIALIZABLE_BULK_DEG_GRAPH_IDS
            else validate_graph_params(graph, params)
        )
        if not validation["valid"]:
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="render_bundle",
                stable_id=f"render:{graph_id}",
                status="blocked",
                payload={
                    "graph_id": graph_id,
                    "workflow_graph": graph,
                    "run_blocker": "Required parameters are missing; fix params before bundle generation.",
                    "missing_required_inputs": validation["missing_required_inputs"],
                    "headless": {"command": None, "script": None, "script_filename": None},
                    **self._execution_payload(location),
                },
                summary="Cannot materialize bundle until required parameters are provided.",
                blockers=[f"missing `{name}`" for name in validation["missing_required_inputs"]],
            )

        if graph_id == BULK_DEG_PLOTS_GRAPH_ID:
            blocker = graph.get("run_blocker") or "Plot modules cannot be materialized yet."
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="render_bundle",
                stable_id=f"render:{graph_id}",
                status="blocked",
                payload={
                    "graph_id": graph_id,
                    "workflow_graph": graph,
                    "run_blocker": blocker,
                    "headless": {"command": None, "script": None, "script_filename": None},
                    **self._execution_payload(location),
                },
                summary=blocker,
                blockers=[blocker],
            )

        if graph_id in MATERIALIZABLE_BULK_DEG_GRAPH_IDS:
            root = Path(out_root or os.environ.get("MORPHIC_AGENT_BUNDLE_ROOT") or tempfile.mkdtemp(prefix="morphic-agent-bundles-"))
            bundle_path = materialize_bulk_deseq_bundle(
                graph,
                root,
                params=validation["normalized_params"],
                execution_location=location.location_id,
            )
            self._localize_execution_bundle_manifest(bundle_path, location)
            readiness = preflight_bulk_deseq_bundle(
                graph,
                validation["normalized_params"],
                execution_location_kind=location.kind,
                bundle_dir=bundle_path,
            )
            run_sh = bundle_path / "run.sh"
            executable_ready = bool(readiness.get("executable_ready"))
            run_blocker = readiness.get("run_blocker")
            route = readiness.get("execution_route") if isinstance(readiness.get("execution_route"), dict) else {}
            headless_command = None
            if executable_ready:
                if location.kind == "server" and str(route.get("route_id") or "") == "host_r":
                    headless_command = f"bash {run_sh}"
                elif str(route.get("route_id") or "") in {"local_docker", "remote_ssh_docker"} and str(route.get("command") or "").strip():
                    headless_command = str(route["command"])
            if not executable_ready and not run_blocker:
                run_blocker = "Bundle files were materialized for review, but STAR/DESeq2 executables are not ready on this host."
            bundle_record = (
                self.store.record_bundle(
                    graph_id,
                    bundle_path,
                    {
                        "schema": "morphic.generated_bundle_manifest/v0",
                        "graph_id": graph_id,
                        "request_context": request_context or {},
                        "execution_readiness": "executable_ready" if executable_ready else readiness.get("status"),
                        "files": sorted(p.name for p in bundle_path.iterdir()),
                    },
                )
                if self.store is not None
                else {}
            )
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="render_bundle",
                stable_id=f"render:{graph_id}",
                status="materialized",
                payload={
                    "graph_id": graph_id,
                    "bundle_path": str(bundle_path),
                    "bundle_id": bundle_record.get("bundle_id"),
                    "workflow_graph": graph,
                    "execution_readiness": "executable_ready" if executable_ready else readiness.get("status"),
                    "run_blocker": run_blocker,
                    "headless": {
                        "command": headless_command,
                        "script": run_sh.read_text(encoding="utf-8") if executable_ready and headless_command == f"bash {run_sh}" else None,
                        "script_filename": "run.sh" if executable_ready and headless_command == f"bash {run_sh}" else None,
                    },
                    "files": sorted(p.name for p in bundle_path.iterdir()),
                    "preflight": readiness,
                    **self._execution_payload(location, bundle_path=bundle_path),
                },
                summary=(
                    f"Materialized runnable bundle at {bundle_path}"
                    if executable_ready
                    else f"Materialized review bundle at {bundle_path}; execution blocked until preflight is executable_ready."
                ),
                confidence_tier=str(graph.get("confidence_tier") or "curated_profile"),
                blockers=[run_blocker] if run_blocker else [],
            )

        if graph_id == TRIMODAL_QC_GRAPH_ID:
            readiness = preflight_trimodal_qc_bundle(graph, validation["normalized_params"])
            root = Path(out_root or os.environ.get("MORPHIC_AGENT_BUNDLE_ROOT") or tempfile.mkdtemp(prefix="morphic-agent-bundles-"))
            bundle_path = materialize_trimodal_qc_bundle(
                graph,
                root,
                params=validation["normalized_params"],
                execution_location=location.location_id,
            )
            self._localize_execution_bundle_manifest(bundle_path, location)
            run_sh = bundle_path / "run.sh"
            executable_ready = bool(readiness.get("executable_ready"))
            run_blocker = readiness.get("run_blocker")
            bundle_record = (
                self.store.record_bundle(
                    graph_id,
                    bundle_path,
                    {
                        "schema": "morphic.generated_bundle_manifest/v0",
                        "graph_id": graph_id,
                        "request_context": request_context or {},
                        "execution_readiness": "executable_ready" if executable_ready else readiness.get("status"),
                        "files": sorted(p.name for p in bundle_path.iterdir()),
                    },
                )
                if self.store is not None
                else {}
            )
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="render_bundle",
                stable_id=f"render:{graph_id}",
                status="materialized",
                payload={
                    "graph_id": graph_id,
                    "bundle_path": str(bundle_path),
                    "bundle_id": bundle_record.get("bundle_id"),
                    "workflow_graph": graph,
                    "execution_readiness": "executable_ready" if executable_ready else readiness.get("status"),
                    "run_blocker": run_blocker,
                    "headless": {
                        "command": f"bash {run_sh}",
                        "script": run_sh.read_text(encoding="utf-8"),
                        "script_filename": "run.sh",
                    },
                    "files": sorted(p.name for p in bundle_path.iterdir()),
                    "preflight": readiness,
                    **self._execution_payload(location, bundle_path=bundle_path),
                },
                summary=(
                    f"Materialized runnable trimodal QC bundle at {bundle_path}"
                    if executable_ready
                    else f"Materialized trimodal QC review bundle at {bundle_path}; execution may be blocked until preflight passes."
                ),
                confidence_tier=str(graph.get("confidence_tier") or "tested_local_recipe"),
                blockers=[run_blocker] if run_blocker else [],
            )

        if is_nfcore_pipeline_graph(graph):
            root = Path(out_root or os.environ.get("MORPHIC_AGENT_BUNDLE_ROOT") or tempfile.mkdtemp(prefix="morphic-agent-bundles-"))
            bundle_path = materialize_nfcore_pipeline_bundle(
                graph,
                root,
                params=validation["normalized_params"],
                execution_location=location.location_id,
            )
            self._localize_execution_bundle_manifest(bundle_path, location)
            readiness = preflight_nfcore_bundle(
                graph,
                validation["normalized_params"],
                bundle_dir=bundle_path,
                execution_location_kind=location.kind,
            )
            run_sh = bundle_path / "run.sh"
            executable_ready = bool(readiness.get("executable_ready"))
            run_blocker = readiness.get("run_blocker")
            bundle_record = (
                self.store.record_bundle(
                    graph_id,
                    bundle_path,
                    {
                        "schema": "morphic.generated_bundle_manifest/v0",
                        "graph_id": graph_id,
                        "request_context": request_context or {},
                        "execution_readiness": "executable_ready" if executable_ready else readiness.get("status"),
                        "files": sorted(p.name for p in bundle_path.iterdir()),
                    },
                )
                if self.store is not None
                else {}
            )
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="render_bundle",
                stable_id=f"render:{graph_id}",
                status="materialized",
                payload={
                    "graph_id": graph_id,
                    "bundle_path": str(bundle_path),
                    "bundle_id": bundle_record.get("bundle_id"),
                    "workflow_graph": graph,
                    "execution_readiness": "executable_ready" if executable_ready else readiness.get("status"),
                    "run_blocker": run_blocker,
                    "headless": {
                        "command": f"bash {run_sh}" if executable_ready and location.kind == "server" else None,
                        "script": run_sh.read_text(encoding="utf-8") if executable_ready and location.kind == "server" else None,
                        "script_filename": "run.sh" if executable_ready and location.kind == "server" else None,
                    },
                    "files": sorted(p.name for p in bundle_path.iterdir()),
                    "preflight": readiness,
                    **self._execution_payload(location, bundle_path=bundle_path),
                },
                summary=(
                    f"Materialized runnable nf-core bundle at {bundle_path}"
                    if executable_ready
                    else f"Materialized nf-core review bundle at {bundle_path}; execution blocked until preflight passes."
                ),
                confidence_tier=str(graph.get("confidence_tier") or "upstream_declared"),
                blockers=[run_blocker] if run_blocker else [],
            )

        if graph.get("materialization_status") == "graph_draft_only":
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="render_bundle",
                stable_id=f"render:{graph_id}",
                status="blocked",
                payload={
                    "graph_id": graph_id,
                    "workflow_graph": graph,
                    "run_blocker": graph.get("run_blocker"),
                    "headless": {"command": None, "script": None, "script_filename": None},
                    **self._execution_payload(location),
                },
                summary=str(graph.get("run_blocker") or "Runnable graph rendering is not connected yet."),
                blockers=[str(graph.get("run_blocker") or "renderer not connected")],
            )

        recipe_graph = RecipeGraph(
            graph_id=graph["graph_id"],
            title=graph.get("title") or graph_id,
            nodes=graph.get("nodes") or [],
            edges=graph.get("edges") or [],
            inputs=graph.get("inputs") or [],
            outputs=graph.get("outputs") or [],
            capabilities=graph.get("capabilities") or [],
            evidence=graph.get("evidence") or [],
            lifecycle_state=str(graph.get("lifecycle_state") or "candidate"),
            confidence_tier=str(graph.get("confidence_tier") or "source_derived"),
            materialization_status=str(graph.get("materialization_status") or "runnable_smoke_bundle"),
            execution=graph.get("execution") or {},
            projection=graph.get("projection") or {},
        )
        bundle_path = materialize_star_mvp_bundle(recipe_graph, out_root or "/tmp/morphic-agent-bundles", params=params)
        self._localize_execution_bundle_manifest(bundle_path, location)
        bundle_record = (
            self.store.record_bundle(
                graph_id,
                bundle_path,
                {
                    "schema": "morphic.generated_bundle_manifest/v0",
                    "graph_id": graph_id,
                    "request_context": request_context or {},
                    "files": sorted(p.name for p in bundle_path.iterdir()),
                },
            )
            if self.store is not None
            else {}
        )
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="render_bundle",
            stable_id=f"render:{graph_id}",
            status="materialized",
            payload={
                "bundle_path": str(bundle_path),
                "bundle_id": bundle_record.get("bundle_id"),
                "files": sorted(p.name for p in bundle_path.iterdir()),
                **self._execution_payload(location, bundle_path=bundle_path),
            },
            summary=f"Materialized bundle at {bundle_path}",
            confidence_tier=recipe_graph.confidence_tier,
        )

    def preflight_bundle(
        self,
        graph_id: str,
        params: dict[str, Any] | None = None,
        *,
        execution_location: Any = None,
        bundle_path: str | Path | None = None,
    ) -> ToolResponse:
        location = resolve_execution_location(execution_location)
        graph = self.graph_tools.get_graph(graph_id)
        if not graph:
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="preflight_bundle",
                stable_id=f"preflight:{graph_id}",
                status="not_found",
                payload={"graph_id": graph_id},
                summary="Graph not found.",
                blockers=["graph not found"],
            )

        params = params or {}
        bundle = Path(bundle_path).expanduser() if bundle_path else None
        manifest = load_path_bindings(bundle) if bundle is not None else None
        if bundle is not None:
            bundle_params = self._load_bundle_params(bundle)
            params = {**bundle_params, **params}

        validation_result = (
            validate_path_bindings_for_location(manifest, bundle_dir=bundle, execution_location=location.location_id)
            if bundle is not None
            else None
        )
        path_metadata = path_bindings_response(bundle) if bundle is not None else {}

        if is_nfcore_pipeline_graph(graph):
            params_for_nfcore = resolve_params_for_location(params, manifest, bundle_dir=bundle, execution_location=location.location_id) if bundle is not None else params
            result = preflight_nfcore_bundle(
                graph,
                params_for_nfcore,
                bundle_dir=bundle,
                execution_location_kind=location.kind,
            )
            result = self._merge_path_binding_validation(result, validation_result, path_metadata)
            record = self.store.record_preflight(graph_id, params_for_nfcore, result) if self.store is not None else {}
            result = {**result, **record}
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="preflight_bundle",
                stable_id=f"preflight:{graph_id}",
                status=result["status"],
                payload=result,
                summary="Preflight passed." if result["status"] == "preflight_passed" else str(result.get("run_blocker") or "nf-core preflight blocked."),
                blockers=[result["run_blocker"]] if result.get("run_blocker") else [],
            )

        if location.kind == "local":
            result = self._local_preflight_payload(graph_id, bundle, validation_result, path_metadata)
            if graph_id in BULK_DEG_GRAPH_IDS and bundle is not None:
                deg = preflight_bulk_deseq_bundle(
                    graph,
                    params,
                    execution_location_kind=location.kind,
                    bundle_dir=bundle,
                )
                result = self._merge_recipe_preflight(result, deg)
            record = self.store.record_preflight(graph_id, params, result) if self.store is not None else {}
            result = {**result, **record}
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="preflight_bundle",
                stable_id=f"preflight:{graph_id}",
                status=result["status"],
                payload=result,
                summary=str(result.get("run_blocker") or "Caller-managed local execution must run outside the Workbench API."),
                blockers=[result["run_blocker"]] if result.get("run_blocker") else [],
            )

        if location.kind == "remote_ssh":
            result = self._remote_ssh_preflight_payload(graph_id, bundle, manifest, validation_result, path_metadata, location)
            if graph_id in BULK_DEG_GRAPH_IDS and bundle is not None:
                deg = preflight_bulk_deseq_bundle(
                    graph,
                    params,
                    execution_location_kind=location.kind,
                    bundle_dir=bundle,
                )
                result = self._merge_recipe_preflight(result, deg)
            record = self.store.record_preflight(graph_id, params, result) if self.store is not None else {}
            result = {**result, **record}
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="preflight_bundle",
                stable_id=f"preflight:{graph_id}",
                status=result["status"],
                payload=result,
                summary="Remote SSH preflight passed." if result["status"] == "preflight_passed" else str(result.get("run_blocker") or "Remote SSH preflight blocked."),
                blockers=[result["run_blocker"]] if result.get("run_blocker") else [],
            )

        if location.kind in {"scheduler_temporal", "scheduler_remote_ssh"}:
            result = self._scheduler_preflight_payload(graph_id, bundle, manifest, validation_result, path_metadata, location)
            if graph_id in BULK_DEG_GRAPH_IDS and bundle is not None:
                deg = preflight_bulk_deseq_bundle(
                    graph,
                    params,
                    execution_location_kind=location.kind,
                    bundle_dir=bundle,
                )
                result = self._merge_recipe_preflight(result, deg)
            record = self.store.record_preflight(graph_id, params, result) if self.store is not None else {}
            result = {**result, **record}
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="preflight_bundle",
                stable_id=f"preflight:{graph_id}",
                status=result["status"],
                payload=result,
                summary="Scheduler preflight passed." if result["status"] == "preflight_passed" else str(result.get("run_blocker") or "Scheduler preflight blocked."),
                blockers=[result["run_blocker"]] if result.get("run_blocker") else [],
            )

        params = resolve_params_for_location(params, manifest, bundle_dir=bundle, execution_location=location.location_id) if bundle is not None else params
        if graph_id in BULK_DEG_GRAPH_IDS:
            result = preflight_bulk_deseq_bundle(
                graph,
                params,
                execution_location_kind=location.kind,
                bundle_dir=bundle,
            )
            result = self._merge_path_binding_validation(result, validation_result, path_metadata)
            record = self.store.record_preflight(graph_id, params, result) if self.store is not None else {}
            result = {**result, **record}
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="preflight_bundle",
                stable_id=f"preflight:{graph_id}",
                status=result["status"],
                payload=result,
                summary="Preflight passed." if result["status"] == "preflight_passed" else str(result.get("run_blocker") or "Preflight blocked."),
                blockers=[result["run_blocker"]] if result.get("run_blocker") else [],
            )

        if graph_id == TRIMODAL_QC_GRAPH_ID:
            result = preflight_trimodal_qc_bundle(graph, params)
            result = self._merge_path_binding_validation(result, validation_result, path_metadata)
            record = self.store.record_preflight(graph_id, params, result) if self.store is not None else {}
            result = {**result, **record}
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="preflight_bundle",
                stable_id=f"preflight:{graph_id}",
                status=result["status"],
                payload=result,
                summary="Preflight passed." if result["status"] == "preflight_passed" else str(result.get("run_blocker") or "Preflight blocked."),
                blockers=[result["run_blocker"]] if result.get("run_blocker") else [],
            )

        checks: list[dict[str, Any]] = []
        for node in graph.get("nodes") or []:
            module = self.catalog.get_module(str(node.get("module_id") or ""))
            for check in (module or {}).get("preflight") or []:
                checks.append(
                    {
                        "node_id": node.get("id"),
                        "module_id": node.get("module_id"),
                        "check": check,
                        "status": "not_run",
                    }
                )
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="preflight_bundle",
            stable_id=f"preflight:{graph_id}",
            status="blocked",
            payload={
                "graph_id": graph_id,
                "checks": checks,
                "run_blocker": "Preflight checks are declared but not executable until graph materialization/preflight adapters are connected.",
            },
            summary="Preflight declared but blocked until a materialized bundle exists.",
            blockers=["preflight adapter not connected for graph_draft_only graphs"],
        )

    def materialize_draft_bundle(
        self,
        graph_id: str,
        params: dict[str, Any],
        out_root: str | Path,
        *,
        execution_location: Any = None,
    ) -> Path:
        location = resolve_execution_location(execution_location)
        graph = self.graph_tools.get_graph(graph_id)
        if not graph:
            raise ValueError(f"graph not found: {graph_id}")
        if graph_id in MATERIALIZABLE_BULK_DEG_GRAPH_IDS:
            bundle = materialize_bulk_deseq_bundle(graph, out_root, params=params, execution_location=location.location_id)
            self._localize_execution_bundle_manifest(bundle, location)
            return bundle
        if graph_id == TRIMODAL_QC_GRAPH_ID:
            bundle = materialize_trimodal_qc_bundle(graph, out_root, params=params, execution_location=location.location_id)
            self._localize_execution_bundle_manifest(bundle, location)
            return bundle
        if is_nfcore_pipeline_graph(graph):
            bundle = materialize_nfcore_pipeline_bundle(graph, out_root, params=params, execution_location=location.location_id)
            self._localize_execution_bundle_manifest(bundle, location)
            return bundle
        bundle = Path(out_root) / graph_id
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "helpers").mkdir(exist_ok=True)
        (bundle / "manifests").mkdir(exist_ok=True)
        recipe_payload = {
            "schema": "morphic.materialized_recipe/v0",
            "graph_id": graph_id,
            "title": graph.get("title"),
            "nodes": graph.get("nodes"),
            "edges": graph.get("edges"),
        }
        params_review_payload = {"params": params}
        (bundle / "workflow_graph.json").write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n")
        (bundle / "recipe.json").write_text(json.dumps(recipe_payload, indent=2, sort_keys=True) + "\n")
        (bundle / "params.review.json").write_text(json.dumps(params_review_payload, indent=2, sort_keys=True) + "\n")
        (bundle / "params.schema.json").write_text(json.dumps(graph.get("params_schema") or {}, indent=2, sort_keys=True) + "\n")
        write_path_bindings(
            bundle,
            graph,
            params,
            execution_location=location.location_id,
            recipe_payload=recipe_payload,
            params_review_payload=params_review_payload,
        )
        helper = bundle / "helpers" / "README.md"
        helper.write_text(
            "# Helper sources\n\n"
            "This draft bundle reserves editable helper files. "
            "A runnable renderer will populate suite helper scripts here after approval.\n"
        )
        run_sh = bundle / "run.sh"
        run_sh.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"echo \"Blocked: {graph.get('run_blocker') or 'renderer not connected'}\" >&2\n"
            "exit 3\n"
        )
        run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR)
        (bundle / "README.md").write_text(
            f"# {graph.get('title') or graph_id}\n\n"
            "Draft bundle for review. Execution is blocked until the graph renderer is connected.\n"
        )
        self._localize_execution_bundle_manifest(bundle, location)
        return bundle

    def _localize_execution_bundle_manifest(self, bundle: Path, location: Any) -> None:
        try:
            if getattr(location, "kind", "") == "remote_ssh":
                localize_bundle_manifest(Path(bundle), location)
            elif getattr(location, "kind", "") in {"scheduler_temporal", "scheduler_remote_ssh"}:
                localize_bundle_manifest_for_scheduler(Path(bundle), location)
        except ValueError:
            return

    def _execution_payload(self, location: Any, *, bundle_path: Path | None = None) -> dict[str, Any]:
        gate = execution_location_gate(location, "execute")
        payload: dict[str, Any] = {
            "execution_location": location.as_dict(),
            "execution_dispatch": execution_dispatch_for_location(location),
            "execution_run_gate": gate.as_dict(),
        }
        if bundle_path is not None:
            payload.update(path_bindings_response(bundle_path))
            payload.update(container_manifest_response(bundle_path))
            payload["caller_run"] = {
                "command": f"cd {bundle_path} && bash run.sh",
                "api_executable": gate.allowed,
            }
        else:
            payload.update({"path_bindings_path": None, "path_bindings_hash": None})
            payload.update({"container_manifest_path": None, "container_manifest_hash": None})
        return payload

    def _load_bundle_params(self, bundle: Path) -> dict[str, Any]:
        params_path = Path(bundle) / "params.review.json"
        if not params_path.is_file():
            return {}
        loaded = json.loads(params_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("params"), dict):
            return loaded["params"]
        return {}

    def _local_preflight_payload(
        self,
        graph_id: str,
        bundle: Path | None,
        validation_result: dict[str, Any] | None,
        path_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        if bundle is None:
            checks.append({"check": "bundle_path provided for caller-managed bundle", "status": "fail"})
        else:
            run_sh = Path(bundle) / "run.sh"
            checks.append({"check": "bundle contains run.sh", "status": "pass" if run_sh.is_file() else "fail", "path": str(run_sh)})
        checks.extend((validation_result or {}).get("checks") or [])
        checks.append({"check": "caller-visible input paths are caller-managed", "status": "not_run"})
        blockers = list((validation_result or {}).get("blockers") or [])
        if bundle is None:
            blockers.append("bundle_path is required for caller-managed preflight")
        blocker = (
            "The Workbench API cannot execute a caller-local bundle. "
            "Download or copy the bundle and run it in the local shell."
        )
        return {
            "schema": "morphic.preflight_result/v0",
            "status": "blocked",
            "graph_id": graph_id,
            "checks": checks,
            "blockers": blockers + [blocker],
            "run_blocker": "; ".join(blockers + [blocker]) if blockers else blocker,
            "inputs_passed": False,
            "executable_ready": False,
            **path_metadata,
        }

    def _remote_ssh_preflight_payload(
        self,
        graph_id: str,
        bundle: Path | None,
        manifest: dict[str, Any] | None,
        validation_result: dict[str, Any] | None,
        path_metadata: dict[str, Any],
        location: Any,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        blockers = list((validation_result or {}).get("blockers") or [])
        if bundle is None:
            checks.append({"check": "bundle_path provided for remote SSH execution", "status": "fail"})
            blockers.append("bundle_path is required for remote SSH preflight")
        else:
            run_sh = Path(bundle) / "run.sh"
            checks.append({"check": "bundle contains run.sh", "status": "pass" if run_sh.is_file() else "fail", "path": str(run_sh)})
            if not run_sh.is_file():
                blockers.append("bundle is missing run.sh")
        checks.extend((validation_result or {}).get("checks") or [])
        if bundle is not None:
            remote = remote_ssh_preflight(bundle=Path(bundle), location=location, path_manifest=manifest)
            checks.extend(remote.get("checks") or [])
            blockers.extend(remote.get("blockers") or [])
        return {
            "schema": "morphic.preflight_result/v0",
            "status": "preflight_passed" if not blockers else "blocked",
            "graph_id": graph_id,
            "checks": checks,
            "blockers": blockers,
            "run_blocker": "; ".join(blockers) if blockers else None,
            "inputs_passed": not blockers,
            "executable_ready": not blockers,
            **path_metadata,
        }

    def _scheduler_preflight_payload(
        self,
        graph_id: str,
        bundle: Path | None,
        manifest: dict[str, Any] | None,
        validation_result: dict[str, Any] | None,
        path_metadata: dict[str, Any],
        location: Any,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        blockers = list((validation_result or {}).get("blockers") or [])
        if bundle is None:
            checks.append({"check": "bundle_path provided for local scheduler execution", "status": "fail"})
            blockers.append("bundle_path is required for local scheduler preflight")
        checks.extend((validation_result or {}).get("checks") or [])
        scheduler = scheduler_preflight(bundle=Path(bundle) if bundle is not None else None, location=location, path_manifest=manifest)
        checks.extend(scheduler.get("checks") or [])
        blockers.extend(scheduler.get("blockers") or [])
        return {
            "schema": "morphic.preflight_result/v0",
            "status": "preflight_passed" if not blockers else "blocked",
            "graph_id": graph_id,
            "checks": checks,
            "blockers": blockers,
            "run_blocker": "; ".join(blockers) if blockers else None,
            "inputs_passed": not blockers,
            "executable_ready": not blockers,
            "scheduler": scheduler.get("scheduler"),
            **path_metadata,
        }

    def _merge_recipe_preflight(self, result: dict[str, Any], recipe_result: dict[str, Any]) -> dict[str, Any]:
        merged = dict(result)
        merged["execution_route"] = recipe_result.get("execution_route")
        if recipe_result.get("container_diagnostic"):
            merged["container_diagnostic"] = recipe_result.get("container_diagnostic")
        if recipe_result.get("skip_star") is not None:
            merged["skip_star"] = recipe_result.get("skip_star")

        checks = list(merged.get("checks") or [])
        checks.extend(recipe_result.get("checks") or [])
        blockers = list(merged.get("blockers") or [])
        for blocker in recipe_result.get("blockers") or []:
            if blocker not in blockers:
                blockers.append(blocker)

        if recipe_result.get("status") == "blocked" or recipe_result.get("executable_ready") is False:
            merged["status"] = "blocked"
            merged["inputs_passed"] = False
            merged["executable_ready"] = False
            existing = str(merged.get("run_blocker") or "").strip()
            recipe_blocker = str(recipe_result.get("run_blocker") or "").strip()
            merged["run_blocker"] = "; ".join(item for item in (existing, recipe_blocker) if item) or None

        merged["checks"] = checks
        merged["blockers"] = blockers
        return merged

    def _merge_path_binding_validation(
        self,
        result: dict[str, Any],
        validation_result: dict[str, Any] | None,
        path_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if validation_result is None:
            return {**result, **path_metadata}
        merged = dict(result)
        checks = list(merged.get("checks") or [])
        checks.extend(validation_result.get("checks") or [])
        blockers = list(merged.get("blockers") or [])
        for blocker in validation_result.get("blockers") or []:
            if blocker not in blockers:
                blockers.append(blocker)
        if validation_result.get("valid") is False:
            existing = str(merged.get("run_blocker") or "").strip()
            validation_blocker = "; ".join(validation_result.get("blockers") or [])
            merged["run_blocker"] = "; ".join(item for item in (existing, validation_blocker) if item)
            merged["status"] = "blocked"
            merged["executable_ready"] = False
        merged["checks"] = checks
        merged["blockers"] = blockers
        merged.update(path_metadata)
        return merged
