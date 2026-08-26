"""Initial Workbench kernel schema.

The migration keeps SQLite as the default local/test backend while shaping tables
so Postgres repositories can target the same canonical model in the next
deployment step.
"""

from __future__ import annotations

import sqlite3

from morphic_agent.db.schema import WORKBENCH_KERNEL_SCHEMA_SQL

revision = "20260701_0001"
description = "initial_workbench_kernel"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(WORKBENCH_KERNEL_SCHEMA_SQL)
