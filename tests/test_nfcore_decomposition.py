"""Source-level nf-core decomposition contract tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.harvest.nfcore import harvest_nfcore_pipeline_path_to_registry
from morphic_agent.harvest.nfcore_decomposition import decompose_nfcore_pipeline
from morphic_agent.registry.store import AgentStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"
PIPELINE_FIXTURE = FIXTURE_ROOT / "decomposition_pipeline"


def test_decomposition_indexes_files_aliases_calls_and_metadata() -> None:
    result = decompose_nfcore_pipeline(PIPELINE_FIXTURE)

    assert result["status"] == "decomposed"
    assert result["summary"] == {
        "source_file_count": 6,
        "reachable_source_file_count": 6,
        "unreachable_source_file_count": 0,
        "node_count": 13,
        "edge_count": 18,
        "node_counts": {
            "module_source": 3,
            "pipeline_source": 1,
            "plugin_symbol": 1,
            "process": 3,
            "subworkflow": 1,
            "subworkflow_source": 1,
            "workflow": 2,
            "workflow_source": 1,
        },
        "edge_counts": {"declares": 6, "includes": 6, "invokes": 6},
        "include_count": 6,
        "unresolved_include_count": 0,
        "metadata_file_count": 2,
    }
    assert result["execution_boundary"]["decomposed_components_independently_runnable"] is False
    assert result["decomposer"]["executes_workflow"] is False

    workflow = _file(result, "workflows/demo/main.nf")
    count_include = next(
        symbol
        for include in workflow["includes"]
        for symbol in include["symbols"]
        if symbol["alias"] == "COUNT_SAMPLE"
    )
    assert count_include["symbol"] == "COUNTS"
    assert count_include["resolution"] == "declaration"
    demo = next(item for item in workflow["declarations"] if item["name"] == "DEMO")
    assert [call["symbol"] for call in demo["calls"]] == ["PREPARE", "COUNT_SAMPLE", "FASTQC"]

    fastqc = _file(result, "modules/nf-core/fastqc/main.nf")
    assert fastqc["metadata"]["name"] == "fastqc"
    assert fastqc["modules_registry"]["git_sha"] == "abc123"


def test_decomposition_is_deterministic_and_does_not_embed_source_text() -> None:
    first = decompose_nfcore_pipeline(PIPELINE_FIXTURE)
    second = decompose_nfcore_pipeline(PIPELINE_FIXTURE)

    assert first == second
    encoded = json.dumps(first, sort_keys=True)
    assert "touch counts.tsv" not in encoded
    assert first["source_manifest"]["source_index_hash"].startswith("sha256:")


def test_strict_decomposition_rejects_unresolved_local_include(tmp_path: Path) -> None:
    (tmp_path / "main.nf").write_text(
        "include { MISSING } from './modules/local/missing'\nworkflow { MISSING() }\n",
        encoding="utf-8",
    )

    non_strict = decompose_nfcore_pipeline(tmp_path)
    assert non_strict["status"] == "decomposed_with_unresolved_includes"
    assert non_strict["summary"]["unresolved_include_count"] == 1
    with pytest.raises(ValueError, match="1 unresolved includes"):
        decompose_nfcore_pipeline(tmp_path, strict=True)


def test_strict_decomposition_rejects_missing_symbol_in_existing_source(tmp_path: Path) -> None:
    module = tmp_path / "modules" / "local" / "demo"
    module.mkdir(parents=True)
    (module / "main.nf").write_text("process PRESENT { }\n", encoding="utf-8")
    (tmp_path / "main.nf").write_text(
        "include { ABSENT } from './modules/local/demo'\nworkflow { ABSENT() }\n",
        encoding="utf-8",
    )

    result = decompose_nfcore_pipeline(tmp_path)
    assert result["unresolved"][0]["kind"] == "include_symbol_not_found"
    with pytest.raises(ValueError, match="1 unresolved includes"):
        decompose_nfcore_pipeline(tmp_path, strict=True)


def test_plugin_reachability_tracks_the_including_source(tmp_path: Path) -> None:
    (tmp_path / "main.nf").write_text("workflow { }\n", encoding="utf-8")
    (tmp_path / "unused.nf").write_text(
        "include { unusedHelp } from 'plugin/nf-schema'\nworkflow UNUSED { unusedHelp() }\n",
        encoding="utf-8",
    )

    result = decompose_nfcore_pipeline(tmp_path)
    plugin = next(node for node in result["nodes"] if node["kind"] == "plugin_symbol")

    assert result["summary"]["unreachable_source_file_count"] == 1
    assert plugin["reachable_from_entrypoint"] is False


def test_local_pipeline_harvest_attaches_decomposition_to_runnable_wrapper(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline"
    shutil.copytree(PIPELINE_FIXTURE, pipeline)
    shutil.copy2(FIXTURE_ROOT / "minimal_nextflow_schema.json", pipeline / "nextflow_schema.json")
    store = AgentStore(tmp_path / "registry.sqlite3")

    imported = harvest_nfcore_pipeline_path_to_registry(pipeline, store)
    graph = imported.harvest_result.workflow_graph

    assert imported.import_manifest["decomposition"]["status"] == "decomposed"
    assert graph["lifecycle_state"] == "source_decomposed"
    assert graph["nodes"][0]["id"] == "nfcore_pipeline"
    assert graph["nodes"][0]["execution_boundary"] is True
    assert graph["decomposition"]["summary"]["source_file_count"] == 6
    assert graph["decomposition"]["files"][0]["path"] == "main.nf"
    assert len(graph["decomposition"]["nodes"]) == 13
    assert len(graph["decomposition"]["edges"]) == 18
    assert graph["runtime"]["local_pipeline_path"] == str(pipeline.resolve())
    assert graph["runtime"]["workflow_path_override_env"] == "NFCORE_WORKFLOW_PATH"
    assert graph["runtime"]["default_launch_target"] == "upstream_pipeline_reference"
    assert len(store.get_subgraph(graph["graph_id"])["nodes"]) == 1


def test_nfcore_decomposition_http_endpoint_is_read_only(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "api.sqlite3")
    client = TestClient(app)

    response = client.post("/api/nfcore/decompose", json={"pipeline_path": str(PIPELINE_FIXTURE)})

    assert response.status_code == 200
    assert response.json()["summary"]["source_file_count"] == 6
    assert client.get("/api/nfcore/pipelines").json()["results"] == []


def test_nfcore_decomposition_cli_writes_full_and_graph_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "decomposition.json"
    graph_output = tmp_path / "component_graph.json"

    process = subprocess.run(
        [
            sys.executable,
            "scripts/decompose_nfcore_pipeline.py",
            str(PIPELINE_FIXTURE),
            "--summary",
            "--output",
            str(output),
            "--graph-output",
            str(graph_output),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["summary"]["source_file_count"] == 6
    assert json.loads(output.read_text(encoding="utf-8"))["files"][0]["path"] == "main.nf"
    assert json.loads(graph_output.read_text(encoding="utf-8"))["schema"] == "morphic.nfcore_component_graph/v0"


def test_nfcore_collection_cli_discovers_checkouts_and_writes_manifest(tmp_path: Path) -> None:
    collection = tmp_path / "checkouts"
    pipeline = collection / "demo"
    shutil.copytree(PIPELINE_FIXTURE, pipeline)
    shutil.copy2(FIXTURE_ROOT / "minimal_nextflow_schema.json", pipeline / "nextflow_schema.json")
    out_root = tmp_path / "artifacts"

    process = subprocess.run(
        [
            sys.executable,
            "scripts/decompose_nfcore_collection.py",
            str(collection),
            "--out-root",
            str(out_root),
            "--strict",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pipeline_count"] == 1
    assert manifest["error_count"] == 0
    artifact_dir = Path(manifest["results"][0]["artifact_dir"])
    assert (artifact_dir / "decomposition.json").is_file()
    assert (artifact_dir / "component_graph.json").is_file()


def test_nfcore_harvest_cli_dry_run_decomposes_local_checkout(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline"
    shutil.copytree(PIPELINE_FIXTURE, pipeline)
    shutil.copy2(FIXTURE_ROOT / "minimal_nextflow_schema.json", pipeline / "nextflow_schema.json")

    process = subprocess.run(
        [
            sys.executable,
            "scripts/harvest_nfcore_pipeline.py",
            str(pipeline),
            "--dry-run",
            "--strict-decomposition",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    payload = json.loads(process.stdout)
    assert payload["mutated"] is False
    assert payload["decomposition"]["status"] == "decomposed"
    assert payload["decomposition"]["summary"]["source_file_count"] == 6


def _file(result: dict, path: str) -> dict:
    return next(item for item in result["files"] if item["path"] == path)
