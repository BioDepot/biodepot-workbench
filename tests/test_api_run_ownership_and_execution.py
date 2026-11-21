"""Run ownership on preflight/materialize routes and execution concurrency."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.execution.nextflow import run_in_new_session, run_nextflow_bundle, terminate_process_group
from morphic_agent.workbench.service import WorkbenchService

GRAPH = "trimodal_qc_report_v0"
ALICE = {"x-auth-request-email": "alice@example.org"}
BOB = {"x-auth-request-email": "bob@example.org"}
PRIVATE_ROUTES = hasattr(WorkbenchService, "record_external_preflight")
app_module = importlib.import_module("morphic_agent.api.app")


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(db_path=tmp_path / "api.sqlite3"), raise_server_exceptions=False)


def _params(tmp_path: Path) -> dict:
    return {"mudata": "data/demo_trimodal_small.h5mu", "output_prefix": str(tmp_path / "qc" / "demo")}


def _start_run(client: TestClient, tmp_path: Path, headers: dict) -> str:
    response = client.post("/api/runs", json={"graph_id": GRAPH, "params": _params(tmp_path)}, headers=headers)
    assert response.status_code == 201, response.text[:300]
    return response.json()["run_id"]


def _run(client: TestClient, run_id: str, headers: dict) -> dict:
    response = client.get(f"/api/runs/{run_id}", headers=headers)
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    return body.get("run", body)


def test_graph_preflight_rejects_other_users_run(tmp_path: Path):
    client = _client(tmp_path)
    run_id = _start_run(client, tmp_path, ALICE)
    before = _run(client, run_id, ALICE)

    response = client.post(
        f"/api/graphs/{GRAPH}/preflight",
        json={"run_id": run_id, "bundle_path": str(tmp_path), "params": {}, "execution_location": "server"},
        headers=BOB,
    )

    assert "owned by" in json.dumps(response.json())
    after = _run(client, run_id, ALICE)
    assert after["status"] == before["status"]
    assert len(after.get("events") or []) == len(before.get("events") or [])


def test_graph_preflight_allows_owner_and_anonymous_local_flow(tmp_path: Path):
    client = _client(tmp_path)
    alice_run = _start_run(client, tmp_path, ALICE)
    anon_run = _start_run(client, tmp_path, {})
    for run_id, headers in ((alice_run, ALICE), (anon_run, {})):
        response = client.post(
            f"/api/graphs/{GRAPH}/preflight",
            json={"run_id": run_id, "bundle_path": str(tmp_path), "params": {}, "execution_location": "server"},
            headers=headers,
        )
        assert "owned by" not in json.dumps(response.json())
        assert _run(client, run_id, headers)["status"].startswith("preflight")


def test_service_without_request_context_still_works(tmp_path: Path):
    # MCP and internal callers pass no request context and must keep working.
    service = WorkbenchService.create(db_path=tmp_path / "service.sqlite3")
    run = service.start_run(GRAPH, _params(tmp_path), execution_location="server", request_context={"user": "alice"})
    result = service.preflight_bundle(
        GRAPH, {}, execution_location="server", bundle_path=str(tmp_path), run_id=run["run_id"]
    )
    assert "owned by" not in json.dumps(result)
    other = service.preflight_bundle(
        GRAPH,
        {},
        execution_location="server",
        bundle_path=str(tmp_path),
        run_id=run["run_id"],
        request_context={"user": "bob"},
    )
    assert "owned by" in json.dumps(other)


@pytest.mark.skipif(not PRIVATE_ROUTES, reason="star-mvp preflight/materialize ownership applies to the private routes")
def test_star_mvp_preflight_and_materialize_reject_other_users_run(tmp_path: Path):
    client = _client(tmp_path)
    plan = client.post("/api/star-mvp/plan", json={}).json()
    graph_id = plan["graph_id"]
    run_id = client.post("/api/runs", json={"graph_id": graph_id}, headers=ALICE).json()["run_id"]
    before = _run(client, run_id, ALICE)

    preflight = client.post(
        "/api/star-mvp/preflight",
        json={"graph_id": graph_id, "run_id": run_id, "bundle_path": str(tmp_path)},
        headers=BOB,
    )
    materialize = client.post(
        "/api/star-mvp/materialize",
        json={"graph_id": graph_id, "run_id": run_id, "out_root": str(tmp_path / "out")},
        headers=BOB,
    )

    assert preflight.status_code == 400 and "owned by" in preflight.json()["run_blocker"]
    assert materialize.status_code == 400
    after = _run(client, run_id, ALICE)
    assert after["status"] == before["status"]
    assert not after.get("bundle")


def _server_run_ready(client: TestClient, tmp_path: Path) -> dict:
    params = _params(tmp_path)
    rendered = client.post(
        f"/api/graphs/{GRAPH}/render",
        json={"params": params, "out_root": str(tmp_path / "bundles"), "execution_location": "server"},
    ).json()
    bundle_path = rendered["bundle_path"]
    review = client.post(
        f"/api/graphs/{GRAPH}/execution-review",
        json={
            "params": params,
            "bundle_path": bundle_path,
            "execution_location": "server",
            "review_stage": "before_execute",
            "human_review": {"approved": True, "execution_location": "server", "verified_paths": True},
        },
    ).json()
    assert review["status"] == "approved", review
    preflight = client.post(
        f"/api/graphs/{GRAPH}/preflight",
        json={
            "params": {},
            "bundle_path": bundle_path,
            "execution_location": review["approved_execution_location_request"],
            "run_id": review["run_id"],
        },
    ).json()
    assert preflight["status"] == "preflight_passed", preflight
    return {
        "bundle_path": bundle_path,
        "params": {},
        "execution_location": review["approved_execution_location_request"],
        "run_id": review["run_id"],
        "timeout": 5,
    }


def test_local_production_run_executes_off_the_event_loop(tmp_path: Path, monkeypatch):
    client = _client(tmp_path)
    payload = _server_run_ready(client, tmp_path)
    on_loop: list[bool] = []

    def fake(command, *, cwd, timeout, env=None):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(app_module, "run_in_new_session", fake)
    response = client.post(f"/api/graphs/{GRAPH}/execute-production", json=payload)

    assert response.status_code == 200, response.text
    assert on_loop == [False]


def _stream_events(client: TestClient, payload: dict) -> list[dict]:
    response = client.post(f"/api/graphs/{GRAPH}/execute-production/stream", json=payload)
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def _patch_launcher(monkeypatch, exc: BaseException):
    real_popen = subprocess.Popen

    def popen(command, *args, **kwargs):
        if isinstance(command, list) and command[:1] == ["bash"]:
            raise exc
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(app_module.subprocess, "Popen", popen)


def test_stream_timeout_is_finalized_like_the_non_stream_handler(tmp_path: Path, monkeypatch):
    client = _client(tmp_path)
    payload = _server_run_ready(client, tmp_path)
    _patch_launcher(monkeypatch, subprocess.TimeoutExpired("bash", 5))

    result = _stream_events(client, payload)[-1]["payload"]

    assert result["execution_result"]["failure_kind"] == "timeout"
    assert result["execution_id"]
    assert client.get(f"/api/runs/{payload['run_id']}").json()["status"] != "execution_running"


def test_stream_unexpected_exception_does_not_leave_run_running(tmp_path: Path, monkeypatch):
    client = _client(tmp_path)
    payload = _server_run_ready(client, tmp_path)
    _patch_launcher(monkeypatch, OSError("launcher unavailable"))

    result = _stream_events(client, payload)[-1]["payload"]

    assert result["message"] == "launcher unavailable"
    assert result["execution_id"]
    assert client.get(f"/api/runs/{payload['run_id']}").json()["status"] != "execution_running"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def _wait_dead(pid: int) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(pid)


def test_run_in_new_session_timeout_kills_descendants(tmp_path: Path):
    pidfile = tmp_path / "child.pid"
    script = tmp_path / "run.sh"
    script.write_text(f"sleep 60 &\necho $! > {pidfile}\nwait\n")
    with pytest.raises(subprocess.TimeoutExpired):
        run_in_new_session(["bash", str(script)], cwd=str(tmp_path), timeout=1)
    child = int(pidfile.read_text())
    assert _wait_dead(child)


def test_run_nextflow_bundle_timeout_kills_descendants(tmp_path: Path):
    pidfile = tmp_path / "child.pid"
    (tmp_path / "run.nextflow.sh").write_text(f"sleep 60 &\necho $! > {pidfile}\nwait\n")
    result = run_nextflow_bundle(tmp_path, timeout_seconds=1)
    assert result["failure_kind"] == "timeout"
    assert _wait_dead(int(pidfile.read_text()))


def test_terminate_process_group_kills_descendants(tmp_path: Path):
    pidfile = tmp_path / "child.pid"
    proc = subprocess.Popen(
        ["bash", "-c", f"sleep 60 & echo $! > {pidfile}; wait"], start_new_session=True
    )
    deadline = time.monotonic() + 3
    while not (pidfile.exists() and pidfile.read_text().strip()) and time.monotonic() < deadline:
        time.sleep(0.02)
    terminate_process_group(proc)
    assert _wait_dead(int(pidfile.read_text()))


def test_nonstream_unexpected_exception_is_finalized_as_failed(tmp_path: Path, monkeypatch):
    client = _client(tmp_path)
    payload = _server_run_ready(client, tmp_path)

    def boom(command, *, cwd, timeout, env=None):
        raise OSError("launcher unavailable")

    monkeypatch.setattr(app_module, "run_in_new_session", boom)
    response = client.post(f"/api/graphs/{GRAPH}/execute-production", json=payload)

    assert response.status_code == 500
    assert response.json()["message"] == "launcher unavailable"
    assert response.json().get("execution_id")
    assert client.get(f"/api/runs/{payload['run_id']}").json()["status"] != "execution_running"


def test_failed_finalize_does_not_record_a_second_failed_execution(tmp_path: Path, monkeypatch):
    client = _client(tmp_path)
    payload = _server_run_ready(client, tmp_path)
    monkeypatch.setattr(
        app_module,
        "run_in_new_session",
        lambda command, *, cwd, timeout, env=None: subprocess.CompletedProcess(command, 0, "hello out", ""),
    )
    import morphic_agent.registry.store as store_module

    store_cls = next(c for c in vars(store_module).values() if isinstance(c, type) and c.__module__ == store_module.__name__ and hasattr(c, "update_workbench_run") and hasattr(c, "record_execution"))
    original = store_cls.update_workbench_run
    calls = {"update": 0, "record": 0}

    def flaky_update(self, *args, **kwargs):
        if kwargs.get("event") == "execution_completed" and not calls["update"]:
            calls["update"] += 1
            raise RuntimeError("database is locked")
        return original(self, *args, **kwargs)

    original_record = store_cls.record_execution

    def counting_record(self, *args, **kwargs):
        calls["record"] += 1
        return original_record(self, *args, **kwargs)

    monkeypatch.setattr(store_cls, "update_workbench_run", flaky_update)
    monkeypatch.setattr(store_cls, "record_execution", counting_record)
    response = client.post(f"/api/graphs/{GRAPH}/execute-production", json=payload)

    assert response.status_code == 500
    assert calls["record"] == 1
    assert calls["update"] == 1
    assert "hello out" in response.json()["stdout_tail"]


def test_run_materialized_bundle_timeout_kills_descendants(tmp_path: Path):
    from morphic_front.graph_mvp import run_materialized_bundle

    pidfile = tmp_path / "child.pid"
    (tmp_path / "run.sh").write_text(f"sleep 60 &\necho $! > {pidfile}\nwait\n")
    with pytest.raises(subprocess.TimeoutExpired):
        run_materialized_bundle(tmp_path, timeout=1)
    assert _wait_dead(int(pidfile.read_text()))
