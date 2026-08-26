"""Graph projection service/API contract tests."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from fastmcp import Client
from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.mcp import build_workbench_mcp
from morphic_agent.workbench import WorkbenchService


def test_projection_service_rebuilds_from_canonical_graph_tables(tmp_path: Path):
    service = WorkbenchService.create(db_path=tmp_path / "projection.sqlite3")

    manifest = service.rebuild_graph_projection("projection-contract-v0")
    status = service.projection_status("projection-contract-v0")

    assert manifest["status"] == "ok"
    assert manifest["projection_status"] == "rebuilt"
    assert manifest["canonical_store"] == "postgres"
    assert manifest["graph_index"] == "arcadedb"
    assert manifest["projection_adapter"] == "sqlite"
    assert manifest["source_counts"]["graphs"] > 0
    assert manifest["projected_vertex_count"] > 0
    assert manifest["projected_edge_count"] > 0
    assert status["status"] == "ok"
    assert status["projection_status"] == "rebuilt"
    assert status["projected_vertex_count"] == manifest["projected_vertex_count"]
    assert status["projected_edge_count"] == manifest["projected_edge_count"]
    assert service.store.count_rows("graph_projection_manifests") == 1

    with sqlite3.connect(service.store.db_path) as conn:
        kinds = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT kind FROM graph_projection_vertices WHERE projection_version=?",
                ("projection-contract-v0",),
            ).fetchall()
        }
        labels = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT label FROM graph_projection_edges WHERE projection_version=?",
                ("projection-contract-v0",),
            ).fetchall()
        }

    assert {"Graph", "GraphVersion", "Module", "ArtifactType", "Capability"} <= kinds
    assert {"PRODUCES", "CONSUMES", "HAS_CAPABILITY"} <= labels


def test_projection_dry_run_reports_counts_without_writing_projection_tables(tmp_path: Path):
    service = WorkbenchService.create(db_path=tmp_path / "projection.sqlite3")
    projection_service = service.graph_index.projection_service
    assert projection_service is not None

    dry_run = projection_service.rebuild_projection("dry-run-v0", dry_run=True)

    assert dry_run["status"] == "dry_run"
    assert dry_run["mutated"] is False
    assert dry_run["projected_vertex_count"] > 0
    assert service.store.projection_status("dry-run-v0")["status"] == "missing"
    assert service.store.count_rows("graph_projection_vertices") == 0
    assert service.store.count_rows("graph_projection_edges") == 0


def test_projection_api_and_mcp_surfaces_share_contract(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api.sqlite3")
    client = TestClient(app)

    rebuild = client.post("/api/graphs/projection/rebuild", json={"projection_version": "api-projection-v0"})
    status = client.get("/api/graphs/projection/api-projection-v0")

    assert rebuild.status_code == 200
    assert rebuild.json()["status"] == "ok"
    assert rebuild.json()["projection_status"] == "rebuilt"
    assert status.status_code == 200
    assert status.json()["status"] == "ok"
    assert status.json()["projection_status"] == "rebuilt"
    assert status.json()["projected_vertex_count"] == rebuild.json()["projected_vertex_count"]

    async def run_mcp() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        async with Client(server) as mcp_client:
            mcp_rebuild = (
                await mcp_client.call_tool(
                    "workbench_rebuild_graph_projection",
                    {"projection_version": "mcp-projection-v0"},
                )
            ).data
            mcp_status = (
                await mcp_client.call_tool(
                    "workbench_get_projection_status",
                    {"projection_version": "mcp-projection-v0"},
                )
            ).data
        assert mcp_rebuild["mcp_tool"]["name"] == "workbench_rebuild_graph_projection"
        assert mcp_rebuild["status"] == "ok"
        assert mcp_rebuild["projection_status"] == "rebuilt"
        assert mcp_status["mcp_tool"]["name"] == "workbench_get_projection_status"
        assert mcp_status["status"] == "ok"
        assert mcp_status["projection_status"] == "rebuilt"
        assert mcp_status["projected_edge_count"] == mcp_rebuild["projected_edge_count"]

    asyncio.run(run_mcp())
