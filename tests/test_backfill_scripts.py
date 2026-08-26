"""CLI utility smoke tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from morphic_agent.registry.store import AgentStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_json(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_backfill_graph_search_dry_run_does_not_create_target_db(tmp_path: Path):
    target = tmp_path / "dry-run-target.sqlite3"

    payload = _run_json(
        "scripts/backfill_graph_search_index.py",
        "--db",
        f"sqlite:///{target}",
        "--dry-run",
    )

    assert payload["status"] == "dry_run"
    assert payload["mutated"] is False
    assert payload["planned"]["module_catalog_modules"] > 0
    assert target.exists() is False


def test_rebuild_graph_projection_dry_run_does_not_create_target_db(tmp_path: Path):
    target = tmp_path / "projection-target.sqlite3"

    payload = _run_json(
        "scripts/rebuild_graph_projection.py",
        "--db",
        str(target),
        "--projection-version",
        "script-dry-run-v0",
        "--dry-run",
    )

    assert payload["status"] == "dry_run"
    assert payload["mutated"] is False
    assert payload["projected_vertex_count"] > 0
    assert payload["target_db"] == str(target)
    assert target.exists() is False


def test_migrate_agent_store_dry_run_reports_counts_without_target_mutation(tmp_path: Path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "target.sqlite3"
    AgentStore(source).ensure_thread("thread-smoke")

    payload = _run_json(
        "scripts/migrate_agent_store_to_workbench_db.py",
        "--source-db",
        str(source),
        "--db",
        str(target),
        "--dry-run",
    )

    assert payload["status"] == "dry_run"
    assert payload["mutated"] is False
    assert payload["source_counts"]["agent_threads"] == 1
    assert target.exists() is False


def test_harvest_nfcore_pipeline_dry_run_maps_fixture_without_target_mutation(tmp_path: Path):
    target = tmp_path / "nfcore-target.sqlite3"
    cache_root = tmp_path / "nfcore-cache"
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "nfcore"

    payload = _run_json(
        "scripts/harvest_nfcore_pipeline.py",
        str(fixture_root),
        "--schema",
        str(fixture_root / "minimal_nextflow_schema.json"),
        "--modules-json",
        str(fixture_root / "minimal_modules.json"),
        "--db",
        str(target),
        "--cache-root",
        str(cache_root),
        "--dry-run",
    )

    assert payload["status"] == "dry_run"
    assert payload["mutated"] is False
    assert payload["module_id"] == "nfcore_demo"
    assert payload["graph_id"] == "nfcore_demo_v1_2_3"
    assert payload["search_facets"]["suite"] == "nf-core"
    assert target.exists() is False
    assert cache_root.exists() is False
    assert payload["would_cache_metadata"] is True


def test_harvest_nfcore_pipeline_writes_target_db(tmp_path: Path):
    target = tmp_path / "nfcore-target.sqlite3"
    cache_root = tmp_path / "nfcore-cache"
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "nfcore"

    payload = _run_json(
        "scripts/harvest_nfcore_pipeline.py",
        str(fixture_root),
        "--schema",
        str(fixture_root / "minimal_nextflow_schema.json"),
        "--modules-json",
        str(fixture_root / "minimal_modules.json"),
        "--db",
        str(target),
        "--cache-root",
        str(cache_root),
    )

    assert payload["status"] == "harvested"
    assert payload["mutated"] is True
    assert payload["module_id"] == "nfcore_demo"
    assert payload["graph_id"] == "nfcore_demo_v1_2_3"
    assert payload["cache_manifest"]["pipeline"] == "nf-core/demo"
    assert target.exists() is True
    assert cache_root.exists() is True

    store = AgentStore(target)
    assert store.get_module_contract("nfcore_demo") is not None
    assert store.get_subgraph("nfcore_demo_v1_2_3") is not None


def test_harvest_nfcore_pipeline_remote_spec_requires_network_flag(tmp_path: Path):
    target = tmp_path / "nfcore-target.sqlite3"

    result = _run_script(
        "scripts/harvest_nfcore_pipeline.py",
        "nf-core/demo",
        "--db",
        str(target),
        "--dry-run",
    )

    assert result.returncode != 0
    assert "requires --allow-network" in result.stderr
    assert target.exists() is False


def test_harvest_nfcore_index_dry_run_maps_explicit_entries_without_mutation(tmp_path: Path):
    target = tmp_path / "nfcore-index-target.sqlite3"
    cache_root = tmp_path / "nfcore-index-cache"
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "nfcore"
    index_path = tmp_path / "nfcore-index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "morphic.harvest.nfcore_index_fixture/v0",
                "pipelines": [
                    {
                        "id": "demo",
                        "schema_path": str(fixture_root / "minimal_nextflow_schema.json"),
                        "modules_json_path": str(fixture_root / "minimal_modules.json"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _run_json(
        "scripts/harvest_nfcore_index.py",
        str(index_path),
        "--db",
        str(target),
        "--cache-root",
        str(cache_root),
        "--dry-run",
    )

    assert payload["status"] == "ok"
    assert payload["mutated"] is False
    assert payload["entry_count"] == 1
    assert payload["results"][0]["status"] == "dry_run"
    assert payload["results"][0]["module_id"] == "nfcore_demo"
    assert payload["results"][0]["graph_id"] == "nfcore_demo_v1_2_3"
    assert target.exists() is False
    assert cache_root.exists() is False


def test_harvest_nfcore_index_writes_target_db_and_cache(tmp_path: Path):
    target = tmp_path / "nfcore-index-target.sqlite3"
    cache_root = tmp_path / "nfcore-index-cache"
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "nfcore"
    index_path = tmp_path / "nfcore-index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "demo",
                    "schema_path": str(fixture_root / "minimal_nextflow_schema.json"),
                    "modules_json_path": str(fixture_root / "minimal_modules.json"),
                }
            ]
        ),
        encoding="utf-8",
    )

    payload = _run_json(
        "scripts/harvest_nfcore_index.py",
        str(index_path),
        "--db",
        str(target),
        "--cache-root",
        str(cache_root),
    )

    assert payload["status"] == "ok"
    assert payload["mutated"] is True
    assert payload["ok_count"] == 1
    assert payload["results"][0]["cache_manifest"]["pipeline"] == "nf-core/demo"
    assert target.exists() is True
    assert cache_root.exists() is True
    store = AgentStore(target)
    assert store.get_module_contract("nfcore_demo") is not None
    assert store.get_subgraph("nfcore_demo_v1_2_3") is not None


def test_harvest_nfcore_index_remote_entries_are_blocked_without_network_flag(tmp_path: Path):
    index_path = tmp_path / "nfcore-index.json"
    index_path.write_text(json.dumps({"pipelines": [{"id": "demo-remote", "pipeline": "nf-core/demo", "release": "1.2.3"}]}), encoding="utf-8")

    payload = _run_json("scripts/harvest_nfcore_index.py", str(index_path), "--dry-run")

    assert payload["status"] == "blocked"
    assert payload["blocked_count"] == 1
    assert payload["results"][0]["status"] == "blocked"
    assert "allow-network" in payload["results"][0]["run_blocker"]


def test_register_nfcore_validation_dry_run_does_not_create_target_db(tmp_path: Path):
    target = tmp_path / "nfcore-validation-target.sqlite3"
    manifest_path = tmp_path / "comparison.json"
    manifest_path.write_text(json.dumps(_nfcore_comparison_manifest("nfcore_demo_v1_2_3")), encoding="utf-8")

    payload = _run_json(
        "scripts/register_nfcore_validation.py",
        str(manifest_path),
        "--db",
        str(target),
        "--dry-run",
    )

    assert payload["status"] == "dry_run"
    assert payload["mutated"] is False
    assert payload["validation_record"]["graph_id"] == "nfcore_demo_v1_2_3"
    assert payload["validation_record"]["comparator_kind"] == "reference_nextflow"
    assert target.exists() is False


def test_register_nfcore_validation_writes_target_db(tmp_path: Path):
    target = tmp_path / "nfcore-validation-target.sqlite3"
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "nfcore"
    store = AgentStore(target)
    from morphic_agent.harvest.nfcore import harvest_nfcore_schema_file_to_registry

    harvest_nfcore_schema_file_to_registry(
        fixture_root / "minimal_nextflow_schema.json",
        store,
        modules_json_path=fixture_root / "minimal_modules.json",
    )
    run = store.create_workbench_run(
        "nfcore_demo_v1_2_3",
        {"input": str(fixture_root / "minimal_nextflow_schema.json"), "outdir": str(tmp_path / "results")},
        execution_location={"kind": "scheduler_temporal"},
    )
    manifest_path = tmp_path / "comparison.json"
    manifest_path.write_text(json.dumps(_nfcore_comparison_manifest("nfcore_demo_v1_2_3")), encoding="utf-8")

    payload = _run_json(
        "scripts/register_nfcore_validation.py",
        str(manifest_path),
        "--graph-id",
        "nfcore_demo_v1_2_3",
        "--run-id",
        run["run_id"],
        "--db",
        str(target),
    )

    assert payload["status"] == "registered"
    assert payload["mutated"] is True
    assert payload["validation_record"]["status"] == "passed"
    assert payload["run"]["latest_validation"]["validation_id"] == payload["validation_record"]["validation_id"]
    validations = AgentStore(target).list_workflow_validations(graph_id="nfcore_demo_v1_2_3")
    assert [item["validation_id"] for item in validations] == [payload["validation_record"]["validation_id"]]
    loaded_run = AgentStore(target).get_workbench_run(run["run_id"])
    assert loaded_run["validations"][0]["validation_id"] == payload["validation_record"]["validation_id"]


def test_nfcore_validation_matrix_reports_harvested_fixture(tmp_path: Path):
    target = tmp_path / "nfcore-matrix.sqlite3"
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "nfcore"
    store = AgentStore(target)
    from morphic_agent.harvest.nfcore import harvest_nfcore_schema_file_to_registry

    harvest_nfcore_schema_file_to_registry(
        fixture_root / "minimal_nextflow_schema.json",
        store,
        modules_json_path=fixture_root / "minimal_modules.json",
    )

    payload = _run_json(
        "scripts/nfcore_validation_matrix.py",
        "--db",
        str(target),
        "--out-root",
        str(tmp_path / "matrix-bundles"),
        "--execution-location",
        "local",
    )

    assert payload["status"] == "ok"
    assert payload["recipe_count"] == 1
    row = payload["recipes"][0]
    assert row["graph_id"] == "nfcore_demo_v1_2_3"
    assert row["schema_valid"] is True
    assert row["render_status"] == "rendered"
    assert row["preflight_status"] == "blocked"
    assert Path(row["bundle_path"]).is_dir()


def _nfcore_comparison_manifest(graph_id: str) -> dict:
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
        "comparisons": [{"comparison_kind": "file_sha256", "sha256": "abc"}],
    }
