"""Registry/search integration tests for local nf-core harvests."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from morphic_agent.harvest.nfcore import (
    harvest_nfcore_pipeline_path_to_registry,
    harvest_nfcore_schema_file_to_registry,
)
from morphic_agent.harvest.nfcore_validation import nfcore_reference_validation_record
from morphic_agent.registry.store import AgentStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"
SCHEMA_FIXTURE = FIXTURE_ROOT / "minimal_nextflow_schema.json"
MODULES_FIXTURE = FIXTURE_ROOT / "minimal_modules.json"


def test_nfcore_schema_import_writes_module_and_graph_records(tmp_path: Path):
    store = AgentStore(tmp_path / "nfcore.sqlite3")

    result = harvest_nfcore_schema_file_to_registry(
        SCHEMA_FIXTURE,
        store,
        modules_json_path=MODULES_FIXTURE,
    )

    manifest = result.import_manifest
    assert manifest["schema"] == "morphic.harvest.nfcore_registry_import/v0"
    assert manifest["status"] == "ok"
    assert manifest["module_id"] == "nfcore_demo"
    assert manifest["graph_id"] == "nfcore_demo_v1_2_3"
    assert manifest["module_import"]["module_count"] == 1
    assert manifest["graph_import"]["graph_id"] == "nfcore_demo_v1_2_3"

    module = store.get_module_contract("nfcore_demo")
    graph = store.get_subgraph("nfcore_demo_v1_2_3")

    assert module is not None
    assert module["runtime"]["kind"] == "nfcore_pipeline"
    assert module["source_manifest"]["schema_hash"].startswith("sha256:")
    assert graph is not None
    assert graph["suite"] == "nf-core"
    assert graph["materialization_status"] == "runnable_nextflow_bundle"
    assert graph["params_schema"]["required"] == ["input", "outdir"]


def test_harvested_nfcore_graph_is_searchable_by_expected_facets(tmp_path: Path):
    store = AgentStore(tmp_path / "nfcore-search.sqlite3")
    harvest_nfcore_schema_file_to_registry(
        SCHEMA_FIXTURE,
        store,
        modules_json_path=MODULES_FIXTURE,
    )

    by_name = store.search_graphs(query="nf-core demo")
    assert [item["graph_id"] for item in by_name["results"]] == ["nfcore_demo_v1_2_3"]

    by_assay = store.search_graphs(filters={"assay_profile": "nfcore_demo"})
    assert [item["graph_id"] for item in by_assay["results"]] == ["nfcore_demo_v1_2_3"]

    by_modality = store.search_graphs(query="rna seq", filters={"modalities": ["rna"]})
    assert [item["graph_id"] for item in by_modality["results"]] == ["nfcore_demo_v1_2_3"]

    by_io = store.search_graphs(
        filters={
            "input_artifact_types": ["samplesheet"],
            "output_artifact_types": ["output_directory"],
        }
    )
    assert [item["graph_id"] for item in by_io["results"]] == ["nfcore_demo_v1_2_3"]

    by_capability = store.search_graphs(filters={"capabilities": ["nfcore_pipeline", "rna_seq"]})
    assert [item["graph_id"] for item in by_capability["results"]] == ["nfcore_demo_v1_2_3"]

    by_suite = store.search_graphs(query="nf-core", filters={"suite": "nf-core", "recipe_family": "nf-core"})
    assert [item["graph_id"] for item in by_suite["results"]] == ["nfcore_demo_v1_2_3"]


def test_nextflow_bundle_graphs_are_not_runnable_until_renderer_is_available(tmp_path: Path):
    store = AgentStore(tmp_path / "nfcore-runnable.sqlite3")
    result = harvest_nfcore_schema_file_to_registry(
        SCHEMA_FIXTURE,
        store,
        modules_json_path=MODULES_FIXTURE,
    )

    pending = store.search_graphs(filters={"runnable_only": True})
    assert pending["results"] == []

    ready_graph = copy.deepcopy(result.harvest_result.workflow_graph)
    ready_graph["execution_policy"]["bundle_renderer"] = "available"
    store.record_subgraph(ready_graph, version="nfcore-bundle-renderer-ready")

    ready = store.search_graphs(filters={"runnable_only": True, "materialization_status": "runnable_nextflow_bundle"})
    assert [item["graph_id"] for item in ready["results"]] == ["nfcore_demo_v1_2_3"]
    assert ready["results"][0]["runnable"] is True


def test_local_nfcore_pipeline_path_import_uses_nextflow_schema_and_optional_modules_json(tmp_path: Path):
    pipeline_dir = tmp_path / "nfcore-demo"
    pipeline_dir.mkdir()
    (pipeline_dir / "nextflow_schema.json").write_text(SCHEMA_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (pipeline_dir / "modules.json").write_text(MODULES_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    store = AgentStore(tmp_path / "nfcore-local.sqlite3")

    result = harvest_nfcore_pipeline_path_to_registry(pipeline_dir, store)

    assert result.import_manifest["module_id"] == "nfcore_demo"
    assert result.import_manifest["source_manifest"]["schema_path"] == str(pipeline_dir / "nextflow_schema.json")
    assert result.import_manifest["source_manifest"]["modules_json_path"] == str(pipeline_dir / "modules.json")
    assert store.get_module_contract("nfcore_demo") is not None
    assert store.get_subgraph("nfcore_demo_v1_2_3") is not None


def test_nfcore_reference_validation_records_are_searchable_by_expected_facets(tmp_path: Path):
    store = AgentStore(tmp_path / "nfcore-validation.sqlite3")
    result = harvest_nfcore_schema_file_to_registry(
        SCHEMA_FIXTURE,
        store,
        modules_json_path=MODULES_FIXTURE,
    )
    graph = result.harvest_result.workflow_graph
    source_manifest = graph["source_manifest"]
    comparison_manifest = {
        "schema": "morphic.nfcore_reference_nextflow_comparison/v0",
        "status": "passed",
        "comparator_kind": "reference_nextflow",
        "graph_id": graph["graph_id"],
        "source_manifest_hash": source_manifest["schema_hash"],
        "pipeline": "nf-core/demo",
        "release": "1.2.3",
        "profile": "docker",
        "fixture": {"fixture_id": "chr22", "sample_id": "SRR4422207_CHR22"},
        "reference": {
            "execution_location_kind": "server",
            "pipeline": "/cached/nf-core/demo",
            "profile": "docker",
        },
        "candidate": {
            "graph_id": graph["graph_id"],
            "execution_location_kind": "scheduler_temporal",
            "source_manifest_hash": source_manifest["schema_hash"],
        },
        "comparisons": [
            {"comparison_kind": "file_sha256", "reference_path": "ref.bam", "candidate_path": "candidate.bam"},
            {"comparison_kind": "salmon_meta_contract", "row_count": 1},
        ],
    }

    record = nfcore_reference_validation_record(comparison_manifest, graph=graph)
    stored = store.record_workflow_validation(record)

    assert stored["graph_id"] == "nfcore_demo_v1_2_3"
    assert stored["status"] == "passed"
    assert stored["validation_kind"] == "nfcore_reference_comparison"
    assert stored["comparator_kind"] == "reference_nextflow"
    assert stored["executor"] == "scheduler_temporal"
    assert stored["fixture_id"] == "chr22"
    assert stored["source_manifest_hash"] == source_manifest["schema_hash"]

    listed = store.list_workflow_validations(
        graph_id="nfcore_demo_v1_2_3",
        filters={"comparator_kind": "reference_nextflow", "fixture_id": "chr22"},
    )
    assert [item["validation_id"] for item in listed] == [stored["validation_id"]]

    by_validation = store.search_graphs(
        filters={
            "suite": "nf-core",
            "validated_only": True,
            "validation_status": "passed",
            "validation_kind": "nfcore_reference_comparison",
            "validation_comparator_kind": "reference_nextflow",
            "validation_executor": "scheduler_temporal",
            "validation_fixture": "chr22",
        }
    )
    assert [item["graph_id"] for item in by_validation["results"]] == ["nfcore_demo_v1_2_3"]
    assert by_validation["results"][0]["validated"] is True
    assert by_validation["results"][0]["latest_validation"]["validation_id"] == stored["validation_id"]

    no_match = store.search_graphs(filters={"validated_only": True, "validation_fixture": "full_grch38"})
    assert no_match["results"] == []


def test_nfcore_reference_validation_requires_reference_nextflow_evidence():
    with pytest.raises(ValueError, match="reference Nextflow section"):
        nfcore_reference_validation_record(
            {
                "schema": "morphic.nfcore_reference_nextflow_comparison/v0",
                "status": "passed",
                "comparator_kind": "reference_nextflow",
                "graph_id": "nfcore_demo_v1_2_3",
                "reference": {"execution_location_kind": "server", "profile": "docker"},
                "candidate": {"graph_id": "nfcore_demo_v1_2_3", "execution_location_kind": "scheduler_temporal"},
                "comparisons": [{"comparison_kind": "file_sha256", "sha256": "abc"}],
            }
        )
