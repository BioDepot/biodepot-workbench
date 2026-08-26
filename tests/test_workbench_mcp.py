"""MCP adapter tests for the Workbench service."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client

from morphic_agent.mcp import build_workbench_mcp
from morphic_agent.workbench import WorkbenchService


def test_workbench_mcp_tool_schema_and_policy_metadata(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        expected = {
            "workbench_model_status",
            "workbench_list_conversations",
            "workbench_get_conversation",
            "workbench_create_conversation",
            "workbench_update_conversation",
            "workbench_fork_conversation",
            "workbench_list_suites",
            "workbench_list_recipes",
            "workbench_get_recipe",
            "workbench_list_modules",
            "workbench_get_module",
            "workbench_compose_graph",
            "workbench_search_graphs",
            "workbench_rebuild_graph_projection",
            "workbench_get_projection_status",
            "workbench_validate_params",
            "workbench_start_run",
            "workbench_get_run",
            "workbench_attach_validation_to_run",
            "workbench_request_user_review",
            "workbench_render_bundle",
            "workbench_preflight_bundle",
            "workbench_execution_diagnostic",
            "workbench_get_bundle_manifest",
            "workbench_decompose_nfcore_pipeline",
            "workbench_harvest_nfcore_pipeline",
            "workbench_register_nfcore_recipe",
            "workbench_list_nfcore_pipelines",
            "workbench_get_nfcore_recipe",
            "workbench_nfcore_validation_matrix",
            "workbench_list_nfcore_validations",
            "workbench_record_nfcore_reference_validation",
            "workbench_render_nfcore_bundle",
            "workbench_preflight_nfcore_bundle",
        }
        assert expected <= set(tools)
        assert all(tool_name.replace("_", "").isalnum() for tool_name in tools)
        render = tools["workbench_render_bundle"]
        assert render.annotations.readOnlyHint is False
        assert render.annotations.destructiveHint is False
        assert render.meta["morphic.workbench.tool_policy"]["creates_artifact"] is True
        assert "remote_ssh" in render.meta["morphic.workbench.tool_policy"]["supported_execution_locations"]
        assert render.meta["morphic.workbench.tool_policy"]["may_execute_code"] is False
        assert render.meta["morphic.workbench.tool_policy"]["requires_human_approval"] is True
        assert tools["workbench_list_suites"].annotations.readOnlyHint is True
        review = tools["workbench_request_user_review"]
        assert review.annotations.readOnlyHint is True
        assert review.annotations.idempotentHint is False
        assert "ctx" not in review.inputSchema.get("properties", {})
        assert review.meta["morphic.workbench.tool_policy"]["elicits_user_input"] is True
        nfcore_harvest = tools["workbench_harvest_nfcore_pipeline"]
        assert nfcore_harvest.annotations.readOnlyHint is False
        assert nfcore_harvest.meta["morphic.workbench.tool_policy"]["may_execute_code"] is False
        nfcore_decompose = tools["workbench_decompose_nfcore_pipeline"]
        assert nfcore_decompose.annotations.readOnlyHint is True
        assert nfcore_decompose.meta["morphic.workbench.tool_policy"]["creates_artifact"] is False
        nfcore_render = tools["workbench_render_nfcore_bundle"]
        assert nfcore_render.meta["morphic.workbench.tool_policy"]["requires_human_approval"] is True
        assert tools["workbench_record_nfcore_reference_validation"].annotations.readOnlyHint is False
        assert tools["workbench_list_nfcore_validations"].annotations.readOnlyHint is True

    asyncio.run(run())


def test_workbench_mcp_nfcore_local_harvest_and_lookup(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp-nfcore.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        fixture_root = Path(__file__).parent / "fixtures" / "nfcore"
        schema_path = fixture_root / "minimal_nextflow_schema.json"
        modules_path = fixture_root / "minimal_modules.json"

        async with Client(server) as client:
            harvested = (
                await client.call_tool(
                    "workbench_harvest_nfcore_pipeline",
                    {
                        "pipeline_path": str(fixture_root),
                        "schema_path": str(schema_path),
                        "modules_json_path": str(modules_path),
                        "cache_root": str(tmp_path / "nfcore-cache"),
                    },
                )
            ).data
            assert harvested["status"] == "ok"
            assert harvested["module_id"] == "nfcore_demo"
            assert harvested["graph_id"] == "nfcore_demo_v1_2_3"
            assert harvested["cache_manifest"]["pipeline"] == "nf-core/demo"
            assert harvested["mcp_tool"]["name"] == "workbench_harvest_nfcore_pipeline"

            listed = (await client.call_tool("workbench_list_nfcore_pipelines", {"query": "demo"})).data
            assert listed["status"] == "ok"
            assert [item["graph_id"] for item in listed["results"]] == ["nfcore_demo_v1_2_3"]

            recipe = (
                await client.call_tool(
                    "workbench_get_nfcore_recipe",
                    {"identifier": "nfcore_demo_v1_2_3"},
                )
            ).data
            assert recipe["status"] == "ok"
            assert recipe["workflow_graph"]["materialization_status"] == "runnable_nextflow_bundle"
            assert recipe["module_contract"]["runtime"]["kind"] == "nfcore_pipeline"

            matrix = (
                await client.call_tool(
                    "workbench_nfcore_validation_matrix",
                    {
                        "out_root": str(tmp_path / "matrix-bundles"),
                        "execution_location": "local",
                    },
                )
            ).data
            assert matrix["recipe_count"] == 1
            assert matrix["recipes"][0]["graph_id"] == "nfcore_demo_v1_2_3"
            assert matrix["recipes"][0]["render_status"] == "rendered"

            run = (
                await client.call_tool(
                    "workbench_start_run",
                    {
                        "graph_id": "nfcore_demo_v1_2_3",
                        "params": {"input": str(schema_path), "outdir": str(tmp_path / "results")},
                        "execution_location": "scheduler_temporal",
                    },
                )
            ).data
            assert run["status"] == "created"

            recorded = (
                await client.call_tool(
                    "workbench_record_nfcore_reference_validation",
                    {
                        "graph_id": "nfcore_demo_v1_2_3",
                        "run_id": run["run_id"],
                        "comparison_manifest": _reference_comparison_manifest("nfcore_demo_v1_2_3"),
                    },
                )
            ).data
            assert recorded["status"] == "ok"
            assert recorded["http_status"] == 201
            assert recorded["validation_record"]["comparator_kind"] == "reference_nextflow"
            assert recorded["run"]["latest_validation"]["validation_id"] == recorded["validation_record"]["validation_id"]

            validations = (
                await client.call_tool(
                    "workbench_list_nfcore_validations",
                    {
                        "graph_id": "nfcore_demo_v1_2_3",
                        "fixture_id": "chr22",
                        "profile": "docker",
                        "source_manifest_hash": "sha256:test-source",
                    },
                )
            ).data
            assert validations["validation_count"] == 1
            assert validations["validations"][0]["status"] == "passed"

            attached = (
                await client.call_tool(
                    "workbench_attach_validation_to_run",
                    {"run_id": run["run_id"], "validation_id": recorded["validation_record"]["validation_id"]},
                )
            ).data
            assert attached["http_status"] == 200
            assert len(attached["run"]["validations"]) == 1

            preflight = (
                await client.call_tool(
                    "workbench_preflight_nfcore_bundle",
                    {
                        "graph_id": "nfcore_demo_v1_2_3",
                        "params": {"input": str(schema_path), "outdir": str(tmp_path / "results")},
                        "execution_location": "local",
                    },
                )
            ).data
            assert preflight["status"] in {"blocked", "preflight_passed"}
            assert preflight["mcp_tool"]["name"] == "workbench_preflight_nfcore_bundle"

    asyncio.run(run())


def test_workbench_mcp_decomposes_nfcore_source_without_registration(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp-nfcore-decompose.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        pipeline = Path(__file__).parent / "fixtures" / "nfcore" / "decomposition_pipeline"

        async with Client(server) as client:
            payload = (
                await client.call_tool(
                    "workbench_decompose_nfcore_pipeline",
                    {"pipeline_path": str(pipeline)},
                )
            ).data

        assert payload["status"] == "decomposed"
        assert payload["summary"]["source_file_count"] == 6
        assert payload["mcp_tool"]["read_only"] is True
        assert service.list_nfcore_pipelines()["results"] == []

    asyncio.run(run())


def _reference_comparison_manifest(graph_id: str) -> dict:
    return {
        "schema": "morphic.nfcore_reference_nextflow_comparison/v0",
        "status": "passed",
        "comparator_kind": "reference_nextflow",
        "graph_id": graph_id,
        "source_manifest_hash": "sha256:test-source",
        "pipeline": "nf-core/demo",
        "release": "1.2.3",
        "profile": "docker",
        "fixture": {"fixture_id": "chr22", "sample_id": "SRR4422207_CHR22"},
        "reference": {"execution_location_kind": "server", "profile": "docker", "pipeline": "nf-core/demo"},
        "candidate": {
            "graph_id": graph_id,
            "execution_location_kind": "scheduler_temporal",
            "source_manifest_hash": "sha256:test-source",
        },
        "comparisons": [
            {"comparison_kind": "file_sha256", "sha256": "abc"},
            {"comparison_kind": "salmon_quant_contract", "row_count": 10},
        ],
    }


def test_workbench_mcp_nfcore_remote_harvest_requires_network_flag(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp-nfcore-remote.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")

        async with Client(server) as client:
            blocked = (
                await client.call_tool(
                    "workbench_harvest_nfcore_pipeline",
                    {
                        "pipeline_path": "nf-core/demo",
                        "release": "1.2.3",
                        "cache_root": str(tmp_path / "nfcore-cache"),
                    },
                )
            ).data

        assert blocked["status"] == "blocked"
        assert "allow_network=true" in blocked["run_blocker"]
        assert blocked["required_next_step"]["arguments"]["allow_network"] is True
        assert blocked["mcp_tool"]["name"] == "workbench_harvest_nfcore_pipeline"

    asyncio.run(run())


def test_workbench_mcp_nfcore_review_gated_temporal_bundle_render(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MORPHIC_WORKBENCH_REVIEW_SURFACE", raising=False)

    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp-nfcore-render.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        fixture_root = Path(__file__).parent / "fixtures" / "nfcore"
        schema_path = fixture_root / "minimal_nextflow_schema.json"
        modules_path = fixture_root / "minimal_modules.json"
        samplesheet = tmp_path / "samplesheet.csv"
        samplesheet.write_text("sample,fastq_1,fastq_2\nS1,S1_R1.fastq.gz,S1_R2.fastq.gz\n", encoding="utf-8")
        params = {"input": str(samplesheet), "outdir": str(tmp_path / "results")}

        async def approve_review(message, response_type, params, context):
            return {
                "approved": True,
                "execution_location": "scheduler_temporal",
                "verified_paths": True,
                "notes": "Approved nf-core Temporal bundle rendering.",
            }

        async with Client(server, elicitation_handler=approve_review) as client:
            harvested = (
                await client.call_tool(
                    "workbench_register_nfcore_recipe",
                    {
                        "schema_path": str(schema_path),
                        "modules_json_path": str(modules_path),
                    },
                )
            ).data
            graph_id = harvested["graph_id"]

            blocked = (
                await client.call_tool(
                    "workbench_render_nfcore_bundle",
                    {
                        "graph_id": graph_id,
                        "params": params,
                        "execution_location": "scheduler_temporal",
                        "out_root": str(tmp_path / "nfcore-bundles"),
                    },
                )
            ).data
            assert blocked["status"] == "blocked"
            assert "review_approval_token" in blocked["run_blocker"]

            review = (
                await client.call_tool(
                    "workbench_request_user_review",
                    {
                        "graph_id": graph_id,
                        "params": params,
                        "proposed_execution_location": "scheduler_temporal",
                        "review_stage": "before_render",
                    },
                )
            ).data
            rendered = (
                await client.call_tool(
                    "workbench_render_nfcore_bundle",
                    {
                        "graph_id": graph_id,
                        "params": params,
                        "execution_location": "scheduler_temporal",
                        "out_root": str(tmp_path / "nfcore-bundles"),
                        "review_approval_token": review["review_approval"]["token"],
                    },
                )
            ).data

        bundle = Path(rendered["bundle_path"])
        assert rendered["status"] == "materialized"
        assert rendered["mcp_tool"]["name"] == "workbench_render_nfcore_bundle"
        assert rendered["workflow_graph"]["runtime"]["kind"] == "nfcore_pipeline"
        assert rendered["execution_location"]["kind"] == "scheduler_temporal"
        assert (bundle / "manifests" / "nextflow-temporal.config").is_file()
        assert (bundle / "manifests" / "nextflow_scheduler_command.json").is_file()

    asyncio.run(run())


def test_workbench_mcp_trimodal_qc_bundle_contract(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MORPHIC_WORKBENCH_REVIEW_SURFACE", raising=False)

    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        elicitation_seen: dict[str, object] = {}

        async def approve_review(message, response_type, params, context):
            elicitation_seen["message"] = message
            elicitation_seen["response_type"] = response_type
            elicitation_seen["requested_schema"] = getattr(params, "requestedSchema", {})
            return {
                "approved": True,
                "execution_location": "local",
                "verified_paths": True,
                "notes": "Approved for local bundle rendering.",
            }

        async with Client(server, elicitation_handler=approve_review) as client:
            suites = (await client.call_tool("workbench_list_suites", {})).data
            assert suites["status"] == "ok"
            assert {"star", "chromap", "multiomics"} <= {item["id"] for item in suites["suites"]}

            recipes = (await client.call_tool("workbench_list_recipes", {"suite_id": "multiomics", "assay": "trimodal"})).data
            assert recipes["status"] == "ok"
            assert recipes["recipe_count"] >= 1

            draft = (
                await client.call_tool(
                    "workbench_compose_graph",
                    {"goal": "QC report for the trimodal MuData at data/demo_trimodal_small.h5mu"},
                )
            ).data
            assert draft["status"] == "graph_draft"
            assert draft["graph_id"] == "trimodal_qc_report_v0"

            params = {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            }
            validation = (
                await client.call_tool(
                    "workbench_validate_params",
                    {"graph_id": draft["graph_id"], "params": params},
                )
            ).data
            assert validation["status"] == "valid"

            started = (
                await client.call_tool(
                    "workbench_start_run",
                    {"graph_id": draft["graph_id"], "params": params, "execution_location": "local"},
                )
            ).data
            assert started["status"] == "created"
            assert started["run_id"].startswith("run-")
            assert started["run"]["current_step"] == "created"

            review = (
                await client.call_tool(
                    "workbench_request_user_review",
                    {
                        "graph_id": draft["graph_id"],
                        "params": params,
                        "proposed_execution_location": "local",
                        "review_stage": "before_render",
                        "run_id": started["run_id"],
                    },
                )
            ).data
            assert review["status"] == "approved"
            assert review["run_id"] == started["run_id"]
            assert review["run"]["status"] == "review_approved"
            assert review["human_review"]["approved"] is True
            assert review["human_review"]["verified_paths"] is True
            assert review["approved_execution_location"] == "local"
            assert review["params_valid"] is True
            assert review["workbench_handoff"]["url_fragment"].startswith("#workbench=")
            assert review["workbench_handoff"]["preferred_url"].startswith("http://127.0.0.1:8890/?workbench=")
            assert review["workbench_handoff"]["payload"]["action"] == "open_execution_review"
            assert review["approved_next_step"]["tool_name"] == "workbench_render_bundle"
            assert review["approved_next_step"]["arguments"]["execution_location"] == "local"
            assert review["approved_next_step"]["arguments"]["review_approval_token"].startswith("review-")
            assert review["approved_next_step"]["arguments"]["run_id"] == started["run_id"]
            assert review["approved_next_step"]["must_use_approved_execution_location"] is True
            assert review["approved_next_step"]["requires_review_approval_token"] is True
            assert review["review_approval"]["token"] == review["approved_next_step"]["arguments"]["review_approval_token"]
            assert "Workbench user review required" in str(elicitation_seen["message"])
            requested_schema = elicitation_seen["requested_schema"]
            assert isinstance(requested_schema, dict)
            assert {"approved", "execution_location", "verified_paths"} <= set(requested_schema["properties"])

            blocked_render = (
                await client.call_tool(
                    "workbench_render_bundle",
                    {
                        "graph_id": draft["graph_id"],
                        "params": params,
                        "execution_location": "local",
                    },
                )
            ).data
            assert blocked_render["status"] == "blocked"
            assert "review_approval_token" in blocked_render["run_blocker"]

            rendered = (
                await client.call_tool(
                    "workbench_render_bundle",
                    review["approved_next_step"]["arguments"],
                )
            ).data
            assert rendered["status"] == "materialized"
            assert rendered["mcp_tool"]["creates_artifact"] is True
            assert rendered["run_id"] == started["run_id"]
            assert rendered["run"]["status"] == "bundle_materialized"
            assert rendered["execution_location"]["kind"] == "local"
            assert rendered["container_manifest_path"] == "manifests/container.json"

            manifest = (
                await client.call_tool(
                    "workbench_get_bundle_manifest",
                    {"bundle_path": rendered["bundle_path"]},
                )
            ).data
            assert manifest["status"] == "ok"
            assert manifest["has_run_script"] is True
            bindings = {item["binding_id"]: item for item in manifest["manifests"]["path_bindings"]["bindings"]}
            assert bindings["mudata"]["path"] == "data/demo_trimodal_small.h5mu"
            assert bindings["output_prefix"]["path_kind"] == "bundle_relative"

            preflight = (
                await client.call_tool(
                    "workbench_preflight_bundle",
                    {
                        "graph_id": draft["graph_id"],
                        "bundle_path": rendered["bundle_path"],
                        "execution_location": "local",
                        "run_id": rendered["run_id"],
                    },
                )
            ).data
            assert preflight["status"] == "blocked"
            assert preflight["run_id"] == started["run_id"]
            assert preflight["run"]["status"] == "preflight_blocked"
            assert "caller-local bundle" in preflight["run_blocker"]

            diagnostic = (
                await client.call_tool(
                    "workbench_execution_diagnostic",
                    {
                        "graph_id": draft["graph_id"],
                        "bundle_path": rendered["bundle_path"],
                        "execution_location": "local",
                        "run_id": rendered["run_id"],
                    },
                )
            ).data
            assert diagnostic["schema"] == "morphic.execution_location_diagnostic/v0"
            assert diagnostic["status"] == "blocked"
            assert diagnostic["run_id"] == started["run_id"]
            assert diagnostic["http_status"] == 200
            assert diagnostic["can_execute_in_api"] is False
            assert diagnostic["execution_dispatch"]["dispatch_kind"] == "caller_managed_shell"
            assert diagnostic["container"]["image"]["reference"] == "biodepot/morphic-trimodal-qc:0.1.0"
            assert {item["name"] for item in diagnostic["requirements"]} >= {"python3", "mudata", "scanpy"}
            diagnostic_options = {item["id"]: item for item in diagnostic["resolution_options"]}
            assert {"run_local_container", "run_local_shell", "regenerate_for_server"} <= set(diagnostic_options)
            assert diagnostic_options["regenerate_for_server"]["api_managed"] is True
            assert diagnostic["workbench_handoff"]["payload"]["action"] == "open_execution_diagnostic"
            assert diagnostic["workbench_handoff"]["url_fragment"].startswith("#workbench=")
            assert diagnostic["workbench_handoff"]["preferred_url"].startswith("http://127.0.0.1:8890/?workbench=")
            assert diagnostic["workbench_handoff"]["payload"]["params"]["mudata"] == params["mudata"]

            loaded_run = (await client.call_tool("workbench_get_run", {"run_id": started["run_id"]})).data
            assert loaded_run["status"] == "ok"
            assert loaded_run["run"]["bundle"]["bundle_path"] == rendered["bundle_path"]
            assert loaded_run["run"]["diagnostic"]["status"] == "blocked"

            path_bindings = json.loads((Path(rendered["bundle_path"]) / "manifests" / "path_bindings.json").read_text())
            assert path_bindings == manifest["manifests"]["path_bindings"]

    asyncio.run(run())


def test_workbench_mcp_user_changed_execution_location_controls_next_step(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MORPHIC_WORKBENCH_REVIEW_SURFACE", raising=False)

    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")

        async def approve_server(message, response_type, params, context):
            return {
                "approved": True,
                "execution_location": "server",
                "verified_paths": True,
                "notes": "Use server execution instead.",
            }

        async with Client(server, elicitation_handler=approve_server) as client:
            review = (
                await client.call_tool(
                    "workbench_request_user_review",
                    {
                        "graph_id": "trimodal_qc_report_v0",
                        "params": {
                            "mudata": "data/demo_trimodal_small.h5mu",
                            "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                            "title": "Demo trimodal QC",
                        },
                        "proposed_execution_location": "local",
                    },
                )
            ).data
        assert review["status"] == "approved"
        assert review["approved_execution_location"] == "server"
        assert review["execution_location_changed_by_user"] is True
        assert review["approved_next_step"]["arguments"]["execution_location"] == "server"
        assert review["approved_next_step"]["arguments"]["review_approval_token"].startswith("review-")
        assert review["approved_next_step"]["must_use_approved_execution_location"] is True
        assert review["approved_next_step"]["requires_review_approval_token"] is True
        assert review["workbench_handoff"]["payload"]["execution_location"] == "server"
        assert review["workbench_handoff"]["payload"]["params"]["mudata"] == "data/demo_trimodal_small.h5mu"

        async with Client(server) as client:
            stale_local_render = (
                await client.call_tool(
                    "workbench_render_bundle",
                    {
                        **review["approved_next_step"]["arguments"],
                        "execution_location": "local",
                    },
                )
            ).data
        assert stale_local_render["status"] == "blocked"
        assert "does not match graph_id, params, or execution_location" in stale_local_render["run_blocker"]

    asyncio.run(run())


def test_workbench_mcp_browser_review_surface_returns_url_without_elicitation(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        elicitation_called = False

        async def fail_if_called(message, response_type, params, context):
            nonlocal elicitation_called
            elicitation_called = True
            return {"approved": True, "execution_location": "server", "verified_paths": True}

        async with Client(server, elicitation_handler=fail_if_called) as client:
            params = {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            }
            review = (
                await client.call_tool(
                    "workbench_request_user_review",
                    {
                        "graph_id": "trimodal_qc_report_v0",
                        "params": params,
                        "remote_host": "10.159.4.53",
                        "remote_user": "lhhung",
                        "remote_workdir": "/tmp/morphic-cursor-ssh/trimodal_qc_report_v0",
                        "remote_container_runtime": "docker",
                        "remote_path_overrides": {},
                        "review_surface": "browser",
                    },
                )
            ).data
            blocked_render = (
                await client.call_tool(
                    "workbench_render_bundle",
                    {
                        "graph_id": "trimodal_qc_report_v0",
                        "params": params,
                        "execution_location": {
                            "location_id": "remote_ssh",
                            "metadata": {
                                "remote_host": "10.159.4.53",
                                "remote_user": "lhhung",
                                "remote_workdir": "/tmp/morphic-cursor-ssh/trimodal_qc_report_v0",
                                "remote_container_runtime": "docker",
                                "remote_path_overrides": {},
                            },
                        },
                        "review_approval_token": "review-synthesized-by-agent",
                    },
                )
            ).data

        assert elicitation_called is False
        assert review["status"] == "needs_browser_review"
        assert review["interaction"]["mode"] == "workbench_browser"
        assert review["browser_review_url"].startswith("http://127.0.0.1:8890/?workbench=")
        assert review["required_next_step"]["action"] == "open_browser_review_url"
        assert review["approved_next_step"] is None
        assert review["browser_review_must_be_opened"] is True
        assert review["mcp_render_blocked_until_browser_approval"] is True
        assert review["workbench_handoff"]["payload"]["execution_location"] == "remote_ssh"
        assert review["workbench_handoff"]["payload"]["execution_location_metadata"]["remote_host"] == "10.159.4.53"
        assert review["workbench_handoff"]["payload"]["execution_location_metadata"]["remote_workdir"].endswith("/trimodal_qc_report_v0")
        assert review["elicitation"]["available"] is False
        assert blocked_render["status"] == "blocked"
        assert "not issued by a completed Workbench user review" in blocked_render["run_blocker"]

    asyncio.run(run())


def test_workbench_mcp_render_accepts_browser_issued_token_across_processes(tmp_path: Path):
    async def run() -> None:
        db_path = tmp_path / "shared.sqlite3"
        params = {
            "mudata": "data/demo_trimodal_small.h5mu",
            "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
            "title": "Demo trimodal QC",
        }
        api_service = WorkbenchService.create(db_path=db_path)
        review = api_service.execution_review_request(
            "trimodal_qc_report_v0",
            params,
            proposed_execution_location={
                "location_id": "remote_ssh",
                "metadata": {
                    "remote_host": "10.159.4.53",
                    "remote_user": "lhhung",
                    "remote_workdir": "/tmp/morphic-cursor-ssh/trimodal_qc_report_v0",
                    "remote_container_runtime": "docker",
                    "remote_path_overrides": {},
                    "remote_check": False,
                },
            },
            review_stage="before_render",
            request_context={"client": "browser"},
        )
        approved = api_service.complete_execution_review(
            review,
            {
                "approved": True,
                "execution_location": "remote_ssh",
                "verified_paths": True,
                "remote_host": "10.159.4.53",
                "remote_user": "lhhung",
                "remote_workdir": "/tmp/morphic-cursor-ssh/trimodal_qc_report_v0",
                "remote_container_runtime": "docker",
                "remote_path_overrides": {},
                "remote_check": False,
            },
            action="accept",
            interaction_mode="http_form",
        )
        assert approved["status"] == "approved"

        mcp_service = WorkbenchService.create(db_path=db_path)
        server = build_workbench_mcp(service=mcp_service, bundle_root=tmp_path / "bundles")
        async with Client(server) as client:
            rendered = (
                await client.call_tool(
                    "workbench_render_bundle",
                    approved["approved_next_step"]["arguments"],
                )
            ).data

        assert rendered["status"] == "materialized"
        assert rendered["execution_location"]["kind"] == "remote_ssh"
        manifest = json.loads((Path(rendered["bundle_path"]) / "manifests" / "path_bindings.json").read_text())
        bindings = {item["binding_id"]: item for item in manifest["bindings"]}
        assert bindings["mudata"]["path_kind"] == "bundle_relative"
        assert bindings["mudata"]["path"].startswith("inputs/mudata/")

    asyncio.run(run())


def test_workbench_mcp_user_review_falls_back_when_elicitation_is_missing(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        async with Client(server) as client:
            review = (
                await client.call_tool(
                    "workbench_request_user_review",
                    {
                        "graph_id": "trimodal_qc_report_v0",
                        "params": {
                            "mudata": "data/demo_trimodal_small.h5mu",
                            "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                            "title": "Demo trimodal QC",
                        },
                        "proposed_execution_location": "local",
                    },
                )
            ).data
        assert review["status"] == "needs_user_input"
        assert review["elicitation"]["available"] is False
        assert "response_schema" in review["elicitation"]
        assert review["workbench_handoff"]["payload"]["action"] == "open_execution_review"
        assert review["human_review"] is None
        assert "approval" in review["run_blocker"]

    asyncio.run(run())


def test_workbench_mcp_stdio_entrypoint_lists_tools(tmp_path: Path):
    async def run() -> None:
        env = {
            "MORPHIC_AGENT_DB": str(tmp_path / "stdio.sqlite3"),
            "MORPHIC_AGENT_BUNDLE_ROOT": str(tmp_path / "stdio-bundles"),
            "PYTHONPATH": os.getcwd(),
        }
        config = {
            "mcpServers": {
                "workbench": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "morphic_agent.mcp.server", "--transport", "stdio"],
                    "env": env,
                }
            }
        }
        async with Client(config) as client:
            tools = {tool.name for tool in await client.list_tools()}
        assert "workbench_list_suites" in tools
        assert "workbench_render_bundle" in tools

    asyncio.run(run())
