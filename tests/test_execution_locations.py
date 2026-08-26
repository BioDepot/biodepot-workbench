"""Execution-location contracts for current and future run dispatch."""

from __future__ import annotations

import tempfile
import io
import importlib
import json
import shutil
import zipfile
from pathlib import Path

from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.execution import (
    execution_dispatch_for_location,
    execution_location_gate,
    list_execution_locations,
    resolve_execution_location,
)


def _client() -> TestClient:
    db = tempfile.mktemp(suffix=".sqlite3")
    return TestClient(create_app(db_path=db))


def test_execution_location_resolver_preserves_production_server_alias():
    location = resolve_execution_location("production")

    assert location.location_id == "server"
    assert location.kind == "server"
    assert "execute" in location.allowed_actions
    assert execution_location_gate(location).allowed is True
    assert execution_dispatch_for_location(location)["dispatch_kind"] == "server_subprocess"


def test_execution_location_resolver_models_local_as_caller_managed():
    location = resolve_execution_location("local")

    assert location.location_id == "local"
    assert location.kind == "local"
    assert execution_location_gate(location).allowed is False
    assert "caller-local bundle" in str(execution_location_gate(location).run_blocker)
    assert execution_dispatch_for_location(location)["dispatch_kind"] == "caller_managed_shell"


def test_execution_location_resolver_models_remote_as_not_directly_executable_and_scheduler_as_api_managed():
    remote = resolve_execution_location({"kind": "remote", "remote_host": "slurm-login"})
    temporal = resolve_execution_location({"kind": "temporal", "task_queue": "morphic-bwb"})

    assert remote.metadata["remote_host"] == "slurm-login"
    assert execution_location_gate(remote).allowed is False
    assert "Remote execution requires" in str(execution_location_gate(remote).run_blocker)
    assert execution_dispatch_for_location(remote)["dispatch_kind"] == "remote_connector"

    assert temporal.location_id == "scheduler_temporal"
    assert temporal.scheduler == "temporal"
    assert execution_location_gate(temporal).allowed is True
    assert execution_dispatch_for_location(temporal)["task_queue"] == "morphic-bwb"
    assert execution_dispatch_for_location(temporal)["direct_api_execution"] is True


def test_execution_location_resolver_models_remote_ssh_as_api_managed_dispatch():
    location = resolve_execution_location(
        {
            "location_id": "remote_ssh",
            "metadata": {
                "remote_host": "128.208.252.232",
                "remote_user": "lhhung",
                "remote_workdir": "/tmp/morphic-ssh/trimodal_qc_report_v0",
                "remote_container_runtime": "apptainer",
            },
        }
    )

    assert location.location_id == "remote_ssh"
    assert location.kind == "remote_ssh"
    assert execution_location_gate(location).allowed is True
    dispatch = execution_dispatch_for_location(location)
    assert dispatch["dispatch_kind"] == "ssh_remote_container"
    assert dispatch["direct_api_execution"] is True
    assert dispatch["remote_host"] == "128.208.252.232"
    assert dispatch["remote_workdir"] == "/tmp/morphic-ssh/trimodal_qc_report_v0"
    assert dispatch["command_hint"] == "./run.apptainer.sh"


def test_execution_location_resolver_blocks_remote_ssh_without_destination():
    location = resolve_execution_location("remote_ssh")

    gate = execution_location_gate(location)

    assert gate.allowed is False
    assert "remote_host" in str(gate.run_blocker)
    assert "remote_workdir" in str(gate.run_blocker)


def test_execution_location_resolver_models_scheduler_remote_ssh_as_api_managed_dispatch():
    location = resolve_execution_location(
        {
            "location_id": "scheduler_remote_ssh",
            "metadata": {
                "remote_host": "10.159.4.53",
                "remote_user": "lhhung",
                "remote_workdir": "/tmp/morphic-scheduler-ssh",
                "scheduler_api_url": "http://127.0.0.1:8000",
            },
        }
    )

    assert location.location_id == "scheduler_remote_ssh"
    assert location.kind == "scheduler_remote_ssh"
    assert execution_location_gate(location).allowed is True
    dispatch = execution_dispatch_for_location(location)
    assert dispatch["dispatch_kind"] == "temporal_ssh_docker_workflow"
    assert dispatch["direct_api_execution"] is True
    assert dispatch["remote_host"] == "10.159.4.53"
    assert dispatch["workflow_type"] == "RemoteDockerWorkflow"


