"""Workbench service and HTTP nf-core harvest surface tests."""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.workbench import WorkbenchService


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"
SCHEMA_FIXTURE = FIXTURE_ROOT / "minimal_nextflow_schema.json"
MODULES_FIXTURE = FIXTURE_ROOT / "minimal_modules.json"


def test_workbench_service_harvests_lists_and_gets_nfcore_recipe(tmp_path: Path):
    service = WorkbenchService.create(db_path=tmp_path / "service.sqlite3")

    harvested = service.harvest_nfcore_pipeline(
        schema_path=SCHEMA_FIXTURE,
        modules_json_path=MODULES_FIXTURE,
        cache_root=tmp_path / "nfcore-cache",
    )

    assert harvested["status"] == "ok"
    assert harvested["source_kind"] == "local_schema"
    assert harvested["module_id"] == "nfcore_demo"
    assert harvested["graph_id"] == "nfcore_demo_v1_2_3"
    assert harvested["cache_manifest"]["pipeline"] == "nf-core/demo"

    listed = service.list_nfcore_pipelines(query="demo")
    assert listed["status"] == "ok"
    assert [item["graph_id"] for item in listed["results"]] == ["nfcore_demo_v1_2_3"]

    recipe, status = service.get_nfcore_recipe("nfcore_demo_v1_2_3")
    assert status == 200
    assert recipe["workflow_graph"]["runtime"]["kind"] == "nfcore_pipeline"
    assert recipe["module_contract"]["module_id"] == "nfcore_demo"

    by_module, module_status = service.get_nfcore_recipe("nfcore_demo")
    assert module_status == 200
    assert by_module["graph_id"] == "nfcore_demo_v1_2_3"

    blocked = service.harvest_nfcore_pipeline(pipeline_path="nf-core/demo", release="1.2.3")
    assert blocked["status"] == "blocked"
    assert "allow_network=true" in blocked["run_blocker"]

    run = service.start_run(
        "nfcore_demo_v1_2_3",
        {"input": str(SCHEMA_FIXTURE), "outdir": str(tmp_path / "results")},
        execution_location="scheduler_temporal",
    )
    recorded, record_status = service.record_nfcore_reference_validation(
        graph_id="nfcore_demo_v1_2_3",
        comparison_manifest=_reference_comparison_manifest("nfcore_demo_v1_2_3"),
        run_id=run["run_id"],
    )
    assert record_status == 201
    assert recorded["validation_record"]["status"] == "passed"
    assert recorded["run"]["latest_validation"]["validation_id"] == recorded["validation_record"]["validation_id"]
    assert recorded["run"]["latest_validation"]["comparator_kind"] == "reference_nextflow"
    validations = service.list_nfcore_validations(graph_id="nfcore_demo_v1_2_3", fixture_id="chr22")
    assert validations["validation_count"] == 1
    assert validations["validations"][0]["comparator_kind"] == "reference_nextflow"
    by_source = service.list_nfcore_validations(
        graph_id="nfcore_demo_v1_2_3",
        profile="docker",
        source_manifest_hash="sha256:test-source",
    )
    assert by_source["validation_count"] == 1
    loaded, loaded_status = service.get_run(run["run_id"])
    assert loaded_status == 200
    assert loaded["run"]["validations"][0]["validation_id"] == recorded["validation_record"]["validation_id"]
    hydrated, hydrated_status = service.get_graph("nfcore_demo_v1_2_3")
    assert hydrated_status == 200
    assert hydrated["workflow_graph"]["latest_validation"]["validation_id"] == recorded["validation_record"]["validation_id"]

    validated = service.search_graphs(filters={"suite": "nf-core", "validated_only": True})
    assert [item["graph_id"] for item in validated["results"]] == ["nfcore_demo_v1_2_3"]


