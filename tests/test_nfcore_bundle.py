"""Bundle rendering tests for nf-core pipeline graphs."""

from __future__ import annotations

import json
from pathlib import Path

from morphic_agent.bundle.nfcore_pipeline import (
    materialize_nfcore_pipeline_bundle,
    normalize_nfcore_params,
    preflight_nfcore_bundle,
)
from morphic_agent.harvest.nfcore_mapper import map_nextflow_schema
from morphic_agent.harvest.nfcore_schema import parse_nextflow_schema
from morphic_agent.tools.bundle import BundleTools


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"


class FakeGraphTools:
    def __init__(self, graph: dict) -> None:
        self.graph = graph

    def get_graph(self, graph_id: str) -> dict | None:
        return self.graph if graph_id == self.graph["graph_id"] else None


def _load_json(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _mapped_graph() -> dict:
    return map_nextflow_schema(
        parse_nextflow_schema(_load_json("minimal_nextflow_schema.json")),
        modules_json=_load_json("minimal_modules.json"),
        provenance={
            "schema_path": "tests/fixtures/nfcore/minimal_nextflow_schema.json",
            "modules_json_path": "tests/fixtures/nfcore/minimal_modules.json",
        },
    ).workflow_graph


def _params(tmp_path: Path) -> dict:
    samplesheet = tmp_path / "samplesheet.csv"
    samplesheet.write_text("sample,fastq_1,fastq_2\nS1,S1_R1.fastq.gz,S1_R2.fastq.gz\n", encoding="utf-8")
    return {
        "input": str(samplesheet),
        "outdir": str(tmp_path / "results"),
    }


def test_nfcore_bundle_renderer_writes_reviewable_nextflow_artifacts(tmp_path: Path):
    graph = _mapped_graph()
    params = _params(tmp_path)

    bundle = materialize_nfcore_pipeline_bundle(graph, tmp_path / "bundles", params=params)

    assert (bundle / "nf-params.json").is_file()
    assert (bundle / "run.nextflow.sh").is_file()
    assert (bundle / "run.sh").is_file()
    assert (bundle / "workflow_graph.json").is_file()
    assert (bundle / "params.schema.json").is_file()
    assert (bundle / "params.review.json").is_file()
    assert (bundle / "manifests" / "path_bindings.json").is_file()
    assert (bundle / "manifests" / "path_binding_candidates.json").is_file()
    assert (bundle / "manifests" / "container.json").is_file()
    assert (bundle / "manifests" / "source_manifest.json").is_file()

    nf_params = json.loads((bundle / "nf-params.json").read_text(encoding="utf-8"))
    assert nf_params["input"] == params["input"]
    assert nf_params["outdir"] == params["outdir"]
    assert nf_params["aligner"] == "star_salmon"
    assert nf_params["profile"] == "docker"
    assert "fasta" not in nf_params

    run_script = (bundle / "run.nextflow.sh").read_text(encoding="utf-8")
    assert "nextflow run" in run_script
    assert "nf-core/demo" in run_script
    assert "-with-trace" in run_script
    assert "-with-report" in run_script
    assert "-with-timeline" in run_script
    assert "-params-file" in run_script

    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert bindings["input"]["role"] == "input"
    assert bindings["input"]["path"] == params["input"]
    assert bindings["outdir"]["role"] == "output"

    container = json.loads((bundle / "manifests" / "container.json").read_text(encoding="utf-8"))
    assert container["schema"] == "morphic.nfcore_container_manifest/v0"
    assert container["container_authority"] == "nf-core/nextflow profile"
    assert container["selected_profile"] == "docker"


def test_nfcore_scheduler_temporal_bundle_writes_temporal_contract(tmp_path: Path):
    graph = _mapped_graph()
    params = _params(tmp_path)

    bundle = materialize_nfcore_pipeline_bundle(
        graph,
        tmp_path / "bundles",
        params=params,
        execution_location="scheduler_temporal",
    )

    temporal_config = bundle / "manifests" / "nextflow-temporal.config"
    command_manifest = bundle / "manifests" / "nextflow_scheduler_command.json"
    assert temporal_config.is_file()
    assert command_manifest.is_file()
    assert "executor = 'temporal'" in temporal_config.read_text(encoding="utf-8")

    command = json.loads(command_manifest.read_text(encoding="utf-8"))
    assert command["schema"] == "morphic.nextflow_scheduler_command/v0"
    assert command["execution_location_kind"] == "scheduler_temporal"
    assert command["scheduler"]["kind"] == "temporal"
    assert command["command"] == ["bash", "run.nextflow.sh", "-c", str(temporal_config)]

    run_script = (bundle / "run.nextflow.sh").read_text(encoding="utf-8")
    assert "NEXTFLOW_BIN" in run_script
    assert "NEXTFLOW_CONFIG_FILE" in run_script
    assert "nextflow-temporal.config" in run_script


def test_nfcore_preflight_reports_runtime_blockers_without_executing(tmp_path: Path):
    graph = _mapped_graph()
    params = _params(tmp_path)
    bundle = materialize_nfcore_pipeline_bundle(graph, tmp_path / "bundles", params=params)

    preflight = preflight_nfcore_bundle(graph, params, bundle_dir=bundle, execution_location_kind="server")

    assert preflight["schema"] == "morphic.nfcore_preflight_result/v0"
    assert preflight["graph_id"] == "nfcore_demo_v1_2_3"
    assert preflight["validation"]["valid"] is True
    assert any(check["check"] == "nf-params.json is valid JSON" and check["status"] == "pass" for check in preflight["checks"])
    assert any(check["check"] == "nextflow available" for check in preflight["checks"])
    assert preflight["launch_command"] == "nextflow run nf-core/demo -r 1.2.3 -profile docker -params-file nf-params.json"


def test_nfcore_scheduler_temporal_preflight_includes_temporal_executor_checks(tmp_path: Path, monkeypatch):
    graph = _mapped_graph()
    params = _params(tmp_path)
    bundle = materialize_nfcore_pipeline_bundle(
        graph,
        tmp_path / "bundles",
        params=params,
        execution_location="scheduler_temporal",
    )
    source_root = tmp_path / "nextflow-source"
    (source_root / "plugins" / "nf-temporal" / "build" / "libs").mkdir(parents=True)
    (source_root / "plugins" / "nf-temporal" / "build" / "target" / "libs").mkdir(parents=True)
    (source_root / "plugins" / "nf-temporal" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (source_root / "plugins" / "nf-temporal" / "build" / "libs" / "nf-temporal-0.1.0.jar").write_bytes(b"jar")
    (source_root / "plugins" / "nf-temporal" / "build" / "target" / "libs" / "dep.jar").write_bytes(b"jar")
    (source_root / "gradlew").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (source_root / "nextflow").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setenv("MORPHIC_NEXTFLOW_SOURCE_ROOT", str(source_root))

    preflight = preflight_nfcore_bundle(
        graph,
        params,
        bundle_dir=bundle,
        execution_location_kind="scheduler_temporal",
    )

    assert any(check["check"] == "bundle contains manifests/nextflow-temporal.config" and check["status"] == "pass" for check in preflight["checks"])
    assert any(check["check"] == "local Nextflow source root with nf-temporal" and check["status"] == "pass" for check in preflight["checks"])
    assert any(check["check"] == "local nf-temporal plugin install source" and check["status"] == "pass" for check in preflight["checks"])
    assert any(check["check"] == "Temporal gRPC target reachable" and check["status"] == "not_run" for check in preflight["checks"])


def test_bundle_tools_materializes_nfcore_review_bundle(tmp_path: Path):
    graph = _mapped_graph()
    params = _params(tmp_path)
    tools = BundleTools(graph_tools=FakeGraphTools(graph))

    response = tools.render_bundle(
        graph["graph_id"],
        params,
        out_root=tmp_path / "bundles",
        execution_location="server",
    )

    assert response.status == "materialized"
    payload = response.payload
    bundle = Path(payload["bundle_path"])
    assert payload["workflow_graph"]["graph_id"] == graph["graph_id"]
    assert payload["execution_readiness"] in {"blocked", "preflight_passed", "executable_ready"}
    assert payload["path_bindings_path"] == "manifests/path_bindings.json"
    assert payload["container_manifest_path"] == "manifests/container.json"
    assert (bundle / "nf-params.json").is_file()

    preflight = tools.preflight_bundle(
        graph["graph_id"],
        bundle_path=bundle,
        execution_location="server",
    )
    assert preflight.status in {"blocked", "preflight_passed"}
    assert preflight.payload["graph_id"] == graph["graph_id"]


def test_nfcore_params_normalization_is_deterministic_and_omits_null_optionals(tmp_path: Path):
    graph = _mapped_graph()
    normalized = normalize_nfcore_params(graph, _params(tmp_path))

    assert list(normalized) == [
        "aligner",
        "input",
        "outdir",
        "max_cpus",
        "profile",
    ]
    assert normalized["aligner"] == "star_salmon"
    assert normalized["max_cpus"] == 16