def test_execution_location_resolver_blocks_scheduler_remote_ssh_without_destination():
    location = resolve_execution_location("scheduler_remote_ssh")

    gate = execution_location_gate(location)

    assert gate.allowed is False
    assert "remote_host" in str(gate.run_blocker)
    assert "remote_user" in str(gate.run_blocker)
    assert "remote_workdir" in str(gate.run_blocker)


def test_api_lists_execution_locations():
    client = _client()

    response = client.get("/api/execution/locations")

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "morphic.execution_locations/v0"
    assert body["default_location_id"] == "server"
    assert {item["location_id"] for item in body["locations"]} == {
        item["location_id"] for item in list_execution_locations()
    }


def test_remote_preflight_reports_location_gate_without_running():
    client = _client()

    response = client.post(
        "/api/star-mvp/preflight",
        json={
            "graph_id": "star_post_mex_h5ad_qc_v0",
            "params": {},
            "execution_location": {"kind": "remote", "remote_host": "slurm-login"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["execution_location"]["kind"] == "remote"
    assert body["execution_dispatch"]["dispatch_kind"] == "remote_connector"
    assert body["execution_dispatch"]["remote_host"] == "slurm-login"
    assert body["execution_run_gate"]["allowed"] is False
    assert body["executable_ready"] is False
    assert "Remote execution requires" in body["run_blocker"]


def _remote_ssh_location(tmp_path: Path) -> dict[str, object]:
    return {
        "location_id": "remote_ssh",
        "metadata": {
            "remote_host": "128.208.252.232",
            "remote_user": "lhhung",
            "remote_workdir": f"/tmp/morphic-ssh-tests/{tmp_path.name}/trimodal_qc_report_v0",
            "remote_container_runtime": "docker",
            "remote_check": False,
            "remote_path_overrides": {
                "mudata": "/remote/data/demo_trimodal_small.h5mu",
            },
        },
    }


def _scheduler_location(tmp_path: Path) -> dict[str, object]:
    return {
        "location_id": "scheduler_temporal",
        "metadata": {
            "scheduler_api_url": "http://127.0.0.1:18000",
            "scheduler_storage_dir": str(tmp_path / "scheduler-storage"),
            "scheduler_worker_queue": "worker1",
            "scheduler_worker_cpus": 2,
            "scheduler_worker_mem_mb": 4096,
            "scheduler_worker_gpus": 0,
        },
    }


def _scheduler_remote_ssh_location(tmp_path: Path) -> dict[str, object]:
    return {
        "location_id": "scheduler_remote_ssh",
        "metadata": {
            "scheduler_api_url": "http://127.0.0.1:18000",
            "scheduler_storage_dir": str(tmp_path / "scheduler-storage"),
            "remote_host": "10.159.4.53",
            "remote_user": "lhhung",
            "remote_workdir": f"/tmp/morphic-scheduler-ssh-tests/{tmp_path.name}",
            "remote_port": 22,
            "remote_container_runtime": "docker",
            "remote_check": False,
        },
    }


def _mock_scheduler_ready(monkeypatch):
    scheduler_module = importlib.import_module("morphic_agent.execution.scheduler")
    monkeypatch.setattr(
        scheduler_module,
        "_get_json",
        lambda url, timeout: {"openapi": "3.0.0", "paths": {"/start_ssh_docker_workflow": {}, "/ssh_docker_workflow_status": {}}},
    )
    monkeypatch.setattr(scheduler_module.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"docker", "ssh", "rsync"} else None)

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(scheduler_module.subprocess, "run", lambda *args, **kwargs: Result())


def test_remote_ssh_render_localizes_path_manifest(tmp_path: Path):
    client = _client()

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": _remote_ssh_location(tmp_path),
        },
    )

    assert response.status_code == 200
    body = response.json()
    bundle = Path(body["bundle_path"])
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert body["execution_location"]["kind"] == "remote_ssh"
    assert body["execution_dispatch"]["dispatch_kind"] == "ssh_remote_container"
    assert body["execution_dispatch"]["remote_host"] == "128.208.252.232"
    assert path_bindings["execution_location"] == "remote_ssh"
    assert path_bindings["remote_destination"]["workdir"].endswith("/trimodal_qc_report_v0")
    assert bindings["mudata"]["path"] == "/remote/data/demo_trimodal_small.h5mu"
    assert bindings["mudata"]["path_kind"] == "remote_visible"
    assert bindings["output_prefix"]["path_kind"] == "bundle_relative"


