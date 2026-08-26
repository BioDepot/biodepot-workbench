"""Graph planning interfaces independent of the backing graph database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

GraphPayload = dict[str, Any]
ProblemSignature = dict[str, Any]
ProjectionManifest = dict[str, Any]


@dataclass(frozen=True)
class ProjectionBatch:
    """Disposable graph projection payload.

    Production adapters can compile this to ArcadeDB vertices/edges. Tests and
    local development can persist the same shape in SQLite without changing the
    planner or tool layer.
    """

    projection_version: str
    vertices: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class GraphIndex(Protocol):
    """Stable graph-search boundary for planner and tools.

    Implementations may be backed by ArcadeDB, an in-memory projection, SQLite
    test tables, or another graph engine. Planner code should not depend on
    database-specific query languages.
    """

    def rebuild_graph_index(self, projection_version: str = "morphic-agent-v0") -> ProjectionManifest:
        ...

    def upsert_projection_batch(
        self,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        projection_version: str = "morphic-agent-v0",
    ) -> dict[str, Any]:
        ...

    def projection_status(self, projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        ...

    def find_candidate_graphs(self, problem_signature: ProblemSignature) -> list[GraphPayload]:
        ...

    def find_verified_subgraphs(self, problem_signature: ProblemSignature) -> list[GraphPayload]:
        ...

    def find_near_match_subgraphs(self, problem_signature: ProblemSignature) -> list[GraphPayload]:
        ...

    def find_candidate_paths(
        self,
        input_artifacts: list[str],
        requested_outputs: list[str],
        constraints: dict[str, Any] | None = None,
    ) -> list[GraphPayload]:
        ...

    def find_missing_contracts(self, candidate_graph: GraphPayload) -> list[dict[str, Any]]:
        ...

    def rank_candidate_graphs(
        self,
        candidates: list[GraphPayload],
        objective: dict[str, Any] | None = None,
    ) -> list[GraphPayload]:
        ...

    def hydrate_graph(self, graph_id: str) -> GraphPayload:
        ...

    def explain_candidate_graph(self, graph_id: str) -> dict[str, Any]:
        ...

    def explain_path(self, path_id: str) -> dict[str, Any]:
        ...

    def store_verified_recipe(self, graph: GraphPayload, execution_manifest: dict[str, Any]) -> dict[str, Any]:
        ...
