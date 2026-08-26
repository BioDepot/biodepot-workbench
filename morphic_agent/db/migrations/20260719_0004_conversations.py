"""Owned conversation records around legacy planner threads."""

from __future__ import annotations

import sqlite3

revision = "20260719_0004"
description = "owned_conversations"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL UNIQUE,
            owner_user TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            origin_session_id TEXT,
            last_session_id TEXT,
            parent_conversation_id TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT,
            FOREIGN KEY(thread_id) REFERENCES agent_threads(thread_id),
            FOREIGN KEY(parent_conversation_id) REFERENCES conversations(conversation_id)
        );
        CREATE TABLE IF NOT EXISTS conversation_run_links (
            conversation_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            linked_at TEXT NOT NULL,
            PRIMARY KEY(conversation_id, run_id),
            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
            FOREIGN KEY(run_id) REFERENCES workbench_runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated
          ON conversations(owner_user, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_conversation_run_links_run
          ON conversation_run_links(run_id);
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO conversations(
          conversation_id, thread_id, owner_user, title, status,
          origin_session_id, last_session_id, parent_conversation_id,
          metadata_json, created_at, updated_at, archived_at
        )
        SELECT
          thread_id, thread_id, 'anonymous', 'Legacy conversation', 'active',
          NULL, NULL, NULL, '{"migrated_from":"agent_threads"}',
          created_at, updated_at, NULL
        FROM agent_threads
        """
    )
