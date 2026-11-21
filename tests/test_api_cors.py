"""The API is same-origin unless specific origins are configured."""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from morphic_agent.api.app import create_app

ALLOWED = "https://tutorial.example.org"
OTHER = "https://other.example.org"


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/api/runs",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_cross_origin_requests_get_no_grant_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MORPHIC_CORS_ALLOW_ORIGINS", raising=False)
    client = TestClient(create_app(db_path=tmp_path / "api.sqlite3"))
    assert "access-control-allow-origin" not in _preflight(client, OTHER).headers
    response = client.get("/healthz", headers={"Origin": OTHER})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_only_configured_origins_are_granted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MORPHIC_CORS_ALLOW_ORIGINS", f" {ALLOWED} , https://second.example.org")
    client = TestClient(create_app(db_path=tmp_path / "api.sqlite3"))
    granted = _preflight(client, ALLOWED)
    assert granted.status_code == 200
    assert granted.headers["access-control-allow-origin"] == ALLOWED
    assert "access-control-allow-origin" not in _preflight(client, OTHER).headers
