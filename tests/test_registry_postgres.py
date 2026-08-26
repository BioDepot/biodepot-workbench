"""Postgres-shaped canonical registry tests using the SQLite walking skeleton."""

from __future__ import annotations

import tempfile

from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore


def test_module_catalog_imports_to_canonical_store_idempotently():
    store = AgentStore(tempfile.mktemp(suffix=".sqlite3"))
    catalog = ModuleCatalog(store=store)
    first_count = len(catalog.list_modules())
    first_manifest = catalog.import_manifest

    second = ModuleCatalog(store=store)

    assert first_count >= 10
    assert second.import_manifest == first_manifest
    assert store.count_rows("source_files") >= 1
    assert store.count_rows("modules") == first_count
    assert store.count_rows("module_versions") >= first_count
    assert store.count_rows("artifact_contracts") >= 8
    assert store.count_rows("compatibility_edges") > 0
    if catalog.suite_import_manifest:
        assert store.count_rows("source_files") >= 2
        assert store.count_rows("subgraph_versions") == catalog.suite_graph_import_manifest["graph_count"]


def test_module_contract_preserves_runtime_confidence_evidence_and_preflight():
    store = AgentStore(tempfile.mktemp(suffix=".sqlite3"))
    ModuleCatalog(store=store)

    module = store.get_module_contract("star_bulk_pe_counts")

    assert module is not None
    assert module["runtime"]["workflow_id"] == "star_bulk_pe_batch"
    assert module["confidence_tier"] == "curated_profile"
    assert module["evidence"]
    assert "STAR suite render succeeds" in module["preflight"]


def test_agent_thread_state_survives_new_store_instance():
    db_path = tempfile.mktemp(suffix=".sqlite3")
    first = AgentStore(db_path)
    first.ensure_thread("thread-registry-1")
    first.save_planner_state("thread-registry-1", {"selected_graph": {"graph_id": "bulk_pe_deseq2_v0"}})

    second = AgentStore(db_path)

    assert second.load_planner_state("thread-registry-1") == {
        "selected_graph": {"graph_id": "bulk_pe_deseq2_v0"}
    }
