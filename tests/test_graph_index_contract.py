"""GraphIndex runbook contract tests for the walking skeleton backend."""

from __future__ import annotations

import tempfile

from morphic_agent.graph.index import MorphicGraphIndex
from morphic_agent.graph.contracts import GraphIndex
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore
from morphic_agent.tools.graph import GraphTools


def _index() -> tuple[AgentStore, MorphicGraphIndex]:
    store = AgentStore(tempfile.mktemp(suffix=".sqlite3"))
    catalog = ModuleCatalog(store=store)
    return store, MorphicGraphIndex(catalog, store=store)


def test_graph_projection_rebuild_is_stored_behind_graph_index():
    store, index = _index()

    assert isinstance(index, GraphIndex)
    manifest = index.rebuild_graph_index("test-projection-v0")

    assert manifest["canonical_store"] == "postgres"
    assert manifest["graph_index"] == "arcadedb"
    assert manifest["projection_version"] == "test-projection-v0"
    assert manifest["projected_vertex_count"] > 0
    assert manifest["projected_edge_count"] > 0
    assert store.count_rows("graph_projection_vertices") == manifest["projected_vertex_count"]
    assert store.count_rows("graph_projection_edges") == manifest["projected_edge_count"]


def test_graph_index_finds_and_explains_deg_candidate_path():
    _, index = _index()

    candidates = index.find_candidate_paths(
        ["paired_fastq", "sample_metadata_table"],
        ["differential_expression_table"],
        {"capabilities": ["deg"]},
    )

    assert candidates
    assert candidates[0]["graph_id"] == "bulk_pe_deseq2_v0"
    assert index.find_missing_contracts(candidates[0]) == []
    explanation = index.explain_path("bulk_pe_deseq2_v0")
    assert explanation["graph_id"] == "bulk_pe_deseq2_v0"
    assert explanation["missing_contracts"] == []


def test_verified_recipe_promotion_is_queryable_by_exact_signature():
    store, index = _index()
    graph = index.hydrate_graph("bulk_pe_deseq2_v0")
    execution_manifest = {
        "schema": "morphic.local_execution_result/v0",
        "status": "verified",
        "graph_id": graph["graph_id"],
        "verified_recipe": True,
        "canonical_graph_hash": "test-canonical-hash",
        "output_contract_checks": [{"name": "deseq2_results", "exists": True}],
    }

    result = index.store_verified_recipe(graph, execution_manifest)
    matches = index.find_verified_subgraphs(
        {
            "requested_outputs": ["differential_expression_table"],
            "capabilities": ["deg"],
        }
    )

    assert result["lifecycle_state"] == "verified"
    assert store.count_rows("verified_recipes") == 1
    assert [item["graph_id"] for item in matches] == ["bulk_pe_deseq2_v0"]


class FakeGraphIndex:
    def __init__(self) -> None:
        self.graph = {
            "graph_id": "fake_graph_v0",
            "title": "Fake graph",
            "nodes": [],
            "edges": [],
            "confidence_tier": "source_derived",
            "materialization_status": "graph_draft_only",
        }

    def rebuild_graph_index(self, projection_version: str = "morphic-agent-v0"):
        return {"projection_version": projection_version, "projected_vertex_count": 0}

    def upsert_projection_batch(self, vertices, edges, *, projection_version: str = "morphic-agent-v0"):
        return {"projection_version": projection_version, "vertex_count": len(vertices), "edge_count": len(edges)}

    def projection_status(self, projection_version: str = "morphic-agent-v0"):
        return {"projection_version": projection_version, "status": "fake"}

    def find_candidate_graphs(self, problem_signature):
        return [self.graph]

    def find_verified_subgraphs(self, problem_signature):
        return []

    def find_near_match_subgraphs(self, problem_signature):
        return [self.graph]

    def find_candidate_paths(self, input_artifacts, requested_outputs, constraints=None):
        return [self.graph]

    def find_missing_contracts(self, candidate_graph):
        return []

    def rank_candidate_graphs(self, candidates, objective=None):
        return candidates

    def hydrate_graph(self, graph_id: str):
        return self.graph

    def explain_candidate_graph(self, graph_id: str):
        return self.graph

    def explain_path(self, path_id: str):
        return self.graph

    def store_verified_recipe(self, graph, execution_manifest):
        return {"graph_id": graph["graph_id"], "lifecycle_state": "verified"}


def test_graph_tools_depend_on_graph_index_protocol_not_concrete_adapter():
    fake_index = FakeGraphIndex()
    assert isinstance(fake_index, GraphIndex)

    response = GraphTools(graph_index=fake_index).find_candidate_graphs({"goal": "anything"})

    assert response.status == "ok"
    assert response.payload["candidate_graphs"][0]["graph_id"] == "fake_graph_v0"
