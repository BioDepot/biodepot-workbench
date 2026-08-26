"""Projection manifest status table."""

from __future__ import annotations

import sqlite3

revision = "20260701_0002"
description = "projection_manifests"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_projection_manifests (
            projection_version TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            adapter TEXT NOT NULL,
            vertex_count INTEGER NOT NULL,
            edge_count INTEGER NOT NULL,
            manifest_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL
        )
        """
    )
