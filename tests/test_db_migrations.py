"""Migration smoke tests for a fresh Workbench kernel database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from morphic_agent.db.schema import EXPECTED_WORKBENCH_TABLES
from morphic_agent.db.session import apply_migrations
from morphic_agent.registry.repositories import GraphRepository


def test_initial_migration_creates_expected_tables_and_minimal_records(tmp_path: Path):
    db_path = tmp_path / "fresh.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        result = apply_migrations(conn)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }

        assert "20260701_0001" in result["applied"]
        assert EXPECTED_WORKBENCH_TABLES <= tables
        assert "idx_workflow_graph_inputs_artifact" in indexes
        assert "idx_workbench_runs_graph_id" in indexes
        assert "idx_workflow_validation_records_facets" in indexes
        assert "idx_conversations_owner_updated" in indexes
        assert "idx_conversation_run_links_run" in indexes

        conn.execute(
            """
            INSERT INTO workbench_runs(
              run_id, graph_id, params_hash, status, current_step,
              state_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-minimal",
                "minimal_graph_v0",
                "sha256:minimal",
                "created",
                "created",
                json.dumps({"run_id": "run-minimal", "graph_id": "minimal_graph_v0"}),
                "2026-07-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
            ),
        )
        conn.commit()
        graph_repo = GraphRepository(lambda: sqlite3.connect(db_path))
        graph_repo.upsert_graph(
            {
                "schema": "morphic.workflow_graph/v0",
                "graph_id": "minimal_graph_v0",
                "title": "Minimal graph",
                "nodes": [],
                "edges": [],
                "inputs": [{"name": "input", "artifact_type": "txt", "required": True}],
                "outputs": [{"name": "output", "artifact_type": "json"}],
                "capabilities": ["smoke"],
                "lifecycle_state": "candidate",
                "materialization_status": "graph_draft_only",
            }
        )

        assert conn.execute("SELECT count(*) FROM workbench_runs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM workflow_graphs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM workflow_graph_inputs").fetchone()[0] == 1
    finally:
        conn.close()


def test_conversation_migration_backfills_legacy_agent_threads(tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE schema_migrations (
                revision TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE agent_threads (
                thread_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE workbench_runs (
                run_id TEXT PRIMARY KEY
            );
            INSERT INTO schema_migrations(revision, description) VALUES
                ('20260701_0001', 'legacy'),
                ('20260701_0002', 'legacy'),
                ('20260701_0003', 'legacy');
            INSERT INTO agent_threads(thread_id, created_at, updated_at) VALUES
                ('thread-legacy', '2026-07-01T00:00:00Z', '2026-07-02T00:00:00Z');
            """
        )

        result = apply_migrations(conn)
        row = conn.execute(
            "SELECT * FROM conversations WHERE conversation_id='thread-legacy'"
        ).fetchone()

        assert result["applied"] == ["20260719_0004"]
        assert row is not None
        assert row["thread_id"] == "thread-legacy"
        assert row["owner_user"] == "anonymous"
        assert row["title"] == "Legacy conversation"
        assert row["status"] == "active"
    finally:
        conn.close()
