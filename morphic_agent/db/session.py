"""SQLite migration/session helpers for the current Workbench kernel."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from typing import Any

from morphic_agent.db.config import DatabaseConfig, resolve_database_config
from morphic_agent.db.migrations import MIGRATION_MODULES


def initialize_sqlite_database(db_path_or_url: str | Path | None = None) -> DatabaseConfig:
    config = resolve_database_config(db_path_or_url)
    if config.backend != "sqlite" or config.sqlite_path is None:
        raise ValueError(
            f"Workbench compatibility store currently requires SQLite; got database backend `{config.backend}`."
        )
    config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(config.sqlite_path, timeout=30) as conn:
        apply_migrations(conn)
    return config


def apply_migrations(conn: sqlite3.Connection) -> dict[str, Any]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            revision TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        str(row[0])
        for row in conn.execute("SELECT revision FROM schema_migrations").fetchall()
    }
    applied_now: list[str] = []
    for module_name in MIGRATION_MODULES:
        module = importlib.import_module(module_name)
        revision = str(getattr(module, "revision"))
        description = str(getattr(module, "description", revision))
        if revision in applied:
            continue
        module.upgrade(conn)
        # Migrations are idempotent, so a concurrent first start may record the
        # same revision; ignore the duplicate instead of failing.
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(revision, description) VALUES (?, ?)",
            (revision, description),
        )
        applied_now.append(revision)
    return {"applied": applied_now, "known": [name.rsplit(".", 1)[-1] for name in MIGRATION_MODULES]}
