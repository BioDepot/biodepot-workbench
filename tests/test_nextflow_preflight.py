"""Nextflow runtime diagnostic contract tests."""

from __future__ import annotations

from morphic_agent.execution.nextflow import (
    nextflow_artifact_candidate_paths,
    nextflow_launch_command,
    nextflow_runtime_preflight,
    workflow_source_check,
)


def test_nextflow_launch_command_preserves_nfcore_release_profile_and_params_file():
    command = nextflow_launch_command(
        pipeline="nf-core/demo",
        release="1.2.3",
        profile="docker",
        params_file="nf-params.json",
    )

    assert command == "nextflow run nf-core/demo -r 1.2.3 -profile docker -params-file nf-params.json"


def test_nextflow_launch_command_does_not_add_release_for_local_workflow_path():
    command = nextflow_launch_command(
        pipeline="./workflow",
        release="1.2.3",
        profile="docker",
        params_file="nf-params.json",
    )

    assert command == "nextflow run ./workflow -profile docker -params-file nf-params.json"


def test_nextflow_preflight_reports_missing_host_runtime_without_traceback(monkeypatch):
    monkeypatch.setenv("PATH", "")

    result = nextflow_runtime_preflight(
        pipeline="nf-core/demo",
        release="1.2.3",
        profile="docker",
        execution_location_kind="server",
    )

    assert result["schema"] == "morphic.nextflow_preflight/v0"
    assert result["status"] == "blocked"
    assert "nextflow is not available on PATH" in result["blockers"]
    assert "selected profile `docker` requires `docker` on PATH" in result["blockers"]
    assert not any(check.get("command") == "java" for check in result["checks"])
    assert result["launch_command"] == "nextflow run nf-core/demo -r 1.2.3 -profile docker -params-file nf-params.json"


def test_nextflow_preflight_local_execution_leaves_runtime_checks_to_caller(monkeypatch):
    monkeypatch.setenv("PATH", "")

    result = nextflow_runtime_preflight(
        pipeline="nf-core/demo",
        release="1.2.3",
        profile="docker",
        execution_location_kind="local",
    )

    assert result["status"] == "ready"
    assert result["blockers"] == []
    assert {check["status"] for check in result["checks"] if "caller-managed" in check["check"]} == {"not_run"}


def test_workflow_source_check_fails_for_missing_local_workflow_path(tmp_path):
    missing = tmp_path / "workflow"

    result = workflow_source_check(str(missing))

    assert result["status"] == "fail"
    assert result["path"] == str(missing)
    assert "does not exist" in result["blocker"]


def test_nextflow_artifact_candidates_include_standard_reports_and_outdir(tmp_path):
    bundle = tmp_path / "bundle"
    params = {"outdir": "results", "publish_dir": str(tmp_path / "published")}

    paths = nextflow_artifact_candidate_paths(bundle, params)

    assert bundle / ".nextflow.log" in paths
    assert bundle / "manifests" / "nextflow-report.html" in paths
    assert bundle / "manifests" / "nextflow-timeline.html" in paths
    assert bundle / "manifests" / "nextflow-trace.txt" in paths
    assert bundle / "results" in paths
    assert tmp_path / "published" in paths
