"""Database URL resolution for the Workbench platform."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatabaseConfig:
    """Resolved database target.

    SQLite remains the default development and test backend. Postgres URLs are
    accepted at the configuration boundary for opt-in integration tests and
    deployment wiring, but the current compatibility store still requires SQLite
    unless a repository implementation explicitly opts into another dialect.
    """

    url: str
    backend: str
    sqlite_path: Path | None = None


def resolve_database_config(db_path_or_url: str | Path | None = None) -> DatabaseConfig:
    raw = str(db_path_or_url or "").strip()
    if not raw:
        raw = str(os.environ.get("MORPHIC_AGENT_DATABASE_URL") or "").strip()
    if raw:
        return _config_from_value(raw)

    legacy_path = str(os.environ.get("MORPHIC_AGENT_DB") or "").strip()
    if legacy_path:
        return _sqlite_path_config(Path(legacy_path).expanduser())

    fd, path = tempfile.mkstemp(prefix="morphic-agent-", suffix=".sqlite3")
    os.close(fd)
    return _sqlite_path_config(Path(path))


def _config_from_value(value: str) -> DatabaseConfig:
    if value.startswith("sqlite:///"):
        return _sqlite_path_config(Path(value.removeprefix("sqlite:///")).expanduser())
    if value.startswith("sqlite://"):
        return _sqlite_path_config(Path(value.removeprefix("sqlite://")).expanduser())
    if "://" in value:
        backend = value.split(":", 1)[0]
        return DatabaseConfig(url=value, backend=backend, sqlite_path=None)
    return _sqlite_path_config(Path(value).expanduser())


def _sqlite_path_config(path: Path) -> DatabaseConfig:
    resolved = path.expanduser()
    return DatabaseConfig(url=f"sqlite:///{resolved}", backend="sqlite", sqlite_path=resolved)
