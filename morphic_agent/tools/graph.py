"""Graph planning tool implementations."""

from __future__ import annotations

from typing import Any

from morphic_agent.contracts.envelopes import ToolResponse
from morphic_agent.graph.contracts import GraphIndex
from morphic_agent.graph.drafts import draft_workflow_graph, get_workflow_graph, graph_draft_message, graph_intent_supported
from morphic_agent.graph.index import MorphicGraphIndex
from morphic_agent.registry.catalog import ModuleCatalog


class GraphTools:
    def __init__(self, catalog: ModuleCatalog | None = None, graph_index: GraphIndex | None = None) -> None:
        self.catalog = catalog or ModuleCatalog()
        self.index = graph_index or MorphicGraphIndex(self.catalog)

    def find_candidate_graphs(self, problem_signature: dict[str, Any]) -> ToolResponse:
        graphs = self.index.find_candidate_graphs(problem_signature)
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="find_candidate_graphs",
            stable_id=f"candidates:{problem_signature.get('goal', '')}",
            status="ok" if graphs else "blocked",
            payload={"candidate_graphs": graphs},
            summary=f"Found {len(graphs)} candidate graph(s).",
            blockers=[] if graphs else ["No candidate graph matched the problem signature."],
        )

    def find_verified_subgraphs(self, problem_signature: dict[str, Any]) -> ToolResponse:
        graphs = self.index.find_verified_subgraphs(problem_signature)
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="find_verified_subgraphs",
            stable_id=f"verified:{problem_signature}",
            status="ok" if graphs else "blocked",
            payload={"verified_subgraphs": graphs},
            summary=f"Found {len(graphs)} verified subgraph(s).",
            blockers=[] if graphs else ["No verified subgraph matched the problem signature."],
        )

    def rebuild_graph_index(self, projection_version: str = "morphic-agent-v0") -> ToolResponse:
        manifest = self.index.rebuild_graph_index(projection_version)
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="rebuild_graph_index",
            stable_id=f"projection:{projection_version}",
            status="ok",
            payload=manifest,
            summary=(
                f"Rebuilt graph projection `{projection_version}` with "
                f"{manifest.get('projected_vertex_count', manifest.get('vertex_count', 0))} vertices."
            ),
        )

    def projection_status(self, projection_version: str = "morphic-agent-v0") -> ToolResponse:
        status = self.index.projection_status(projection_version)
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="projection_status",
            stable_id=f"projection:{projection_version}",
            status="ok" if status.get("status") not in {"missing", "unavailable"} else str(status.get("status")),
            payload=status,
            summary=f"Projection `{projection_version}` status is `{status.get('status')}`.",
            blockers=[status["run_blocker"]] if status.get("run_blocker") else [],
        )

    def draft_graph(self, goal: str, *, include_launchpad: bool = True) -> ToolResponse:
        if not graph_intent_supported(goal):
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="find_candidate_graphs",
                stable_id=f"draft:{goal}",
                status="planning",
                payload={"workflow_graph": None},
                summary="Clarify whether this is a DEG workflow or provide a supported target module.",
                blockers=["No supported graph draft matched the request."],
                required_human_decisions=["clarify assay, inputs, and desired outputs"],
            )
        graph = draft_workflow_graph(goal, self.catalog, include_launchpad=include_launchpad)
        store = getattr(self.index, "store", None)
        if store is not None:
            store.record_subgraph(graph, version="draft")
        else:
            graph = {
                **graph,
                "durability": "transient",
                "run_blocker": graph.get("run_blocker") or "Graph is not stored; store or re-draft before execution.",
            }
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="find_candidate_graphs",
            stable_id=f"graph:{graph['graph_id']}",
            status="graph_draft",
            payload={
                "graph_id": graph["graph_id"],
                "workflow_graph": graph,
                "params_schema": graph.get("params_schema"),
                "required_human_inputs": graph.get("required_human_inputs"),
                "materialization_status": graph.get("materialization_status"),
                "run_blocker": graph.get("run_blocker"),
            },
            summary=graph_draft_message(graph),
            evidence=graph.get("evidence") or [],
            confidence_tier=str(graph.get("confidence_tier") or "source_derived"),
            blockers=[str(graph.get("run_blocker") or "")],
        )

    def explain_candidate_graph(self, graph_id: str) -> ToolResponse:
        explanation = self.index.explain_candidate_graph(graph_id)
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="explain_candidate_graph",
            stable_id=f"graph:{graph_id}",
            status="ok",
            payload=explanation,
            summary=f"Graph `{graph_id}` has {len(explanation.get('nodes') or [])} node(s).",
            evidence=explanation.get("evidence") or [],
            confidence_tier=str(explanation.get("confidence_tier") or "source_derived"),
            blockers=[str(explanation.get("run_blocker") or "")] if explanation.get("run_blocker") else [],
        )

    def store_verified_recipe(self, graph_id: str, execution_manifest: dict[str, Any]) -> ToolResponse:
        try:
            graph = self.index.hydrate_graph(graph_id)
            result = self.index.store_verified_recipe(graph, execution_manifest)
        except (KeyError, ValueError) as exc:
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="store_verified_recipe",
                stable_id=f"verified:{graph_id}",
                status="blocked",
                payload={"graph_id": graph_id, "error": str(exc)},
                summary=f"Could not store verified recipe for `{graph_id}`.",
                blockers=[str(exc)],
            )
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="store_verified_recipe",
            stable_id=f"verified:{graph_id}",
            status="verified",
            payload=result,
            summary=f"Stored `{graph_id}` as a verified recipe.",
            confidence_tier=str((result.get("workflow_graph") or {}).get("confidence_tier") or "source_derived"),
        )

    def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        try:
            return self.index.hydrate_graph(graph_id)
        except (KeyError, ValueError):
            return get_workflow_graph(graph_id, self.catalog)
