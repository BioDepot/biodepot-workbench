"""Scheduler-facing Nextflow smoke harness tests."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from morphic_agent.execution.nextflow import (
    NEXTFLOW_SCHEDULER_COMMAND_SCHEMA,
    nextflow_scheduler_command_manifest,
    nextflow_temporal_env,
    run_nextflow_bundle,
    start_local_nextflow_temporal_worker,
)
from nextflow_smoke_support import (
    DEFAULT_NEXTFLOW_SOURCE_ROOT,
    FIXTURE_ROOT,
    install_local_nf_temporal_plugin,
    local_nextflow_binary,
    make_tiny_nextflow_bundle,
)


def test_nextflow_scheduler_command_manifest_is_temporal_ready(tmp_path: Path):
    bundle = make_tiny_nextflow_bundle(tmp_path)
    config = FIXTURE_ROOT / "tiny_temporal.config"

    manifest = nextflow_scheduler_command_manifest(
        bundle,
        execution_location_kind="scheduler_temporal",
        temporal_config_path=config,
        temporal_target="127.0.0.1:7233",
        namespace="default",
        task_queue="nextflow",
    )

    assert manifest["schema"] == NEXTFLOW_SCHEDULER_COMMAND_SCHEMA
    assert manifest["graph_id"] == "tiny_nextflow_smoke_v0"
    assert manifest["execution_location_kind"] == "scheduler_temporal"
    assert manifest["scheduler"] == {
        "kind": "temporal",
        "target": "127.0.0.1:7233",
        "namespace": "default",
        "task_queue": "nextflow",
    }
    assert manifest["command"] == ["bash", "run.nextflow.sh", "-c", str(config)]
    assert manifest["params_hash"] == "sha256:test"


def test_tiny_nextflow_temporal_scheduler_smoke_when_enabled(tmp_path: Path):
    if os.environ.get("MORPHIC_RUN_NEXTFLOW_SCHEDULER") != "1":
        pytest.skip("set MORPHIC_RUN_NEXTFLOW_SCHEDULER=1 to run Temporal-backed Nextflow smoke")
    if shutil.which("nextflow") is None:
        pytest.skip("nextflow is not available on PATH")

    source_root = Path(os.environ.get("MORPHIC_NEXTFLOW_SOURCE_ROOT", str(DEFAULT_NEXTFLOW_SOURCE_ROOT))).expanduser()
    if not (source_root / "gradlew").is_file():
        pytest.skip(f"local Nextflow source root with nf-temporal worker is not available: {source_root}")
    nxf_home = tmp_path / "nxf-home"
    plugin_dir = install_local_nf_temporal_plugin(nxf_home, source_root)
    if plugin_dir is None:
        pytest.skip(f"local nf-temporal plugin build/cache is not available under {source_root}")

    temporal_target = os.environ.get("MORPHIC_NEXTFLOW_TEMPORAL_TARGET", "127.0.0.1:7233")
    if not _tcp_open(temporal_target, timeout_seconds=1.0):
        pytest.skip(f"Temporal server is not reachable at {temporal_target}")

    bundle = make_tiny_nextflow_bundle(tmp_path)
    config = FIXTURE_ROOT / "tiny_temporal.config"
    namespace = os.environ.get("MORPHIC_NEXTFLOW_TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("MORPHIC_NEXTFLOW_TEMPORAL_TASK_QUEUE", "nextflow")
    worker_log = tmp_path / "temporal-worker.log"
    worker = start_local_nextflow_temporal_worker(
        source_root=source_root,
        worker_log=worker_log,
        temporal_target=temporal_target,
        namespace=namespace,
        task_queue=task_queue,
    )
    try:
        result = run_nextflow_bundle(
            bundle,
            execution_location_kind="scheduler_temporal",
            timeout_seconds=180,
            env={
                **nextflow_temporal_env(
                    nxf_home=nxf_home,
                    temporal_config_path=config,
                    source_root=source_root,
                    temporal_target=temporal_target,
                    namespace=namespace,
                    task_queue=task_queue,
                ),
            },
        )
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=10)

    assert result["status"] == "completed", result["stdout_tail"] + result["stderr_tail"]
    assert result["execution_location_kind"] == "scheduler_temporal"
    assert (bundle / "results" / "message.txt").is_file()


def _tcp_open(target: str, *, timeout_seconds: float) -> bool:
    host, _, port_text = target.rpartition(":")
    if not host or not port_text:
        return False
    sock = socket.socket()
    sock.settimeout(timeout_seconds)
    try:
        sock.connect((host, int(port_text)))
    except OSError:
        return False
    finally:
        sock.close()
    return True
