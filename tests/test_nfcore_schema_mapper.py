"""Focused tests for deterministic local nf-core schema harvesting."""

from __future__ import annotations

import json
from pathlib import Path

from morphic_agent.graph.params import validate_graph_params
from morphic_agent.harvest.nfcore_mapper import map_nextflow_schema
from morphic_agent.harvest.nfcore_schema import parse_nextflow_schema
from morphic_agent.registry.store import AgentStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _mapped():
    return map_nextflow_schema(
        parse_nextflow_schema(_load_json("minimal_nextflow_schema.json")),
        modules_json=_load_json("minimal_modules.json"),
        provenance={
            "schema_path": "tests/fixtures/nfcore/minimal_nextflow_schema.json",
            "modules_json_path": "tests/fixtures/nfcore/minimal_modules.json",
        },
    )


def _field(params_schema: dict, name: str) -> dict:
    return next(field for field in params_schema["fields"] if field["name"] == name)


def _binding(result, name: str) -> dict:
    return next(binding for binding in result.path_binding_candidates if binding["param"] == name)


def test_required_params_are_collected_from_nfcore_groups():
    result = _mapped()

    assert result.params_schema["required"] == ["input", "outdir"]
    assert _field(result.params_schema, "input")["required"] is True
    assert _field(result.params_schema, "outdir")["required"] is True

    validation = validate_graph_params(result.workflow_graph, {"outdir": "results"})
    assert validation["valid"] is False
    assert validation["missing_required_inputs"] == ["input"]


def test_grouped_params_are_preserved_with_advanced_classification():
    result = _mapped()
    groups = {group["id"]: group for group in result.params_schema["groups"]}

    assert list(groups) == ["input_output_options", "reference_genome_options", "advanced_options"]
    assert groups["input_output_options"]["fields"] == ["aligner", "input", "outdir"]
    assert groups["reference_genome_options"]["fields"] == [
        "bed",
        "bwa_index",
        "fasta",
        "gtf",
        "igenomes_base",
        "star_index",
    ]
    assert groups["advanced_options"]["advanced"] is True
    assert _field(result.params_schema, "max_cpus")["advanced"] is True


def test_enum_default_and_numeric_constraints_are_preserved():
    result = _mapped()
    aligner = _field(result.params_schema, "aligner")
    profile = _field(result.params_schema, "profile")
    max_cpus = _field(result.params_schema, "max_cpus")

    assert aligner["default"] == "star_salmon"
    assert aligner["enum"] == ["star_salmon", "hisat2"]
    assert aligner["choices"] == ["star_salmon", "hisat2"]
    assert profile["default"] == "docker"
    assert profile["choices"] == ["docker", "singularity", "conda"]
    assert max_cpus["default"] == 16
    assert max_cpus["minimum"] == 1


def test_path_binding_candidates_detect_nfcore_path_like_params():
    result = _mapped()
    by_name = {binding["param"]: binding for binding in result.path_binding_candidates}

    assert set(by_name) == {
        "bed",
        "bwa_index",
        "fasta",
        "gtf",
        "igenomes_base",
        "input",
        "outdir",
        "star_index",
    }
    assert by_name["input"]["role"] == "input"
    assert by_name["input"]["exists"] is True
    assert by_name["outdir"]["role"] == "output"
    assert by_name["outdir"]["path_kind"] == "directory"
    assert by_name["fasta"]["artifact_type"] == "fasta"
    assert by_name["gtf"]["artifact_type"] == "gtf"
    assert by_name["bed"]["artifact_type"] == "bed"
    assert by_name["star_index"]["path_kind"] == "directory"
    assert by_name["bwa_index"]["path_kind"] == "directory"
    assert by_name["igenomes_base"]["artifact_type"] == "reference_data_root"


def test_samplesheet_input_and_outdir_become_workbench_artifact_contracts():
    result = _mapped()
    module = result.module_contract
    inputs = {item["name"]: item for item in module["inputs"]}
    outputs = {item["name"]: item for item in module["outputs"]}

    assert _field(result.params_schema, "input")["type"] == "path"
    assert _field(result.params_schema, "input")["artifact_type"] == "samplesheet"
    assert inputs["input"]["artifact_type"] == "samplesheet"
    assert inputs["input"]["structured_artifact"] == {
        "kind": "samplesheet",
        "schema_path": "assets/schema_input.json",
    }
    assert outputs["outdir"]["artifact_type"] == "output_directory"
    assert _binding(result, "outdir")["default"] == "results"


def test_module_contract_and_single_node_graph_are_workbench_compatible(tmp_path: Path):
    result = _mapped()
    module = result.module_contract
    graph = result.workflow_graph

    assert module["module_id"] == "nfcore_demo"
    assert module["title"] == "nf-core/demo"
    assert module["runtime"]["kind"] == "nfcore_pipeline"
    assert module["runtime"]["release"] == "1.2.3"
    assert module["runtime"]["git_url"] == "https://github.com/nf-core/demo"
    assert module["runtime"]["git_sha"] == "abc123def456"
    assert module["source_manifest"]["schema_hash"].startswith("sha256:")
    assert module["source_manifest"]["modules_json_hash"].startswith("sha256:")

    assert graph["graph_id"] == "nfcore_demo_v1_2_3"
    assert graph["nodes"] == [
        {
            "id": "nfcore_pipeline",
            "kind": "module",
            "module_id": "nfcore_demo",
            "label": "nf-core/demo",
            "confidence_tier": "upstream_declared",
        }
    ]
    assert graph["edges"] == []
    assert graph["materialization_status"] == "runnable_nextflow_bundle"
    assert graph["confidence_tier"] == "upstream_declared"
    assert graph["params_schema"]["graph_id"] == graph["graph_id"]

    store = AgentStore(tmp_path / "nfcore.sqlite3")
    import_result = store.import_module_catalog({"schema": "morphic.module_catalog/v0", "modules": [module]})
    graph_result = store.record_subgraph(graph, version="nfcore-fixture")

    assert import_result["module_count"] == 1
    assert graph_result["graph_id"] == graph["graph_id"]
    assert store.get_module_contract("nfcore_demo")["module_id"] == "nfcore_demo"
    assert store.get_subgraph("nfcore_demo_v1_2_3")["graph_id"] == "nfcore_demo_v1_2_3"


def test_unsupported_schema_constructs_are_preserved_in_extras():
    result = _mapped()
    custom_selector = _field(result.params_schema, "custom_selector")
    extras = result.module_contract["extras"]

    assert "oneOf" in custom_selector["extras"]["unsupported_schema"]
    assert custom_selector["extras"]["unsupported_schema"]["additionalProperties"] is False
    assert "dependentSchemas" in extras["nfcore_schema"]["unsupported_top_level"]
    assert "unexpected_root_construct" in extras["nfcore_schema"]["unsupported_top_level"]
    assert extras["modules_json"]["installed_modules"] == [
        {
            "git_sha": "111aaa",
            "name": "nf-core/fastqc",
            "repository": "https://github.com/nf-core/modules.git",
        },
        {
            "git_sha": "222bbb",
            "name": "nf-core/multiqc",
            "repository": "https://github.com/nf-core/modules.git",
        },
    ]
