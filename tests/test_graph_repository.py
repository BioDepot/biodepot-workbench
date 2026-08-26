"""Canonical graph repository tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from morphic_agent.registry.store import AgentStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "graph_search"


def _load_graph(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_graph_upsert_is_idempotent_for_same_canonical_hash(tmp_path: Path):
    store = AgentStore(tmp_path / "graphs.sqlite3")
    graph = _load_graph("trimodal_qc_graph.json")

    first = store.record_subgraph(graph, version="fixture")
    second = store.record_subgraph(graph, version="fixture")

    assert second == first
    assert store.count_rows("workflow_graphs") == 1
    assert store.count_rows("workflow_graph_versions") == 1
    assert store.count_rows("workflow_graph_inputs") == 1
    assert store.count_rows("workflow_graph_outputs") == 2
    assert store.get_subgraph("trimodal_qc_report_v0")["title"] == graph["title"]


def test_new_canonical_hash_creates_new_graph_version_and_updates_current_pointer(tmp_path: Path):
    store = AgentStore(tmp_path / "graphs.sqlite3")
    graph = _load_graph("bulk_deseq2_graph.json")
    first = store.record_subgraph(graph, version="fixture")
    updated = copy.deepcopy(graph)
    updated["outputs"].append({"name": "normalized_counts", "artifact_type": "normalized_count_matrix"})

    second = store.record_subgraph(updated, version="fixture")
    current = store.get_subgraph("bulk_pe_deseq2_v0")

    assert second["version_id"] != first["version_id"]
    assert store.count_rows("workflow_graphs") == 1
    assert store.count_rows("workflow_graph_versions") == 2
    assert current["outputs"][-1]["artifact_type"] == "normalized_count_matrix"


def test_normalized_graph_facets_and_lifecycle_are_preserved(tmp_path: Path):
    store = AgentStore(tmp_path / "graphs.sqlite3")
    graph = _load_graph("chromap_hic_graph.json")
    result = store.record_subgraph(graph, version="fixture")

    with store._connect() as conn:
        version = conn.execute(
            "SELECT * FROM workflow_graph_versions WHERE version_id=?",
            (result["version_id"],),
        ).fetchone()
        inputs = conn.execute(
            "SELECT artifact_type FROM workflow_graph_inputs WHERE version_id=? ORDER BY artifact_type",
            (result["version_id"],),
        ).fetchall()
        modalities = conn.execute(
            "SELECT modality FROM workflow_graph_modalities WHERE version_id=?",
            (result["version_id"],),
        ).fetchall()

    assert version["lifecycle_state"] == "candidate"
    assert version["materialization_status"] == "suite_recipe_declared"
    assert [row["artifact_type"] for row in inputs] == ["chromap_index", "fasta", "fastq"]
    assert [row["modality"] for row in modalities] == ["hic"]
    stored = store.get_subgraph("chromap_hic_pairs_v0")
    assert stored is not None
    for key, value in graph.items():
        assert stored[key] == value
    assert stored["canonical_graph_hash"] == result["canonical_graph_hash"]
    assert stored["validation_statuses"] == []
    assert stored["latest_validation"] is None