def test_workbench_api_nfcore_harvest_render_and_preflight(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api.sqlite3")
    client = TestClient(app)

    harvested = client.post(
        "/api/nfcore/harvest",
        json={
            "schema_path": str(SCHEMA_FIXTURE),
            "modules_json_path": str(MODULES_FIXTURE),
            "cache_root": str(tmp_path / "nfcore-cache"),
        },
    )
    assert harvested.status_code == 201
    harvested_body = harvested.json()
    assert harvested_body["status"] == "ok"
    assert harvested_body["graph_id"] == "nfcore_demo_v1_2_3"
    assert harvested_body["workflow_graph"]["materialization_status"] == "runnable_nextflow_bundle"

    listed = client.get("/api/nfcore/pipelines?q=demo")
    assert listed.status_code == 200
    assert [item["graph_id"] for item in listed.json()["results"]] == ["nfcore_demo_v1_2_3"]

    matrix = client.get(f"/api/nfcore/validation-matrix?out_root={tmp_path / 'matrix-bundles'}&execution_location=local")
    assert matrix.status_code == 200
    matrix_body = matrix.json()
    assert matrix_body["recipe_count"] == 1
    assert matrix_body["recipes"][0]["graph_id"] == "nfcore_demo_v1_2_3"
    assert matrix_body["recipes"][0]["render_status"] == "rendered"

    recipe = client.get("/api/nfcore/pipelines/nfcore_demo_v1_2_3")
    assert recipe.status_code == 200
    assert recipe.json()["module_contract"]["runtime"]["kind"] == "nfcore_pipeline"

    run = client.post(
        "/api/runs",
        json={
            "graph_id": "nfcore_demo_v1_2_3",
            "params": {"input": str(SCHEMA_FIXTURE), "outdir": str(tmp_path / "results")},
            "execution_location": "scheduler_temporal",
        },
    )
    assert run.status_code == 201
    run_id = run.json()["run_id"]

    validation = client.post(
        "/api/nfcore/validations/reference",
        json={
            "graph_id": "nfcore_demo_v1_2_3",
            "run_id": run_id,
            "comparison_manifest": _reference_comparison_manifest("nfcore_demo_v1_2_3"),
        },
    )
    assert validation.status_code == 201
    assert validation.json()["validation_record"]["fixture_id"] == "chr22"
    assert validation.json()["run"]["latest_validation"]["fixture_id"] == "chr22"

    validations = client.get(
        "/api/nfcore/validations"
        "?graph_id=nfcore_demo_v1_2_3&fixture_id=chr22&profile=docker&source_manifest_hash=sha256:test-source"
    )
    assert validations.status_code == 200
    assert validations.json()["validation_count"] == 1

    fetched_run = client.get(f"/api/runs/{run_id}")
    assert fetched_run.status_code == 200
    assert fetched_run.json()["run"]["validations"][0]["validation_id"] == validation.json()["validation_record"]["validation_id"]

    hydrated_graph = client.get("/api/graphs/nfcore_demo_v1_2_3")
    assert hydrated_graph.status_code == 200
    assert hydrated_graph.json()["workflow_graph"]["latest_validation"]["validation_id"] == validation.json()["validation_record"]["validation_id"]

    hydrated_recipe = client.get("/api/nfcore/pipelines/nfcore_demo_v1_2_3")
    assert hydrated_recipe.status_code == 200
    assert hydrated_recipe.json()["workflow_graph"]["latest_validation"]["fixture_id"] == "chr22"

    attached = client.post(
        f"/api/runs/{run_id}/validations",
        json={"validation_id": validation.json()["validation_record"]["validation_id"]},
    )
    assert attached.status_code == 200
    assert len(attached.json()["run"]["validations"]) == 1

    params_schema = client.get("/api/graphs/nfcore_demo_v1_2_3/params/schema")
    assert params_schema.status_code == 200
    assert "input" in params_schema.json()["params_schema"]["required"]

    params = {"input": str(SCHEMA_FIXTURE), "outdir": str(tmp_path / "results")}
    rendered = client.post(
        "/api/graphs/nfcore_demo_v1_2_3/render",
        json={
            "params": params,
            "execution_location": "server",
            "out_root": str(tmp_path / "bundles"),
        },
    )
    assert rendered.status_code == 200
    rendered_body = rendered.json()
    assert rendered_body["status"] == "materialized"
    assert rendered_body["workflow_graph"]["runtime"]["kind"] == "nfcore_pipeline"
    assert rendered_body["execution_location"]["kind"] == "server"

    preflight = client.post(
        "/api/graphs/nfcore_demo_v1_2_3/preflight",
        json={
            "params": {},
            "bundle_path": rendered_body["bundle_path"],
            "execution_location": "server",
        },
    )
    assert preflight.status_code == 200
    preflight_body = preflight.json()
    assert preflight_body["graph_id"] == "nfcore_demo_v1_2_3"
    assert preflight_body["status"] in {"blocked", "preflight_passed"}
    assert preflight_body["launch_command"] == "nextflow run nf-core/demo -r 1.2.3 -profile docker -params-file nf-params.json"

    execution = client.post(
        "/api/graphs/nfcore_demo_v1_2_3/execute-production",
        json={
            "bundle_path": rendered_body["bundle_path"],
            "execution_location": "server",
        },
    )
    assert execution.status_code == 403
    execution_body = execution.json()
    assert execution_body["schema"] == "morphic.nfcore_execution_opt_in_gate/v0"
    assert execution_body["status"] == "blocked"
    assert "MORPHIC_RUN_NFCORE_EXECUTION=1" in execution_body["run_blocker"]
    assert execution_body["required_next_step"]["body"]["allow_nfcore_execution"] is True


def test_workbench_api_nfcore_remote_harvest_requires_network_flag(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api.sqlite3")
    client = TestClient(app)

    blocked = client.post(
        "/api/nfcore/harvest",
        json={"pipeline_path": "nf-core/demo", "release": "1.2.3"},
    )

    assert blocked.status_code == 400
    body = blocked.json()
    assert body["status"] == "blocked"
    assert "allow_network=true" in body["run_blocker"]


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