def test_remote_ssh_render_stages_server_readable_inputs_without_override(tmp_path: Path):
    client = _client()
    location = _remote_ssh_location(tmp_path)
    location["metadata"].pop("remote_path_overrides")

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
        },
    )

    assert response.status_code == 200
    bundle = Path(response.json()["bundle_path"])
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert bindings["mudata"]["path_kind"] == "bundle_relative"
    assert bindings["mudata"]["path"].startswith("inputs/mudata/")
    assert (bundle / bindings["mudata"]["path"]).is_file()
    assert bindings["mudata"]["staged_for_remote_ssh"] is True
    staging = path_bindings["remote_input_staging"]
    assert staging["strategy"] == "copy_server_readable_inputs_into_ssh_bundle"
    assert staging["staged"][0]["binding_id"] == "mudata"
    assert staging["skipped"] == []


def test_remote_ssh_preflight_passes_without_remote_probe_when_disabled(tmp_path: Path, monkeypatch):
    client = _client()
    monkeypatch.setattr("morphic_agent.execution.ssh.shutil.which", lambda name: f"/usr/bin/{name}" if name == "ssh" else None)
    location = _remote_ssh_location(tmp_path)
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/preflight",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": location,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preflight_passed"
    assert body["execution_location"]["kind"] == "remote_ssh"
    assert body["execution_run_gate"]["allowed"] is True
    assert body["execution_dispatch"]["dispatch_kind"] == "ssh_remote_container"
    assert any(check["check"] == "remote path overrides provided" and check["status"] == "pass" for check in body["checks"])


def test_remote_ssh_preflight_reports_staged_inputs_without_remote_probe(tmp_path: Path, monkeypatch):
    client = _client()
    monkeypatch.setattr("morphic_agent.execution.ssh.shutil.which", lambda name: f"/usr/bin/{name}" if name == "ssh" else None)
    location = _remote_ssh_location(tmp_path)
    location["metadata"].pop("remote_path_overrides")
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/preflight",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": location,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preflight_passed"
    assert any(check["check"] == "server input staged into SSH bundle: mudata" and check["status"] == "pass" for check in body["checks"])


