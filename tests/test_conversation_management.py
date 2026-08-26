"""Owned conversation lifecycle across HTTP, MCP, and persisted planner threads."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import Client
from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.mcp import build_workbench_mcp
from morphic_agent.registry.store import AgentStore
from morphic_agent.workbench import WorkbenchService


def _headers(user: str, session: str = "browser-session") -> dict[str, str]:
    return {"X-Remote-User": user, "X-Morphic-Session": session}


def test_conversation_api_lifecycle_and_owner_isolation(tmp_path: Path):
    client = TestClient(create_app(db_path=tmp_path / "conversations.sqlite3"))
    alice = _headers("alice")
    bob = _headers("bob")

    created_response = client.post("/api/conversations", json={"title": "Bulk RNA tutorial"}, headers=alice)
    assert created_response.status_code == 201
    created = created_response.json()["conversation"]
    conversation_id = created["conversation_id"]
    assert created["owner_user"] == "alice"
    assert created["status"] == "active"

    listed = client.get("/api/conversations", headers=alice).json()
    assert [item["conversation_id"] for item in listed["conversations"]] == [conversation_id]
    assert client.get("/api/conversations", headers=bob).json()["conversation_count"] == 0
    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).status_code == 403

    renamed = client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "Bulk RNA counts and DESeq2"},
        headers=alice,
    )
    assert renamed.status_code == 200
    assert renamed.json()["conversation"]["title"] == "Bulk RNA counts and DESeq2"

    chat = client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "goal": "Draft a trimodal QC workflow."},
        headers=alice,
    )
    assert chat.status_code == 200
    assert chat.json()["conversation_id"] == conversation_id
    assert chat.json()["thread_id"] == conversation_id

    detail = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert [turn["role"] for turn in detail["turns"]] == ["user", "assistant"]
    assert detail["conversation"]["turn_count"] == 2

    archived = client.patch(
        f"/api/conversations/{conversation_id}",
        json={"status": "archived"},
        headers=alice,
    )
    assert archived.status_code == 200
    assert archived.json()["conversation"]["archived_at"]
    blocked = client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "goal": "Continue."},
        headers=alice,
    )
    assert blocked.status_code == 409
    explained = client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "intent": "explain_plan"},
        headers=alice,
    )
    assert explained.status_code == 200
    assert explained.json()["conversation_id"] == conversation_id
    archived_run = client.post(
        "/api/runs",
        json={
            "graph_id": "trimodal_qc_report_v0",
            "params": {},
            "execution_location": "local",
            "conversation_id": conversation_id,
        },
        headers=alice,
    )
    assert archived_run.status_code == 400

    restored = client.patch(
        f"/api/conversations/{conversation_id}",
        json={"status": "active"},
        headers=alice,
    )
    assert restored.status_code == 200
    assert restored.json()["conversation"]["archived_at"] is None

    forked = client.post(
        f"/api/conversations/{conversation_id}/fork",
        json={"title": "Alternative normalization", "include_history": True},
        headers=alice,
    )
    assert forked.status_code == 201
    fork = forked.json()["conversation"]
    assert fork["parent_conversation_id"] == conversation_id
    fork_detail = client.get(f"/api/conversations/{fork['conversation_id']}", headers=alice).json()
    assert len(fork_detail["turns"]) == 2

    legacy_log = client.get(f"/api/threads/{conversation_id}/turns", headers=bob)
    assert legacy_log.status_code == 403


def test_chat_auto_creates_and_resumes_persisted_conversation(tmp_path: Path):
    db_path = tmp_path / "resume.sqlite3"
    first_client = TestClient(create_app(db_path=db_path))
    headers = _headers("alice", "first-session")
    first = first_client.post(
        "/api/chat",
        json={"goal": "Create a bulk RNA-seq workflow."},
        headers=headers,
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    assert first.json()["conversation"]["title"] == "Create a bulk RNA-seq workflow."

    resumed_client = TestClient(create_app(db_path=db_path))
    listed = resumed_client.get("/api/conversations", headers=_headers("alice", "second-session"))
    assert listed.status_code == 200
    assert listed.json()["conversations"][0]["conversation_id"] == conversation_id
    second = resumed_client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "goal": "Explain the current plan."},
        headers=_headers("alice", "second-session"),
    )
    assert second.status_code == 200
    assert second.json()["conversation"]["last_session_id"] == "second-session"


def test_legacy_thread_creation_is_immediately_discoverable(tmp_path: Path):
    store = AgentStore(tmp_path / "legacy-direct.sqlite3")
    store.append_turn("direct-planner-thread", role="user", goal="Plan a workflow")

    conversation = store.get_conversation("direct-planner-thread", owner_user="anonymous")
    assert conversation is not None
    assert conversation["title"] == "New conversation"
    assert conversation["turn_count"] == 1


def test_conversation_links_workbench_runs(tmp_path: Path):
    client = TestClient(create_app(db_path=tmp_path / "runs.sqlite3"))
    headers = _headers("alice")
    conversation = client.post("/api/conversations", json={"title": "Run linkage"}, headers=headers).json()["conversation"]
    client.post("/api/conversations", json={"title": "Newer idle conversation"}, headers=headers)

    run = client.post(
        "/api/runs",
        json={
            "graph_id": "trimodal_qc_report_v0",
            "params": {},
            "execution_location": "local",
            "conversation_id": conversation["conversation_id"],
        },
        headers=headers,
    )
    assert run.status_code == 201
    detail = client.get(f"/api/conversations/{conversation['conversation_id']}", headers=headers).json()
    assert detail["conversation"]["run_count"] == 1
    assert detail["runs"][0]["run_id"] == run.json()["run_id"]
    listed_conversations = client.get("/api/conversations", headers=headers).json()["conversations"]
    assert listed_conversations[0]["conversation_id"] == conversation["conversation_id"]
    assert client.get(f"/api/runs/{run.json()['run_id']}", headers=_headers("bob")).status_code == 403
    assert client.get("/api/runs", headers=_headers("bob")).json()["run_count"] == 0
    assert client.get("/api/runs", headers=headers).json()["run_count"] == 1


def test_run_cannot_be_linked_to_another_users_conversation(tmp_path: Path):
    client = TestClient(create_app(db_path=tmp_path / "forged-link.sqlite3"))
    bob_conversation = client.post(
        "/api/conversations",
        json={"title": "Bob's work"},
        headers=_headers("bob"),
    ).json()["conversation"]

    forged = client.post(
        "/api/runs",
        json={
            "graph_id": "trimodal_qc_report_v0",
            "params": {},
            "execution_location": "local",
            "conversation_id": bob_conversation["conversation_id"],
        },
        headers=_headers("alice"),
    )
    assert forged.status_code == 403
    detail = client.get(
        f"/api/conversations/{bob_conversation['conversation_id']}",
        headers=_headers("bob"),
    ).json()
    assert detail["conversation"]["run_count"] == 0


def test_conversation_mcp_tools_enforce_owner_and_fork(tmp_path: Path):
    async def run() -> None:
        service = WorkbenchService.create(db_path=tmp_path / "mcp.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=tmp_path / "bundles")
        async with Client(server) as client:
            created = (
                await client.call_tool(
                    "workbench_create_conversation",
                    {"user": "Alice Smith", "session_id": "MCP A", "title": "MCP tutorial"},
                )
            ).data
            conversation_id = created["conversation_id"]
            assert created["conversation"]["owner_user"] == "alice-smith"
            assert created["conversation"]["origin_session_id"] == "mcp-a"
            listed = (
                await client.call_tool(
                    "workbench_list_conversations",
                    {"user": "alice-smith"},
                )
            ).data
            forbidden = (
                await client.call_tool(
                    "workbench_get_conversation",
                    {"conversation_id": conversation_id, "user": "bob"},
                )
            ).data
            forked = (
                await client.call_tool(
                    "workbench_fork_conversation",
                    {"conversation_id": conversation_id, "user": "alice-smith", "title": "MCP fork"},
                )
            ).data
        assert listed["conversation_count"] == 1
        assert forbidden["http_status"] == 403
        assert forked["http_status"] == 201
        assert forked["conversation"]["parent_conversation_id"] == conversation_id

    asyncio.run(run())


def test_workbench_html_contains_conversation_manager(tmp_path: Path):
    client = TestClient(create_app(db_path=tmp_path / "ui.sqlite3"))
    html = client.get("/").text
    for expected in (
        "conversationList",
        "newConversationBtn",
        "renameConversationBtn",
        "forkConversationBtn",
        "archiveConversationBtn",
        "function refreshConversations",
        "function openConversation",
        "/api/conversations",
    ):
        assert expected in html
