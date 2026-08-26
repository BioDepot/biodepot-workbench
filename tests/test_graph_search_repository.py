"""Relational graph search repository tests."""

from __future__ import annotations

import json
from pathlib import Path

from morphic_agent.registry.store import AgentStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "graph_search"


def _load_graph(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _seed_store(tmp_path: Path) -> AgentStore:
    store = AgentStore(tmp_path / "search.sqlite3")
    for name in (
        "trimodal_qc_graph.json",
        "chromap_hic_graph.json",
        "chromap_chip_graph.json",
        "bulk_deseq2_graph.json",
        "celltyping_graph.json",
    ):
        store.record_subgraph(_load_graph(name), version="fixture")
    verified = {
        "schema": "morphic.workflow_graph/v0",
        "graph_id": "verified_placeholder_v0",
        "title": "Verified placeholder graph",
        "nodes": [],
        "edges": [],
        "inputs": [{"name": "input", "artifact_type": "txt", "required": True}],
        "outputs": [{"name": "output", "artifact_type": "json"}],
        "capabilities": ["verified_smoke"],
    }
    verified["lifecycle_state"] = "verified"
    verified["materialization_status"] = "verified_recipe"
    store.record_subgraph(verified, version="verified")
    return store


def test_trimodal_qc_query_ranks_trimodal_first(tmp_path: Path):
    store = _seed_store(tmp_path)

    results = store.search_graphs(query="trimodal qc h5mu")

    assert results["status"] == "ok"
    assert results["results"][0]["graph_id"] == "trimodal_qc_report_v0"
    assert results["results"][0]["match_reasons"]


def test_h5mu_input_and_html_json_outputs_find_trimodal_report(tmp_path: Path):
    store = _seed_store(tmp_path)

    results = store.search_graphs(
        filters={
            "input_artifact_types": ["h5mu"],
            "output_artifact_types": ["html", "json"],
            "runnable_only": True,
        }
    )

    assert [item["graph_id"] for item in results["results"] if item["graph_id"] == "trimodal_qc_report_v0"]
    assert all(item["runnable"] for item in results["results"])


def test_hic_modality_finds_chromap_hic_not_trimodal_or_example_atac(tmp_path: Path):
    store = _seed_store(tmp_path)

    results = store.search_graphs(query="hic", filters={"modalities": ["hic"]})
    graph_ids = {item["graph_id"] for item in results["results"]}

    assert "chromap_hic_pairs_v0" in graph_ids
    assert "trimodal_qc_report_v0" not in graph_ids
    assert all("cat" not in graph_id.lower() for graph_id in graph_ids)


def test_chip_modality_finds_chromap_chip_when_present(tmp_path: Path):
    store = _seed_store(tmp_path)

    results = store.search_graphs(query="chip-seq", filters={"modalities": ["chip-seq"]})

    assert [item["graph_id"] for item in results["results"]] == ["chromap_chip_tagalign_v0"]


def test_bulk_deg_and_cell_typing_capability_filters(tmp_path: Path):
    store = _seed_store(tmp_path)

    deg = store.search_graphs(query="bulk RNA-seq DEG", filters={"capabilities": ["deg"]})
    celltyping = store.search_graphs(query="cell typing", filters={"capabilities": ["cell_typing"]})

    assert deg["results"][0]["graph_id"] == "bulk_pe_deseq2_v0"
    assert celltyping["results"][0]["graph_id"] == "single_cell_celltyping_v0"


def test_runnable_and_verified_filters_exclude_nonmatching_graphs(tmp_path: Path):
    store = _seed_store(tmp_path)

    runnable = store.search_graphs(filters={"runnable_only": True})
    verified = store.search_graphs(filters={"verified_only": True})

    assert "single_cell_celltyping_v0" not in {item["graph_id"] for item in runnable["results"]}
    assert [item["graph_id"] for item in verified["results"]] == ["verified_placeholder_v0"]


def test_unknown_query_returns_empty_ok_result(tmp_path: Path):
    store = _seed_store(tmp_path)

    results = store.search_graphs(query="zzzz_unmatched_token")

    assert results["status"] == "ok"
    assert results["results"] == []
    assert results["result_count"] == 0