def test_remote_ssh_preflight_blocks_when_input_exceeds_packet_copy_limit(tmp_path: Path, monkeypatch):
    client = _client()
    monkeypatch.setenv("MORPHIC_REMOTE_SSH_INPUT_COPY_MAX_BYTES", "1")
    monkeypatch.setattr("morphic_agent.execution.ssh.shutil.which", lambda name: f"/usr/bin/{name}" if name == "ssh" else None)
    location = _remote_ssh_location(tmp_path)
    location["metadata"].pop("remote_path_overrides")
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
        },
    )
    bundle = Path(rendered.json()["bundle_path"])
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert bindings["mudata"]["path_kind"] == "remote_visible"
    assert path_bindings["remote_input_staging"]["skipped"][0]["reason"] == "copy_limit_exceeded"

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/preflight",
        json={
            "bundle_path": str(bundle),
            "params": {},
            "execution_location": location,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert "MORPHIC_REMOTE_SSH_INPUT_COPY_MAX_BYTES" in body["run_blocker"]


def test_remote_ssh_execution_review_accepts_path_override_dict(tmp_path: Path):
    client = _client()
    location = _remote_ssh_location(tmp_path)
    params = {
        "mudata": "data/demo_trimodal_small.h5mu",
        "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
        "title": "Demo trimodal QC",
    }

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execution-review",
        json={
            "params": params,
            "execution_location": location,
            "review_stage": "before_render",
            "human_review": {
                "approved": True,
                "execution_location": "remote_ssh",
                "verified_paths": True,
                "remote_host": "128.208.252.232",
                "remote_workdir": location["metadata"]["remote_workdir"],
                "remote_container_runtime": "docker",
                "remote_check": False,
                "remote_path_overrides": {"mudata": "/remote/data/demo_trimodal_small.h5mu"},
                "notes": "Approve remote SSH test.",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["approved_execution_location"] == "remote_ssh"
    args = body["approved_next_step"]["arguments"]
    assert args["execution_location"]["location_id"] == "remote_ssh"
    assert args["execution_location"]["metadata"]["remote_path_overrides"]["mudata"] == "/remote/data/demo_trimodal_small.h5mu"
    assert args["review_approval_token"].startswith("review-")


def test_remote_ssh_execute_production_uses_remote_adapter_and_collects_outputs(tmp_path: Path, monkeypatch):
    client = _client()
    session_id = "remote-ssh-execute-test"
    location = _remote_ssh_location(tmp_path)
    monkeypatch.setattr("morphic_agent.execution.ssh.shutil.which", lambda name: f"/usr/bin/{name}" if name == "ssh" else None)

    def fake_remote_run(*, bundle: Path, location: object, timeout: int) -> dict[str, object]:
        output_prefix = bundle / "outputs" / "demo_trimodal_qc"
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        (Path(str(output_prefix) + ".html")).write_text("<html>remote ok</html>\n", encoding="utf-8")
        (Path(str(output_prefix) + ".json")).write_text('{"status":"ok"}\n', encoding="utf-8")
        (bundle / "execution_result.json").write_text(
            json.dumps({"status": "completed", "graph_id": "trimodal_qc_report_v0"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {"returncode": 0, "stdout": "remote ok\n", "stderr": ""}

    api_app_module = importlib.import_module("morphic_agent.api.app")
    monkeypatch.setattr(api_app_module, "run_remote_ssh_bundle", fake_remote_run)
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
            "client_session_id": session_id,
        },
        headers={"X-Morphic-Session": session_id},
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execute-production",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": location,
            "client_session_id": session_id,
            "timeout": 30,
        },
        headers={"X-Morphic-Session": session_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution_location"]["kind"] == "remote_ssh"
    assert body["execution_dispatch"]["dispatch_kind"] == "ssh_remote_container"
    assert body["execution_result"]["returncode"] == 0
    assert "remote ok" in body["execution_result"]["stdout_tail"]
    assert body["artifact_manifest"]["files"]


def test_remote_execute_production_is_blocked_before_subprocess_dispatch():
    client = _client()

    response = client.post(
        "/api/graphs/star_post_mex_h5ad_qc_v0/execute-production",
        json={
            "bundle_path": "/tmp/not-a-registered-bundle",
            "execution_location": {"kind": "remote", "remote_host": "slurm-login"},
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "blocked"
    assert body["execution_location"]["kind"] == "remote"
    assert body["execution_dispatch"]["dispatch_kind"] == "remote_connector"
    assert body["execution_run_gate"]["allowed"] is False
    assert "Remote execution requires" in body["run_blocker"]


def test_local_render_materializes_bundle_with_caller_run_metadata(tmp_path: Path):
    client = _client()

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": "local",
        },
    )

    assert response.status_code == 200
    body = response.json()
    bundle = Path(body["bundle_path"])
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert (bundle / "manifests" / "path_bindings.json").is_file()
    assert body["execution_location"]["kind"] == "local"
    assert body["execution_dispatch"]["dispatch_kind"] == "caller_managed_shell"
    assert body["execution_run_gate"]["allowed"] is False
    assert body["caller_run"]["api_executable"] is False
    assert body["path_bindings_hash"].startswith("sha256:")
    assert body["container_manifest_path"] == "manifests/container.json"
    assert body["container_manifest_hash"].startswith("sha256:")
    assert bindings["output_prefix"]["path_kind"] == "bundle_relative"
    assert bindings["output_prefix"]["path"].startswith("outputs/")
    run_sh = (bundle / "run.sh").read_text(encoding="utf-8")
    run_docker = (bundle / "run.docker.sh").read_text(encoding="utf-8")
    run_apptainer = (bundle / "run.apptainer.sh").read_text(encoding="utf-8")
    assert "manifests/path_bindings.json" in run_sh
    assert "runtime_params.json" in run_sh
    assert "biodepot/morphic-trimodal-qc:0.1.0" in run_docker
    assert "docker://biodepot/morphic-trimodal-qc:0.1.0" in run_apptainer
    assert "MUDATA=${MUDATA:-/" not in run_sh
    assert "OUTPUT_PREFIX=${OUTPUT_PREFIX:-/tmp/" not in run_sh


def test_scheduler_render_stages_inputs_and_uses_bundle_outputs(tmp_path: Path):
    client = _client()

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": _scheduler_location(tmp_path),
        },
    )

    assert response.status_code == 200
    body = response.json()
    bundle = Path(body["bundle_path"])
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert body["execution_location"]["kind"] == "scheduler_temporal"
    assert body["execution_dispatch"]["dispatch_kind"] == "temporal_workflow"
    assert body["execution_run_gate"]["allowed"] is True
    assert path_bindings["execution_location"] == "scheduler_temporal"
    assert path_bindings["scheduler_destination"]["worker_queue"] == "worker1"
    assert bindings["mudata"]["path_kind"] == "bundle_relative"
    assert bindings["mudata"]["path"].startswith("inputs/mudata/")
    assert bindings["mudata"]["staged_for_scheduler"] is True
    assert (bundle / bindings["mudata"]["path"]).is_file()
    assert bindings["output_prefix"]["path_kind"] == "bundle_relative"
    assert bindings["output_prefix"]["path"] == "outputs/demo_trimodal_qc"
    staging = path_bindings["scheduler_input_staging"]
    assert staging["strategy"] == "copy_server_readable_inputs_into_scheduler_bundle"
    assert staging["staged"][0]["binding_id"] == "mudata"


def test_scheduler_remote_ssh_render_stages_inputs_and_uses_bundle_outputs(tmp_path: Path):
    client = _client()

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": _scheduler_remote_ssh_location(tmp_path),
        },
    )

    assert response.status_code == 200
    body = response.json()
    bundle = Path(body["bundle_path"])
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text(encoding="utf-8"))
    bindings = {item["binding_id"]: item for item in path_bindings["bindings"]}
    assert body["execution_location"]["kind"] == "scheduler_remote_ssh"
    assert body["execution_dispatch"]["dispatch_kind"] == "temporal_ssh_docker_workflow"
    assert body["execution_run_gate"]["allowed"] is True
    assert path_bindings["execution_location"] == "scheduler_remote_ssh"
    assert path_bindings["remote_destination"]["host"] == "10.159.4.53"
    assert path_bindings["scheduler_destination"]["worker_queue"] == "lhhung@10.159.4.53:22"
    assert bindings["mudata"]["path_kind"] == "bundle_relative"
    assert bindings["mudata"]["path"].startswith("inputs/mudata/")
    assert bindings["mudata"]["staged_for_scheduler"] is True
    assert (bundle / bindings["mudata"]["path"]).is_file()
    assert bindings["output_prefix"]["path_kind"] == "bundle_relative"
    assert bindings["output_prefix"]["path"] == "outputs/demo_trimodal_qc"


