"""Shared Workbench service contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.workbench import WorkbenchService


def test_workbench_service_preserves_trimodal_bundle_contract(tmp_path: Path):
    service = WorkbenchService.create(db_path=tmp_path / "service.sqlite3")

    suites = service.suites()
    assert suites["status"] == "ok"
    assert {"star", "chromap", "multiomics"} <= {item["id"] for item in suites["suites"]}

    draft = service.draft_graph("QC report for the trimodal MuData at data/demo_trimodal_small.h5mu")
    assert draft["status"] == "graph_draft"
    assert draft["graph_id"] == "trimodal_qc_report_v0"
    assert draft["durability"] == "stored"

    params = {
        "mudata": "data/demo_trimodal_small.h5mu",
        "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
        "title": "Demo trimodal QC",
    }
    validation = service.validate_params(draft["graph_id"], params)
    assert validation["status"] == "valid"

    review = service.execution_review_request(
        draft["graph_id"],
        params,
        proposed_execution_location="local",
        review_stage="before_render",
        request_context={"client_session_id": "service-contract"},
    )
    assert review["status"] == "needs_user_review"
    assert review["run_id"].startswith("run-")
    assert review["run"]["status"] == "review_required"

    approved = service.complete_execution_review(
        review,
        {"approved": True, "execution_location": "local", "verified_paths": True},
        interaction_mode="service_test",
    )
    assert approved["status"] == "approved"
    assert approved["approved_next_step"]["arguments"]["run_id"] == review["run_id"]
    assert approved["run"]["status"] == "review_approved"

    rendered = service.render_bundle(
        draft["graph_id"],
        params,
        out_root=tmp_path / "bundles",
        request_context={"client_session_id": "service-contract"},
        execution_location="local",
        run_id=approved["run_id"],
    )
    assert rendered["status"] == "materialized"
    assert rendered["run_id"] == review["run_id"]
    assert rendered["run"]["status"] == "bundle_materialized"
    assert rendered["run"]["bundle"]["bundle_id"] == rendered["bundle_id"]
    assert rendered["execution_location"]["kind"] == "local"
    assert rendered["execution_run_gate"]["allowed"] is False
    assert rendered["container_manifest_path"] == "manifests/container.json"

    bundle = Path(rendered["bundle_path"])
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert bindings["mudata"]["path"] == "data/demo_trimodal_small.h5mu"
    assert bindings["output_prefix"]["path_kind"] == "bundle_relative"

    preflight = service.preflight_bundle(
        draft["graph_id"],
        {},
        bundle_path=rendered["bundle_path"],
        execution_location="local",
        run_id=rendered["run_id"],
    )
    assert preflight["status"] == "blocked"
    assert preflight["run_id"] == review["run_id"]
    assert preflight["run"]["status"] == "preflight_blocked"
    assert preflight["run"]["preflight"]["preflight_id"] == preflight["preflight_id"]
    assert preflight["execution_location"]["kind"] == "local"
    assert "caller-local bundle" in preflight["run_blocker"]

    loaded, status = service.get_run(review["run_id"])
    assert status == 200
    assert loaded["run"]["bundle"]["bundle_path"] == rendered["bundle_path"]
    assert loaded["run"]["preflight"]["status"] == "blocked"


def test_workbench_app_exposes_shared_service_instance(tmp_path: Path):
    app = create_app(db_path=tmp_path / "app.sqlite3")
    assert isinstance(app.state.workbench_service, WorkbenchService)

    client = TestClient(app)
    api_suites = client.get("/api/suites").json()
    service_suites = app.state.workbench_service.suites()
    assert api_suites["status"] == service_suites["status"] == "ok"
    assert [item["id"] for item in api_suites["suites"]] == [item["id"] for item in service_suites["suites"]]


def test_workbench_app_exposes_durable_run_endpoints(tmp_path: Path):
    app = create_app(db_path=tmp_path / "app.sqlite3")
    client = TestClient(app)

    params = {
        "mudata": "data/demo_trimodal_small.h5mu",
        "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
    }
    created = client.post(
        "/api/runs",
        json={"graph_id": "trimodal_qc_report_v0", "params": params, "execution_location": "local"},
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    fetched = client.get(f"/api/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["run"]["graph_id"] == "trimodal_qc_report_v0"

    listed = client.get("/api/runs?graph_id=trimodal_qc_report_v0")
    assert listed.status_code == 200
    assert any(item["run_id"] == run_id for item in listed.json()["runs"])
