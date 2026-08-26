"""Graph projection service boundary.

The canonical graph registry stays in the relational store. This module builds
the disposable graph-engine projection from those canonical records, then hands
the batch to the configured projection repository.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from morphic_agent.registry.repositories import ProjectionRepository
from morphic_agent.registry.store import AgentStore


@dataclass
class GraphProjectionService:
    store: AgentStore
    projection_repository: ProjectionRepository | None = None

    def __post_init__(self) -> None:
        if self.projection_repository is None:
            self.projection_repository = self.store.projection_repository

    def rebuild_projection(self, projection_version: str = "morphic-agent-v0", *, dry_run: bool = False) -> dict[str, Any]:
        projection_version = str(projection_version or "morphic-agent-v0")
        batch = self.build_projection_batch(projection_version)
        manifest = {
            "schema": "morphic.graph_projection_manifest/v0",
            "projection_version": projection_version,
            "canonical_store": "postgres",
            "graph_index": "arcadedb",
            "projection_adapter": getattr(self.projection_repository, "adapter_name", "unknown"),
            "source_counts": batch["source_counts"],
            "projected_vertex_count": len(batch["vertices"]),
            "projected_edge_count": len(batch["edges"]),
        }
        if dry_run:
            return {**manifest, "status": "dry_run", "mutated": False}
        assert self.projection_repository is not None
        return self.projection_repository.rebuild_projection(
            projection_version=projection_version,
            vertices=batch["vertices"],
            edges=batch["edges"],
            manifest=manifest,
        )

    def upsert_projection_batch(
        self,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        projection_version: str = "morphic-agent-v0",
    ) -> dict[str, Any]:
        assert self.projection_repository is not None
        return self.projection_repository.upsert_projection_batch(
            vertices,
            edges,
            projection_version=projection_version,
        )

    def projection_status(self, projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        assert self.projection_repository is not None
        return self.projection_repository.projection_status(projection_version)

    def build_projection_batch(self, projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        projection_version = str(projection_version or "morphic-agent-v0")
        vertices: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}

        modules = self.store.list_module_contracts()
        graphs = self.store.graph_repository.list_graphs()
        compatibility_edges = self.store.list_compatibility_edges()
        verified_recipes = self.store.list_verified_recipes()

        for module in modules:
            module_id = str(module.get("module_id") or "").strip()
            if not module_id:
                continue
            runtime = module.get("runtime") if isinstance(module.get("runtime"), dict) else {}
            _add_vertex(
                vertices,
                f"module:{module_id}",
                label=str(module.get("title") or module_id),
                kind="Module",
                properties={
                    "module_id": module_id,
                    "confidence_tier": module.get("confidence_tier"),
                    "runtime_kind": runtime.get("kind"),
                    "projection_version": projection_version,
                },
            )
            if runtime.get("kind"):
                runtime_id = f"runtime:{runtime['kind']}"
                _add_vertex(vertices, runtime_id, label=str(runtime["kind"]), kind="Runtime", properties={})
                _add_edge(edges, f"module:{module_id}", runtime_id, "SUPPORTS_RUNTIME", projection_version=projection_version)
            for item in module.get("inputs") or []:
                if isinstance(item, dict) and item.get("artifact_type"):
                    artifact_id = _artifact_vertex(vertices, str(item["artifact_type"]))
                    _add_edge(
                        edges,
                        artifact_id,
                        f"module:{module_id}",
                        "CONSUMES",
                        artifact_type=str(item["artifact_type"]),
                        projection_version=projection_version,
                    )
            for item in module.get("outputs") or []:
                if isinstance(item, dict) and item.get("artifact_type"):
                    artifact_id = _artifact_vertex(vertices, str(item["artifact_type"]))
                    _add_edge(
                        edges,
                        f"module:{module_id}",
                        artifact_id,
                        "PRODUCES",
                        artifact_type=str(item["artifact_type"]),
                        projection_version=projection_version,
                    )
            for capability in _string_list(module.get("capabilities")):
                capability_id = f"capability:{capability}"
                _add_vertex(vertices, capability_id, label=capability, kind="Capability", properties={})
                _add_edge(edges, f"module:{module_id}", capability_id, "HAS_CAPABILITY", projection_version=projection_version)
            for modality in _string_list(module.get("modalities")):
                modality_id = f"modality:{modality}"
                _add_vertex(vertices, modality_id, label=modality, kind="Modality", properties={})
                _add_edge(edges, f"module:{module_id}", modality_id, "HAS_MODALITY", projection_version=projection_version)

        for record in graphs:
            graph_id = str(record.get("graph_id") or "").strip()
            version_id = str(record.get("version_id") or "").strip()
            if not graph_id or not version_id:
                continue
            graph_vertex_id = f"graph:{graph_id}"
            version_vertex_id = f"graph_version:{version_id}"
            _add_vertex(
                vertices,
                graph_vertex_id,
                label=str(record.get("title") or graph_id),
                kind="Graph",
                properties={
                    "graph_id": graph_id,
                    "suite": record.get("suite"),
                    "recipe_family": record.get("recipe_family"),
                    "assay_profile": record.get("assay_profile"),
                    "lifecycle_state": record.get("lifecycle_state"),
                    "materialization_status": record.get("materialization_status"),
                    "runnable": bool(record.get("runnable")),
                    "verified": bool(record.get("verified")),
                },
            )
            _add_vertex(
                vertices,
                version_vertex_id,
                label=f"{graph_id}@{record.get('version') or 'current'}",
                kind="GraphVersion",
                properties={
                    "graph_id": graph_id,
                    "version_id": version_id,
                    "canonical_graph_hash": record.get("canonical_graph_hash"),
                    "projection_version": projection_version,
                },
            )
            _add_edge(edges, graph_vertex_id, version_vertex_id, "HAS_VERSION", projection_version=projection_version)
            graph = record.get("graph") if isinstance(record.get("graph"), dict) else {}
            runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
            if runtime.get("kind"):
                runtime_id = f"runtime:{runtime['kind']}"
                _add_vertex(vertices, runtime_id, label=str(runtime["kind"]), kind="Runtime", properties={})
                _add_edge(edges, version_vertex_id, runtime_id, "SUPPORTS_RUNTIME", projection_version=projection_version)
            for node in graph.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                module_id = str(node.get("module_id") or node.get("id") or "").strip()
                if not module_id:
                    continue
                module_vertex_id = f"module:{module_id}"
                _add_vertex(
                    vertices,
                    module_vertex_id,
                    label=str(node.get("label") or module_id),
                    kind="Module",
                    properties={"module_id": module_id},
                )
                _add_edge(edges, version_vertex_id, module_vertex_id, "USES_MODULE", projection_version=projection_version)
            for artifact_type in _string_list(record.get("inputs")):
                artifact_id = _artifact_vertex(vertices, artifact_type)
                _add_edge(edges, version_vertex_id, artifact_id, "CONSUMES", artifact_type=artifact_type, projection_version=projection_version)
            for artifact_type in _string_list(record.get("outputs")):
                artifact_id = _artifact_vertex(vertices, artifact_type)
                _add_edge(edges, version_vertex_id, artifact_id, "PRODUCES", artifact_type=artifact_type, projection_version=projection_version)
            for capability in _string_list(record.get("capabilities")):
                capability_id = f"capability:{capability}"
                _add_vertex(vertices, capability_id, label=capability, kind="Capability", properties={})
                _add_edge(edges, version_vertex_id, capability_id, "HAS_CAPABILITY", projection_version=projection_version)
            for modality in _string_list(record.get("modalities")):
                modality_id = f"modality:{modality}"
                _add_vertex(vertices, modality_id, label=modality, kind="Modality", properties={})
                _add_edge(edges, version_vertex_id, modality_id, "HAS_MODALITY", projection_version=projection_version)
            for execution_location in _string_list(record.get("execution_locations")):
                location_id = f"execution_location:{execution_location}"
                _add_vertex(vertices, location_id, label=execution_location, kind="ExecutionLocation", properties={})
                _add_edge(edges, version_vertex_id, location_id, "SUPPORTS_EXECUTION", projection_version=projection_version)

        for edge in compatibility_edges:
            source = f"module:{edge['source_module_id']}"
            target = f"module:{edge['target_module_id']}"
            _add_edge(
                edges,
                source,
                target,
                "COMPATIBLE_WITH",
                artifact_type=edge.get("artifact_type"),
                projection_version=projection_version,
                properties={
                    "compatibility_edge_id": edge.get("edge_id"),
                    "source_output": edge.get("source_output"),
                    "target_input": edge.get("target_input"),
                    "confidence_tier": edge.get("confidence_tier"),
                },
            )

        for verified in verified_recipes:
            verification_id = f"verification:{verified['verified_recipe_id']}"
            graph_id = str(verified.get("graph_id") or "")
            _add_vertex(
                vertices,
                verification_id,
                label=str(verified.get("verified_recipe_id")),
                kind="Verification",
                properties={
                    "verified_recipe_id": verified.get("verified_recipe_id"),
                    "graph_id": graph_id,
                    "canonical_graph_hash": verified.get("canonical_graph_hash"),
                    "created_at": verified.get("created_at"),
                },
            )
            if graph_id:
                _add_edge(edges, f"graph:{graph_id}", verification_id, "VERIFIED_BY", projection_version=projection_version)

        return {
            "schema": "morphic.graph_projection_batch/v0",
            "projection_version": projection_version,
            "vertices": list(vertices.values()),
            "edges": list(edges.values()),
            "source_counts": {
                "modules": len(modules),
                "graphs": len(graphs),
                "compatibility_edges": len(compatibility_edges),
                "verified_recipes": len(verified_recipes),
            },
        }


class ArcadeDBProjectionRepository:
    """Opt-in placeholder adapter kept behind the projection boundary.

    The first production tranche uses the SQLite projection adapter for local
    tests and staged deployment. A real ArcadeDB client can implement the same
    methods without changing WorkbenchService or MorphicGraphIndex.
    """

    adapter_name = "arcadedb"

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint or os.environ.get("MORPHIC_ARCADEDB_URL")
        if not self.endpoint:
            raise RuntimeError("MORPHIC_ARCADEDB_URL is required for the ArcadeDB projection adapter.")


def _artifact_vertex(vertices: dict[str, dict[str, Any]], artifact_type: str) -> str:
    artifact_id = f"artifact:{artifact_type}"
    _add_vertex(vertices, artifact_id, label=artifact_type, kind="ArtifactType", properties={"artifact_type": artifact_type})
    return artifact_id


def _add_vertex(
    vertices: dict[str, dict[str, Any]],
    vertex_id: str,
    *,
    label: str,
    kind: str,
    properties: dict[str, Any],
) -> None:
    if vertex_id in vertices:
        existing = vertices[vertex_id]
        merged = {**dict(existing.get("properties") or {}), **properties}
        existing["properties"] = {key: value for key, value in merged.items() if value is not None}
        if not existing.get("label"):
            existing["label"] = label
        return
    vertices[vertex_id] = {
        "id": vertex_id,
        "label": label,
        "kind": kind,
        "properties": {key: value for key, value in properties.items() if value is not None},
    }


def _add_edge(
    edges: dict[str, dict[str, Any]],
    source: str,
    target: str,
    label: str,
    *,
    artifact_type: str | None = None,
    projection_version: str,
    properties: dict[str, Any] | None = None,
) -> None:
    payload = {"source": source, "target": target, "label": label, "artifact_type": artifact_type}
    edge_id = f"edge-{_sha256_json(payload)[:20]}"
    edge_properties = {"projection_version": projection_version, **(properties or {})}
    edges[edge_id] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "label": label,
        "artifact_type": artifact_type,
        "properties": {key: value for key, value in edge_properties.items() if value is not None},
    }


def _string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = [values]
    out: list[str] = []
    for value in raw_values:
        text = str(value or "").strip().lower()
        if text and text not in out:
            out.append(text)
    return out


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
