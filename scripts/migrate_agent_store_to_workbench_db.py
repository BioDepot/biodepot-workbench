#!/usr/bin/env python3
"""Copy compatible rows from an older AgentStore SQLite DB into a Workbench DB."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.db.config import resolve_database_config
from morphic_agent.registry.store import AgentStore


MIGRATABLE_TABLES = (
    "agent_threads",
    "agent_turns",
    "planner_states",
    "source_files",
    "modules",
    "module_versions",
    "module_inputs",
    "module_outputs",
    "artifact_contracts",
    "parameter_schemas",
    "compatibility_edges",
    "subgraph_versions",
    "workflow_graphs",
    "workflow_graph_versions",
    "workflow_graph_nodes",
    "workflow_graph_edges",
    "workflow_graph_inputs",
    "workflow_graph_outputs",
    "workflow_graph_capabilities",
    "workflow_graph_modalities",
    "workflow_graph_execution_locations",
    "generated_bundles",
    "execution_review_approvals",
    "workbench_runs",
    "preflight_runs",
    "execution_runs",
    "verified_recipes",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, help="Existing SQLite AgentStore DB path or sqlite:/// URL.")
    parser.add_argument("--db", required=True, help="Destination Workbench SQLite DB path or sqlite:/// URL.")
    parser.add_argument("--dry-run", action="store_true", help="Report table counts without copying rows.")
    args = parser.parse_args()

    source = _sqlite_path(args.source_db)
    destination = _sqlite_path(args.db)
    if args.dry_run:
        payload = {
            "schema": "morphic.agent_store_migration/v0",
            "status": "dry_run",
            "mutated": False,
            "source_db": str(source),
            "target_db": str(destination),
            "source_counts": _table_counts(source),
        }
    else:
        payload = _migrate(source, destination)
    print(json.dumps(payload, indent=2, sort_keys=True))


def _migrate(source: Path, destination: Path) -> dict[str, Any]:
    AgentStore(destination)
    copied: dict[str, int] = {}
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        for table in MIGRATABLE_TABLES:
            if not _table_exists(src, table) or not _table_exists(dst, table):
                continue
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            columns = [item[1] for item in src.execute(f"PRAGMA table_info({table})").fetchall()]
            if not rows or not columns:
                copied[table] = 0
                continue
            placeholders = ", ".join("?" for _ in columns)
            quoted = ", ".join(columns)
            dst.executemany(
                f"INSERT OR IGNORE INTO {table}({quoted}) VALUES ({placeholders})",
                rows,
            )
            copied[table] = len(rows)
        dst.commit()
    return {
        "schema": "morphic.agent_store_migration/v0",
        "status": "migrated",
        "mutated": True,
        "source_db": str(source),
        "target_db": str(destination),
        "copied_rows": copied,
    }


def _table_counts(db_path: Path) -> dict[str, int | None]:
    if not db_path.exists():
        return {table: None for table in MIGRATABLE_TABLES}
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if _table_exists(conn, table) else None
            for table in MIGRATABLE_TABLES
        }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _sqlite_path(value: str) -> Path:
    config = resolve_database_config(value)
    if config.sqlite_path is None:
        raise SystemExit(f"Only SQLite migration paths are supported, got `{config.backend}`.")
    return config.sqlite_path


if __name__ == "__main__":
    main()
