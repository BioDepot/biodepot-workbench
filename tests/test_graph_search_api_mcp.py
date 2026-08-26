"""HTTP and MCP graph-search surface tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import Client
from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.mcp import build_workbench_mcp
from morphic_agent.workbench import WorkbenchService


NFCORE_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"
NFCORE_SCHEMA_FIXTURE = NFCORE_FIXTURE_ROOT / "minimal_nextflow_schema.json"
NFCORE_MODULES_FIXTURE = NFCORE_FIXTURE_ROOT / "minimal_modules.json"


def test_graph_search_api_finds_trimodal_qc_by_text_and_artifact_filters(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api.sqlite3")
    client = TestClient(app)

    text = client.post("/api/graphs/search", json={"query": "trimodal qc h5mu"})
    filtered = client.post(
        "/api/graphs/search",
        json={
            "filters": {
                "input_artifact_types": ["h5mu"],
                "output_artifact_types": ["html", "json"],
                "runnable_only": True,
            }
        },
    )
    unknown = client.post("/api/graphs/search", json={"query": "zzzz_unmatched_token"})

    assert text.status_code == 200
    assert text.json()["results"][0]["graph_id"] == "trimodal_qc_report_v0"
    assert filtered.status_code == 200
    assert filtered.json()["results"][0]["graph_id"] == "trimodal_qc_report_v0"
    assert filtered.json()["results"][0]["match_reasons"]
    assert unknown.status_code == 200
    assert unknown.json()["results"] == []


def test_graph_search_api_exposes_nfcore_validation_facets(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api.sqlite3")
    client = TestClient(app)

    harvested = client.post(
        "/api/nfcore/harvest",
        json={
            "schema_path": str(NFCORE_SCHEMA_FIXTURE),
            "modules_json_path": str(NFCORE_MODULES_FIXTURE),
            "cache_root": str(tmp_path / "nfcore-cache"),
        },
    )
    assert harvested.status_code == 201

    validation = client.post(
        "/api/nfcore/validations/reference",
        json={
            "graph_id": "nfcore_demo_v1_2_3",
            "comparison_manifest": _reference_comparison_manifest("nfcore_demo_v1_2_3"),
        },
    )
    assert validation.status_code == 201

    response = client.post(
        "/api/graphs/search",
        json={
            "filters": {
                "suite": "nf-core",
                "validated_only": True,
                "validation_status": "passed",
                "validation_kind": "nfcore_reference_comparison",
                "validation_comparator_kind": "reference_nextflow",
                "validation_fixture": "chr22",
            },
            "limit": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result_count"] == 1
    result = body["results"][0]
    assert result["graph_id"] == "nfcore_demo_v1_2_3"
    assert result["validated"] is True
    assert result["latest_validation"]["status"] == "passed"
    assert result["latest_validation"]["comparator_kind"] == "reference_nextflow"
    assert result["validation_fixtures"] == ["chr22"]
    assert "filter `validated_only` matched" in result["match_reasons"]
    assert "filter `validation_comparator_kind` matched" in result["match_reasons"]


def test_workbench_search_graphs_mcp_tool_uses_same_contract(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")

        async with Client(server) as client:
            result = (
                await client.call_tool(
                    "workbench_search_graphs",
                    {
                        "query": "bulk RNA-seq DEG",
                        "filters": {"capabilities": ["deg"], "runnable_only": True},
                    },
                )
            ).data

        assert result["status"] == "ok"
        assert result["mcp_tool"]["name"] == "workbench_search_graphs"
        assert result["results"][0]["graph_id"] == "bulk_pe_deseq2_v0"
        assert "filter `capabilities` matched" in result["results"][0]["match_reasons"]

    asyncio.run(run())


def test_workbench_search_graphs_mcp_tool_filters_nfcore_validations(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        service.harvest_nfcore_pipeline(
            schema_path=NFCORE_SCHEMA_FIXTURE,
            modules_json_path=NFCORE_MODULES_FIXTURE,
            cache_root=tmp_path / "nfcore-cache",
        )
        recorded, status = service.record_nfcore_reference_validation(
            graph_id="nfcore_demo_v1_2_3",
            comparison_manifest=_reference_comparison_manifest("nfcore_demo_v1_2_3"),
        )
        assert status == 201
        assert recorded["validation_record"]["fixture_id"] == "chr22"

        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")

        async with Client(server) as client:
            result = (
                await client.call_tool(
                    "workbench_search_graphs",
                    {
                        "filters": {
                            "suite": "nf-core",
                            "validated_only": True,
                            "validation_status": "passed",
                            "validation_comparator_kind": "reference_nextflow",
                            "validation_fixture": "chr22",
                        },
                    },
                )
            ).data

        assert result["status"] == "ok"
        assert result["mcp_tool"]["name"] == "workbench_search_graphs"
        assert result["results"][0]["graph_id"] == "nfcore_demo_v1_2_3"
        assert result["results"][0]["validated"] is True
        assert result["results"][0]["latest_validation"]["fixture_id"] == "chr22"

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
