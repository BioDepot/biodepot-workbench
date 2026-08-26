"""Workflow validation evidence records."""

from __future__ import annotations

import sqlite3

revision = "20260701_0003"
description = "workflow_validation_records"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_validation_records (
            validation_id TEXT PRIMARY KEY,
            graph_id TEXT NOT NULL,
            canonical_graph_hash TEXT,
            source_manifest_hash TEXT,
            validation_kind TEXT NOT NULL,
            comparator_kind TEXT NOT NULL,
            executor TEXT,
            profile TEXT,
            fixture_id TEXT,
            status TEXT NOT NULL,
            manifest_hash TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_validation_records_graph_id ON workflow_validation_records(graph_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_validation_records_status ON workflow_validation_records(status)"
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_validation_records_facets
        ON workflow_validation_records(validation_kind, comparator_kind, executor, fixture_id)
        """
    )