def test_scheduler_preflight_passes_when_stack_is_reachable(tmp_path: Path, monkeypatch):
    client = _client()
    _mock_scheduler_ready(monkeypatch)
    location = _scheduler_location(tmp_path)
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/preflight",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": location,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preflight_passed"
    assert body["execution_location"]["kind"] == "scheduler_temporal"
    assert body["execution_run_gate"]["allowed"] is True
    assert body["execution_dispatch"]["direct_api_execution"] is True
    assert any(check["check"] == "Temporal scheduler API reachable" and check["status"] == "pass" for check in body["checks"])
    assert any(check["check"] == "server input staged into scheduler bundle: mudata" and check["status"] == "pass" for check in body["checks"])


def test_scheduler_remote_ssh_preflight_passes_when_stack_and_worker_are_reachable(tmp_path: Path, monkeypatch):
    client = _client()
    _mock_scheduler_ready(monkeypatch)
    location = _scheduler_remote_ssh_location(tmp_path)
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/preflight",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": location,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preflight_passed"
    assert body["execution_location"]["kind"] == "scheduler_remote_ssh"
    assert body["execution_run_gate"]["allowed"] is True
    assert body["execution_dispatch"]["direct_api_execution"] is True
    assert any(check["check"] == "scheduler SSH Docker workflow endpoint available" and check["status"] == "pass" for check in body["checks"])
    assert any(check["check"] == "server input staged into scheduler bundle: mudata" and check["status"] == "pass" for check in body["checks"])


