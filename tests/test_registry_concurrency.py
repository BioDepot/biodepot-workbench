"""Concurrency and malformed-catalog regressions for the registry and database layers."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from morphic_agent.db.session import apply_migrations
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore


def test_concurrent_update_run_keeps_every_field_and_event(tmp_path: Path):
    store = AgentStore(str(tmp_path / "runs.sqlite3"))
    run_id = store.create_workbench_run("g", {}, status="created", current_step="created")["run_id"]
    count = 16
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait()
            store.update_workbench_run(run_id, {f"k{index}": index}, event=f"e{index}")
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    run = store.get_workbench_run(run_id)
    assert all(run[f"k{i}"] == i for i in range(count))
    assert len(run["events"]) == count + 1


def test_update_missing_run_returns_none(tmp_path: Path):
    store = AgentStore(str(tmp_path / "runs.sqlite3"))
    assert store.update_workbench_run("run-missing", {"a": 1}, event="x") is None


def test_apply_migrations_tolerates_revision_recorded_concurrently(tmp_path: Path):
    db_path = tmp_path / "mig.sqlite3"
    conn = sqlite3.connect(db_path)
    apply_migrations(conn)
    conn.commit()
    # Simulate a peer that applied the first revision between our read and insert.
    revision = conn.execute("SELECT revision FROM schema_migrations ORDER BY revision LIMIT 1").fetchone()[0]
    conn.execute("DELETE FROM schema_migrations WHERE revision=?", (revision,))
    conn.commit()
    other = sqlite3.connect(db_path)
    original = conn.execute

    class Racing:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if sql.lstrip().startswith("INSERT") and "schema_migrations" in sql:
                other.execute("INSERT INTO schema_migrations(revision, description) VALUES (?, 'peer')", (revision,))
                other.commit()
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    apply_migrations(Racing(conn))
    other.close()
    conn.close()
    del original


def _catalog(tmp_path: Path, payload) -> ModuleCatalog:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = AgentStore(str(tmp_path / "cat.sqlite3"))
    return ModuleCatalog(path, store=store, import_suite_recipes=False)


def test_duplicate_input_and_output_names_are_validation_errors(tmp_path: Path):
    item = {"name": "x", "artifact_type": "T"}
    module = {"module_id": "a", "title": "A", "runtime": {}, "inputs": [item, item], "outputs": [item, item]}
    catalog = _catalog(tmp_path, {"modules": [module]})
    errors = catalog._payload["errors"]
    assert any("duplicate input name" in str(e) for e in errors)
    assert any("duplicate output name" in str(e) for e in errors)


def test_non_object_catalog_is_an_error_payload(tmp_path: Path):
    catalog = _catalog(tmp_path, [])
    assert catalog._payload["errors"]
    assert catalog._payload["modules"] == []
