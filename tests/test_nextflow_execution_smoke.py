"""Gated Nextflow execution smoke tests and manifest contract tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from morphic_agent.execution.nextflow import (
    NEXTFLOW_ARTIFACT_MANIFEST_SCHEMA,
    NEXTFLOW_EXECUTION_RESULT_SCHEMA,
    collect_nextflow_artifact_manifest,
    run_nextflow_bundle,
)
from nextflow_smoke_support import make_tiny_nextflow_bundle


def test_collect_nextflow_artifact_manifest_detects_standard_reports_and_outdir(tmp_path: Path):
    bundle = make_tiny_nextflow_bundle(tmp_path)
    (bundle / ".nextflow.log").write_text("log\n", encoding="utf-8")
    (bundle / "manifests" / "nextflow-report.html").write_text("<html>report</html>\n", encoding="utf-8")
    (bundle / "manifests" / "nextflow-timeline.html").write_text("<html>timeline</html>\n", encoding="utf-8")
    (bundle / "manifests" / "nextflow-trace.txt").write_text("task_id\tstatus\n", encoding="utf-8")
    (bundle / "results").mkdir()
    (bundle / "results" / "message.txt").write_text("hello\n", encoding="utf-8")

    manifest = collect_nextflow_artifact_manifest(bundle)

    assert manifest["schema"] == NEXTFLOW_ARTIFACT_MANIFEST_SCHEMA
    assert manifest["manifest_kind"] == "nextflow_outputs"
    roles = {item["role"] for item in manifest["files"]}
    assert {"nextflow_log", "nextflow_report", "nextflow_timeline", "nextflow_trace", "workflow_output"} <= roles
    by_name = {item["name"]: item for item in manifest["files"]}
    assert by_name["message.txt"]["relative_path"] == "results/message.txt"
    assert by_name["message.txt"]["viewable"] is True


def test_tiny_nextflow_bundle_runs_when_enabled(tmp_path: Path):
    if os.environ.get("MORPHIC_RUN_NEXTFLOW_EXECUTION") != "1":
        pytest.skip("set MORPHIC_RUN_NEXTFLOW_EXECUTION=1 to run local Nextflow smoke")
    if shutil.which("nextflow") is None:
        pytest.skip("nextflow is not available on PATH")

    bundle = make_tiny_nextflow_bundle(tmp_path)
    result = run_nextflow_bundle(
        bundle,
        execution_location_kind="server",
        timeout_seconds=120,
        env={"NXF_HOME": str(tmp_path / "nxf-home")},
    )

    assert result["schema"] == NEXTFLOW_EXECUTION_RESULT_SCHEMA
    assert result["status"] == "completed"
    assert result["returncode"] == 0
    assert (bundle / "execution_result.json").is_file()
    assert (bundle / "manifests" / "execution_artifacts.json").is_file()
    assert (bundle / "results" / "message.txt").read_text(encoding="utf-8").strip() == "hello from tiny nextflow smoke"
    assert any(item["role"] == "workflow_output" and item["name"] == "message.txt" for item in result["artifact_manifest"]["files"])