def test_scheduler_execute_production_uses_scheduler_adapter_and_collects_outputs(tmp_path: Path, monkeypatch):
    client = _client()
    _mock_scheduler_ready(monkeypatch)
    session_id = "scheduler-execute-test"
    location = _scheduler_location(tmp_path)

    def fake_scheduler_run(*, bundle: Path, location: object, timeout: int) -> dict[str, object]:
        output_prefix = bundle / "outputs" / "demo_trimodal_qc"
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        (Path(str(output_prefix) + ".html")).write_text("<html>scheduler ok</html>\n", encoding="utf-8")
        (Path(str(output_prefix) + ".json")).write_text('{"status":"ok"}\n', encoding="utf-8")
        (bundle / "execution_result.json").write_text(
            json.dumps({"status": "completed", "graph_id": "trimodal_qc_report_v0"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {"returncode": 0, "stdout": "scheduler ok\n", "stderr": ""}

    api_app_module = importlib.import_module("morphic_agent.api.app")
    monkeypatch.setattr(api_app_module, "run_scheduler_bundle", fake_scheduler_run)
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
            "client_session_id": session_id,
        },
        headers={"X-Morphic-Session": session_id},
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execute-production",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": location,
            "client_session_id": session_id,
            "timeout": 30,
        },
        headers={"X-Morphic-Session": session_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution_location"]["kind"] == "scheduler_temporal"
    assert body["execution_dispatch"]["dispatch_kind"] == "temporal_workflow"
    assert body["execution_result"]["returncode"] == 0
    assert "scheduler ok" in body["execution_result"]["stdout_tail"]
    assert body["artifact_manifest"]["files"]


def test_scheduler_remote_ssh_execute_production_uses_scheduler_ssh_adapter_and_collects_outputs(tmp_path: Path, monkeypatch):
    client = _client()
    _mock_scheduler_ready(monkeypatch)
    session_id = "scheduler-ssh-execute-test"
    location = _scheduler_remote_ssh_location(tmp_path)

    def fake_scheduler_ssh_run(*, bundle: Path, location: object, timeout: int) -> dict[str, object]:
        output_prefix = bundle / "outputs" / "demo_trimodal_qc"
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        (Path(str(output_prefix) + ".html")).write_text("<html>scheduler ssh ok</html>\n", encoding="utf-8")
        (Path(str(output_prefix) + ".json")).write_text('{"status":"ok"}\n', encoding="utf-8")
        (bundle / "execution_result.json").write_text(
            json.dumps({"status": "completed", "graph_id": "trimodal_qc_report_v0"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {"returncode": 0, "stdout": "scheduler ssh ok\n", "stderr": ""}

    api_app_module = importlib.import_module("morphic_agent.api.app")
    monkeypatch.setattr(api_app_module, "run_scheduler_remote_ssh_bundle", fake_scheduler_ssh_run)
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": location,
            "client_session_id": session_id,
        },
        headers={"X-Morphic-Session": session_id},
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execute-production",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": location,
            "client_session_id": session_id,
            "timeout": 30,
        },
        headers={"X-Morphic-Session": session_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution_location"]["kind"] == "scheduler_remote_ssh"
    assert body["execution_dispatch"]["dispatch_kind"] == "temporal_ssh_docker_workflow"
    assert body["execution_result"]["returncode"] == 0
    assert "scheduler ssh ok" in body["execution_result"]["stdout_tail"]
    assert body["artifact_manifest"]["files"]


def test_local_bundle_zip_download_contains_manifest_and_run_script(tmp_path: Path):
    client = _client()
    session_id = "test-local-bundle-download"

    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": "local",
            "client_session_id": session_id,
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.get(
        "/api/graphs/trimodal_qc_report_v0/bundle.zip",
        params={"bundle_path": bundle_path, "client_session_id": session_id},
        headers={"X-Morphic-Session": session_id},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
    assert "trimodal_qc_report_v0/run.sh" in names
    assert "trimodal_qc_report_v0/run.docker.sh" in names
    assert "trimodal_qc_report_v0/run.apptainer.sh" in names
    assert "trimodal_qc_report_v0/manifests/path_bindings.json" in names
    assert "trimodal_qc_report_v0/manifests/container.json" in names


def test_local_preflight_reports_caller_managed_gate(tmp_path: Path):
    client = _client()
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": "local",
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/preflight",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": "local",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["execution_location"]["kind"] == "local"
    assert body["execution_run_gate"]["allowed"] is False
    assert body["execution_dispatch"]["dispatch_kind"] == "caller_managed_shell"
    assert any(check["status"] == "not_run" for check in body["checks"])
    assert "caller-local bundle" in body["run_blocker"]


def test_local_execution_diagnostic_reports_requirements_and_action_items(tmp_path: Path):
    client = _client()
    session_id = "test-local-diagnostic"
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": "local",
            "client_session_id": session_id,
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execution-diagnostic",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": "local",
            "client_session_id": session_id,
        },
        headers={"X-Morphic-Session": session_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "morphic.execution_location_diagnostic/v0"
    assert body["status"] == "blocked"
    assert body["execution_location"]["kind"] == "local"
    assert body["execution_dispatch"]["dispatch_kind"] == "caller_managed_shell"
    assert body["execution_run_gate"]["allowed"] is False
    assert body["can_execute_in_api"] is False
    assert body["path_bindings_path"] == "manifests/path_bindings.json"
    assert body["container_manifest_path"] == "manifests/container.json"
    assert body["container"]["image"]["reference"] == "biodepot/morphic-trimodal-qc:0.1.0"
    assert {"docker", "podman", "apptainer"} <= set(body["container"]["supported_runtimes"])
    if shutil.which("docker"):
        assert body["container"]["run_available"] is True
        assert body["container"]["preferred_runtime"] == "docker"
        assert body["container"]["command"] == "./run.docker.sh"
    assert {item["name"] for item in body["requirements"]} >= {"python3", "mudata", "plotly", "scanpy", "pandas", "numpy"}
    if shutil.which("docker"):
        assert any("Container route available" in item for item in body["action_items"])
    assert any("Download Run Directory" in item for item in body["action_items"])
    options = {item["id"]: item for item in body["resolution_options"]}
    assert {"run_local_container", "run_local_shell", "regenerate_for_server"} <= set(options)
    assert options["run_local_container"]["execution_location"] == "local"
    assert options["run_local_container"]["api_managed"] is False
    assert options["regenerate_for_server"]["execution_location"] == "server"
    assert options["regenerate_for_server"]["api_managed"] is True
    if shutil.which("docker"):
        assert options["run_local_container"]["recommended"] is True
        assert "./run.docker.sh" in options["run_local_container"]["commands"]
    assert body["workbench_handoff"]["schema"] == "morphic.workbench_handoff/v0"
    assert body["workbench_handoff"]["mode"] == "url_fragment"
    assert body["workbench_handoff"]["url_fragment"].startswith("#workbench=")
    assert body["workbench_handoff"]["preferred_url"].startswith("http://127.0.0.1:8890/?workbench=")
    assert body["workbench_handoff"]["payload"]["action"] == "open_execution_diagnostic"
    assert body["workbench_handoff"]["payload"]["graph_id"] == "trimodal_qc_report_v0"
    assert body["workbench_handoff"]["payload"]["params"]["mudata"] == "data/demo_trimodal_small.h5mu"
    assert any(check["check"] == "caller-visible local input paths verified by Workbench API" for check in body["checks"])
    assert "caller-local bundle" in body["run_blocker"]


def test_execution_review_request_and_completion_use_shared_contract(tmp_path: Path):
    client = _client()
    params = {
        "mudata": "data/demo_trimodal_small.h5mu",
        "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
        "title": "Demo trimodal QC",
    }

    request_response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execution-review",
        json={
            "params": params,
            "execution_location": "local",
            "review_stage": "before_render",
        },
    )

    assert request_response.status_code == 200
    request_body = request_response.json()
    assert request_body["schema"] == "morphic.execution_review_request/v0"
    assert request_body["status"] == "needs_user_input"
    assert request_body["proposed_execution_location"]["kind"] == "local"
    assert request_body["params_valid"] is True
    assert any("browser cannot automatically start run.sh" in item for item in request_body["review_items"])
    assert request_body["interaction"]["mode"] == "http_form"
    assert {"approved", "execution_location", "verified_paths"} <= set(request_body["response_schema"]["properties"])
    assert request_body["workbench_handoff"]["url_fragment"].startswith("#workbench=")
    assert request_body["workbench_handoff"]["preferred_url"].startswith("http://127.0.0.1:8890/?workbench=")
    assert request_body["workbench_handoff"]["payload"]["action"] == "open_execution_review"
    assert request_body["workbench_handoff"]["payload"]["params"]["mudata"] == params["mudata"]
    assert request_body["human_review"] is None

    approval_response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execution-review",
        json={
            "params": params,
            "execution_location": "local",
            "review_stage": "before_render",
            "human_review": {
                "approved": True,
                "execution_location": "local",
                "verified_paths": True,
                "notes": "Approved by local Workbench client.",
            },
        },
    )

    assert approval_response.status_code == 200
    approval_body = approval_response.json()
    assert approval_body["schema"] == "morphic.execution_review_request/v0"
    assert approval_body["status"] == "approved"
    assert approval_body["approved_execution_location"] == "local"
    assert approval_body["approved_next_step"]["tool_name"] == "workbench_render_bundle"
    assert approval_body["approved_next_step"]["arguments"]["execution_location"] == "local"
    assert approval_body["approved_next_step"]["arguments"]["review_approval_token"].startswith("review-")
    assert approval_body["approved_next_step"]["must_use_approved_execution_location"] is True
    assert approval_body["approved_next_step"]["requires_review_approval_token"] is True
    assert approval_body["review_approval"]["token"] == approval_body["approved_next_step"]["arguments"]["review_approval_token"]
    assert approval_body["execution_location_changed_by_user"] is False
    assert approval_body["human_review"]["approved"] is True
    assert approval_body["human_review"]["verified_paths"] is True
    assert approval_body["run_blocker"] is None

    server_approval_response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execution-review",
        json={
            "params": params,
            "execution_location": "local",
            "review_stage": "before_render",
            "human_review": {
                "approved": True,
                "execution_location": "server",
                "verified_paths": True,
                "notes": "Changed to server execution in the review form.",
            },
        },
    )
    assert server_approval_response.status_code == 200
    server_approval = server_approval_response.json()
    assert server_approval["status"] == "approved"
    assert server_approval["approved_execution_location"] == "server"
    assert server_approval["execution_location_changed_by_user"] is True
    assert server_approval["approved_next_step"]["arguments"]["execution_location"] == "server"
    assert server_approval["approved_next_step"]["arguments"]["review_approval_token"].startswith("review-")
    assert server_approval["approved_next_step"]["requires_review_approval_token"] is True
    assert server_approval["workbench_handoff"]["payload"]["execution_location"] == "server"
    assert server_approval["workbench_handoff"]["payload"]["params"]["mudata"] == params["mudata"]


def test_local_preflight_on_server_rendered_bundle_reports_locale_mismatch(tmp_path: Path):
    client = _client()
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": "server",
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/preflight",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": "local",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert "path binding `mudata` uses" not in body["run_blocker"]
    assert "path binding `output_prefix` uses" not in body["run_blocker"]
    assert body["run_blocker"].count("caller-local bundle") == 1
    assert any("rendered for `server` execution" in blocker for blocker in body["blockers"])
    assert any(
        check["check"] == "path bindings execution locale matches selected locale"
        and check["status"] == "fail"
        and check["manifest_location_id"] == "server"
        and check["selected_location_id"] == "local"
        for check in body["checks"]
    )


def test_local_execution_diagnostic_on_server_rendered_bundle_reports_regeneration(tmp_path: Path):
    client = _client()
    session_id = "test-cross-locale-diagnostic"
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={
            "params": {
                "mudata": "data/demo_trimodal_small.h5mu",
                "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
                "title": "Demo trimodal QC",
            },
            "out_root": str(tmp_path / "bundles"),
            "execution_location": "server",
            "client_session_id": session_id,
        },
    )
    bundle_path = rendered.json()["bundle_path"]

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execution-diagnostic",
        json={
            "bundle_path": bundle_path,
            "params": {},
            "execution_location": "local",
            "client_session_id": session_id,
        },
        headers={"X-Morphic-Session": session_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert "path binding `mudata` uses" not in body["run_blocker"]
    assert body["run_blocker"].count("caller-local bundle") == 1
    assert any("rendered for `server` execution" in blocker for blocker in body["blockers"])
    assert any("Download Run Directory" in item for item in body["action_items"])
    assert any(
        check["check"] == "path bindings execution locale matches selected locale"
        and check["status"] == "fail"
        for check in body["checks"]
    )


def test_local_execute_production_is_blocked_before_subprocess_dispatch():
    client = _client()

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execute-production",
        json={"bundle_path": "/tmp/not-a-registered-bundle", "execution_location": "local"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "blocked"
    assert body["execution_location"]["kind"] == "local"
    assert body["execution_run_gate"]["allowed"] is False
    assert "caller-local bundle" in body["run_blocker"]


def test_local_execute_production_stream_is_blocked_before_subprocess_dispatch():
    client = _client()

    response = client.post(
        "/api/graphs/trimodal_qc_report_v0/execute-production/stream",
        json={"bundle_path": "/tmp/not-a-registered-bundle", "execution_location": "local"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "blocked"
    assert body["execution_location"]["kind"] == "local"
    assert body["execution_run_gate"]["allowed"] is False
    assert "caller-local bundle" in body["run_blocker"]
