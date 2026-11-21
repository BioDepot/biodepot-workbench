"""Regression tests for API input and config handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from morphic_agent.api.app import create_app

JSON = {"content-type": "application/json"}
BODY_ROUTES = [
    "/api/chat",
    "/api/graphs/draft",
    "/api/runs",
    "/api/conversations",
    "/api/star-mvp/plan",
]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(db_path=tmp_path / "api.sqlite3"), raise_server_exceptions=False)


@pytest.mark.parametrize("route", BODY_ROUTES)
@pytest.mark.parametrize("raw", [b"{bad", b""])
def test_malformed_json_body_returns_400(tmp_path: Path, route: str, raw: bytes):
    response = _client(tmp_path).post(route, content=raw, headers=JSON)
    assert response.status_code == 400
    assert "JSON" in response.json()["message"]


def test_non_json_content_type_still_means_empty_body(tmp_path: Path):
    response = _client(tmp_path).post("/api/conversations", content=b"{bad")
    assert response.status_code in (200, 201), response.text[:300]


def test_infinite_json_number_is_a_400_not_a_500(tmp_path: Path):
    response = _client(tmp_path).post(
        "/api/graphs/x/execute-production", content=b'{"timeout": 1e999}', headers=JSON
    )
    assert response.status_code == 400
    assert "timeout" in response.json()["message"]


@pytest.mark.parametrize("path", ["a\x00b", "a" * 5000, "~no_such_user_zz/x"])
def test_file_browser_invalid_path_returns_400(tmp_path: Path, monkeypatch, path: str):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("MORPHIC_AGENT_FILE_BROWSER_ROOTS", str(root))
    prefix = "" if path.startswith("~") else str(root) + "/"
    response = _client(tmp_path).get("/api/files/browse", params={"path": prefix + path})
    assert response.status_code == 400


def test_star_mvp_execute_bad_timeout_returns_400(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MORPHIC_AGENT_ENABLE_LOCAL_SMOKE_EXECUTION", "1")
    response = _client(tmp_path).post(
        "/api/star-mvp/execute", json={"graph_id": "g", "bundle_path": str(tmp_path), "timeout": "abc"}
    )
    assert response.status_code == 400
    assert "timeout" in response.json()["message"]


@pytest.mark.parametrize("suffix", ["execute-production", "execute-production/stream"])
def test_production_execute_bad_timeout_rejected_before_review_state(tmp_path: Path, suffix: str):
    response = _client(tmp_path).post(
        f"/api/graphs/some_graph/{suffix}", json={"timeout": "abc", "review_approval_token": "t"}
    )
    assert response.status_code == 400
    assert "timeout" in response.json()["message"]


def test_create_app_uses_database_url_when_no_path_set(tmp_path: Path, monkeypatch):
    target = tmp_path / "from-url.sqlite3"
    for name in ("MORPHIC_AGENT_DB", "MORPHIC_AGENT_DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MORPHIC_AGENT_DATABASE_URL", f"sqlite:///{target}")
    app = create_app()
    assert app.state.workbench_service.store.db_path == target


def test_create_app_explicit_db_env_keeps_priority(tmp_path: Path, monkeypatch):
    explicit = tmp_path / "explicit.sqlite3"
    monkeypatch.delenv("MORPHIC_AGENT_DB_PATH", raising=False)
    monkeypatch.setenv("MORPHIC_AGENT_DB", str(explicit))
    monkeypatch.setenv("MORPHIC_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'other.sqlite3'}")
    assert create_app().state.workbench_service.store.db_path == explicit
