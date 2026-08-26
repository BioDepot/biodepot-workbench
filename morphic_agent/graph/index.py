"""GraphIndex adapter — ArcadeDB-shaped API over in-memory projection for the walking skeleton."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from morphic_front.graph_mvp import InMemoryGraphIndex, build_star_mvp_graph_index, plan_star_mvp_composition

from morphic_agent.graph.contracts import GraphIndex
from morphic_agent.graph.drafts import draft_workflow_graph, get_workflow_graph, graph_intent_supported
from morphic_agent.graph.projection import GraphProjectionService
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore

BUILTIN_WORKFLOW_GRAPH_IDS = (
    "bulk_pe_deseq2_v0",
    "bulk_pe_deseq2_plots_v0",
    "trimodal_qc_report_v0",
    "example_perturb_visualization_suite_v0",
)


class MorphicGraphIndex(GraphIndex):
    """Production GraphIndex facade used by planner and tools."""

    def __init__(
        self,
        catalog: ModuleCatalog | None = None,
        star_root: str | None = None,
        *,
        store: AgentStore | None = None,
    ) -> None:
        self.catalog = catalog or ModuleCatalog()
        self.store = store
        self.star_index = build_star_mvp_graph_index(star_root) if star_root else build_star_mvp_graph_index()
        self.projection_service = GraphProjectionService(store) if store is not None else None
        self._draft_cache: dict[str, dict[str, Any]] = {}
        self._seed_canonical_graphs()

    def _seed_canonical_graphs(self) -> None:
        if self.store is None:
            return
        for graph_id in BUILTIN_WORKFLOW_GRAPH_IDS:
            graph = get_workflow_graph(graph_id, self.catalog)
            if graph:
                self.store.record_subgraph(graph, version="builtin")
        for graph in self.star_index.subgraphs.values():
            self.store.record_subgraph(graph.as_dict(), version="star-mvp")

    @staticmethod
    def _canonical_hash(payload: Any) -> str:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def rebuild_graph_index(self, projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        manifest = self.star_index.rebuild_graph_index()
        if self.store is not None and self.projection_service is not None:
            self.store.rebuild_compatibility_edges()
            result = self.projection_service.rebuild_projection(projection_version)
            result["star_projection_manifest"] = manifest
            result["transcriptomics_graphs"] = [
                "bulk_pe_deseq2_v0",
                "bulk_pe_deseq2_plots_v0",
                "trimodal_qc_report_v0",
                "example_perturb_visualization_suite_v0",
            ]
            return result
        manifest["transcriptomics_graphs"] = [
            "bulk_pe_deseq2_v0",
            "bulk_pe_deseq2_plots_v0",
            "trimodal_qc_report_v0",
            "example_perturb_visualization_suite_v0",
        ]
        manifest["projection_version"] = projection_version
        manifest.setdefault("projected_vertex_count", len(self.star_index.vertices))
        manifest.setdefault("projected_edge_count", len(self.star_index.edges))
        return manifest

    def projection_status(self, projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        if self.projection_service is None:
            return {
                "schema": "morphic.graph_projection_status/v0",
                "status": "unavailable",
                "projection_version": projection_version,
                "run_blocker": "No canonical store is configured for projection status.",
            }
        return self.projection_service.projection_status(projection_version)

    def upsert_projection_batch(
        self,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        projection_version: str = "morphic-agent-v0",
    ) -> dict[str, Any]:
        if self.store is None:
            return {"projection_version": projection_version, "vertex_count": len(vertices), "edge_count": len(edges), "stored": False}
        if self.projection_service is not None:
            result = self.projection_service.upsert_projection_batch(vertices, edges, projection_version=projection_version)
        else:
            result = self.store.upsert_projection_batch(vertices, edges, projection_version=projection_version)
        result["stored"] = True
        return result

    def find_candidate_graphs(self, problem_signature: dict[str, Any]) -> list[dict[str, Any]]:
        goal = str(problem_signature.get("goal") or "")
        if graph_intent_supported(goal):
            graph = draft_workflow_graph(goal, self.catalog)
            self._draft_cache[graph["graph_id"]] = copy.deepcopy(graph)
            if self.store is not None:
                self.store.record_subgraph(graph, version="draft")
            return [graph]
        return self.find_candidate_paths(
            problem_signature.get("input_artifacts") or [],
            problem_signature.get("requested_outputs") or [],
            {"capabilities": problem_signature.get("capabilities") or []},
        )

    def find_verified_subgraphs(self, problem_signature: dict[str, Any]) -> list[dict[str, Any]]:
        requested = set(problem_signature.get("requested_outputs") or [])
        capabilities = set(problem_signature.get("capabilities") or [])
        matches: list[dict[str, Any]] = []
        if self.store is not None:
            for item in self.store.list_verified_recipes():
                graph = copy.deepcopy(item["graph"])
                outputs = {str(output.get("artifact_type")) for output in graph.get("outputs") or [] if isinstance(output, dict)}
                graph_caps = set(graph.get("capabilities") or [])
                if requested and not requested <= outputs:
                    continue
                if capabilities and not capabilities <= graph_caps:
                    continue
                graph["verified_recipe_id"] = item["verified_recipe_id"]
                matches.append(graph)
        for graph in self.star_index.find_verified_subgraphs(problem_signature):
            payload = graph.as_dict()
            if payload["graph_id"] not in {item.get("graph_id") for item in matches}:
                matches.append(payload)
        return self.rank_candidate_graphs(matches, {"prefer_verified": True})

    def find_near_match_subgraphs(self, problem_signature: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = self.find_candidate_paths(
            problem_signature.get("input_artifacts") or [],
            problem_signature.get("requested_outputs") or [],
            {"capabilities": problem_signature.get("capabilities") or []},
        )
        verified_ids = {item.get("graph_id") for item in self.find_verified_subgraphs(problem_signature)}
        return [candidate for candidate in candidates if candidate.get("graph_id") not in verified_ids]

    def find_candidate_paths(
        self,
        input_artifacts: list[str],
        requested_outputs: list[str],
        constraints: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        candidates = [item.as_dict() for item in self.star_index.find_candidate_paths(input_artifacts, requested_outputs, constraints or {})]
        candidates.extend(self._stored_subgraph_candidates(input_artifacts, requested_outputs, constraints or {}))
        candidates.extend(self._compatibility_path_candidates(input_artifacts, requested_outputs, constraints or {}))
        for graph_id in BUILTIN_WORKFLOW_GRAPH_IDS:
            graph = get_workflow_graph(graph_id, self.catalog)
            if not graph:
                continue
            graph_outputs = {str(item.get("artifact_type")) for item in graph.get("outputs") or [] if isinstance(item, dict)}
            graph_inputs = {str(item.get("artifact_type")) for item in graph.get("inputs") or [] if isinstance(item, dict)}
            graph_caps = set(graph.get("capabilities") or [])
            capabilities = set((constraints or {}).get("capabilities") or [])
            if input_artifacts and graph_inputs and not set(input_artifacts) <= graph_inputs:
                continue
            if requested_outputs and graph_outputs and not set(requested_outputs) <= graph_outputs:
                continue
            if capabilities and graph_caps and not capabilities <= graph_caps:
                continue
            if graph["graph_id"] not in {item.get("graph_id") for item in candidates}:
                candidates.append(graph)
        objective = {
            **(constraints or {}),
            "input_artifacts": input_artifacts or [],
            "requested_outputs": requested_outputs or [],
        }
        return self.rank_candidate_graphs(candidates, objective)

    def hydrate_graph(self, graph_id: str) -> dict[str, Any]:
        if graph_id in self._draft_cache:
            return copy.deepcopy(self._draft_cache[graph_id])
        if self.store is not None:
            for item in self.store.list_verified_recipes():
                if item["graph_id"] == graph_id:
                    return copy.deepcopy(item["graph"])
            graph = self.store.get_subgraph(graph_id)
            if graph:
                return copy.deepcopy(graph)
        workflow = get_workflow_graph(graph_id, self.catalog)
        if workflow:
            return workflow
        return self.star_index.hydrate_graph(graph_id).as_dict()

    def _stored_subgraph_candidates(
        self,
        input_artifacts: list[str],
        requested_outputs: list[str],
        constraints: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self.store is None:
            return []
        capabilities = set(constraints.get("capabilities") or [])
        requested = set(requested_outputs or [])
        inputs = set(input_artifacts or [])
        out: list[dict[str, Any]] = []
        for item in self.store.list_subgraphs():
            graph = copy.deepcopy(item["graph"])
            graph_outputs = {
                str(output.get("artifact_type"))
                for output in graph.get("outputs") or []
                if isinstance(output, dict) and output.get("artifact_type")
            }
            graph_inputs = {
                str(input_item.get("artifact_type"))
                for input_item in graph.get("inputs") or []
                if isinstance(input_item, dict) and input_item.get("artifact_type")
            }
            graph_caps = set(graph.get("capabilities") or [])
            if requested and not requested <= graph_outputs:
                continue
            if inputs and graph_inputs and not inputs <= graph_inputs:
                continue
            if capabilities and graph_caps and not capabilities <= graph_caps:
                continue
            graph["subgraph_version_id"] = item["version_id"]
            out.append(graph)
        return out

    def _compatibility_path_candidates(
        self,
        input_artifacts: list[str],
        requested_outputs: list[str],
        constraints: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self.store is None or not input_artifacts or not requested_outputs:
            return []
        modules = {
            str(item.get("module_id") or ""): self.catalog.get_module(str(item.get("module_id") or ""))
            for item in self.catalog.list_modules()
            if item.get("module_id")
        }
        modules = {module_id: module for module_id, module in modules.items() if module and module.get("outputs")}
        compatibility_edges = self.store.list_compatibility_edges()
        edges_by_target: dict[str, list[dict[str, Any]]] = {}
        for edge in compatibility_edges:
            edges_by_target.setdefault(str(edge["target_module_id"]), []).append(edge)
        useful_modules = self._useful_modules_for_requested(modules, compatibility_edges, set(requested_outputs or []))

        initial_artifacts = set(input_artifacts or [])
        requested = set(requested_outputs or [])
        capability_filter = set(constraints.get("capabilities") or [])
        states = [
            {
                "module_ids": [],
                "available": set(initial_artifacts),
                "edges": [],
            }
        ]
        out: list[dict[str, Any]] = []
        seen_graphs: set[str] = set()
        max_depth = int(constraints.get("max_depth") or 4)

        for _ in range(max_depth):
            next_states: list[dict[str, Any]] = []
            for state in states:
                selected = set(state["module_ids"])
                available = set(state["available"])
                for module_id in sorted(modules):
                    if module_id in selected:
                        continue
                    if useful_modules and module_id not in useful_modules:
                        continue
                    module = modules[module_id] or {}
                    required_inputs = [
                        item
                        for item in module.get("inputs") or []
                        if isinstance(item, dict) and item.get("required") and item.get("artifact_type")
                    ]
                    required_artifacts = {str(item["artifact_type"]) for item in required_inputs}
                    if required_artifacts and not required_artifacts <= available:
                        continue
                    connecting_edges = self._connecting_edges_for_module(
                        module_id,
                        required_artifacts,
                        initial_artifacts,
                        selected,
                        edges_by_target,
                    )
                    if not self._required_artifacts_connected(required_artifacts, initial_artifacts, connecting_edges):
                        continue
                    output_artifacts = {
                        str(item.get("artifact_type"))
                        for item in module.get("outputs") or []
                        if isinstance(item, dict) and item.get("artifact_type")
                    }
                    if not output_artifacts:
                        continue
                    if not required_artifacts and not (output_artifacts & requested):
                        continue
                    if output_artifacts <= available:
                        continue
                    module_ids = [*state["module_ids"], module_id]
                    candidate_state = {
                        "module_ids": module_ids,
                        "available": available | output_artifacts,
                        "edges": [*state["edges"], *connecting_edges],
                    }
                    graph_caps = set()
                    for selected_module_id in module_ids:
                        graph_caps.update(modules[selected_module_id].get("capabilities") or [])
                    requested_satisfied = requested <= candidate_state["available"]
                    capabilities_satisfied = not capability_filter or capability_filter <= graph_caps
                    if requested_satisfied and capabilities_satisfied:
                        if len(module_ids) > 1:
                            graph = self._composition_graph_from_modules(module_ids, candidate_state["edges"], modules)
                            graph_key = str(graph.get("graph_id"))
                            if graph_key not in seen_graphs:
                                seen_graphs.add(graph_key)
                                self._draft_cache[graph_key] = copy.deepcopy(graph)
                                out.append(graph)
                                if len(out) >= 25:
                                    return out
                        continue
                    next_states.append(candidate_state)
            states = next_states[:100]
            if not states:
                break
        return out

    @staticmethod
    def _useful_modules_for_requested(
        modules: dict[str, dict[str, Any]],
        compatibility_edges: list[dict[str, Any]],
        requested_outputs: set[str],
    ) -> set[str]:
        if not requested_outputs:
            return set()
        useful = {
            module_id
            for module_id, module in modules.items()
            if requested_outputs
            & {
                str(output.get("artifact_type"))
                for output in module.get("outputs") or []
                if isinstance(output, dict) and output.get("artifact_type")
            }
        }
        changed = True
        while changed:
            changed = False
            for edge in compatibility_edges:
                source = str(edge.get("source_module_id") or "")
                target = str(edge.get("target_module_id") or "")
                if target in useful and source and source not in useful:
                    useful.add(source)
                    changed = True
        return useful

    @staticmethod
    def _connecting_edges_for_module(
        module_id: str,
        required_artifacts: set[str],
        initial_artifacts: set[str],
        selected_module_ids: set[str],
        edges_by_target: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for artifact_type in sorted(required_artifacts - initial_artifacts):
            edge = next(
                (
                    item
                    for item in edges_by_target.get(module_id, [])
                    if item["artifact_type"] == artifact_type and item["source_module_id"] in selected_module_ids
                ),
                None,
            )
            if edge:
                out.append(edge)
        return out

    @staticmethod
    def _required_artifacts_connected(
        required_artifacts: set[str],
        initial_artifacts: set[str],
        connecting_edges: list[dict[str, Any]],
    ) -> bool:
        connected = set(initial_artifacts)
        connected.update(str(edge["artifact_type"]) for edge in connecting_edges)
        return required_artifacts <= connected

    def _composition_graph_from_modules(
        self,
        module_ids: list[str],
        compatibility_edges: list[dict[str, Any]],
        modules: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        hash_payload = {
            "module_ids": module_ids,
            "edges": [
                {
                    "source": edge["source_module_id"],
                    "target": edge["target_module_id"],
                    "artifact_type": edge["artifact_type"],
                    "source_output": edge["source_output"],
                    "target_input": edge["target_input"],
                }
                for edge in compatibility_edges
            ],
        }
        graph_id = f"composed_{self._canonical_hash(hash_payload)[:12]}_v0"
        produced = {
            str(output.get("artifact_type"))
            for module_id in module_ids
            for output in modules[module_id].get("outputs") or []
            if isinstance(output, dict) and output.get("artifact_type")
        }
        inputs = []
        input_keys: set[tuple[str, str]] = set()
        for module_id in module_ids:
            for item in modules[module_id].get("inputs") or []:
                if not isinstance(item, dict) or not item.get("artifact_type"):
                    continue
                if item["artifact_type"] in produced:
                    continue
                key = (str(item.get("name") or ""), str(item["artifact_type"]))
                if key in input_keys:
                    continue
                input_keys.add(key)
                inputs.append(item)
        outputs = []
        output_keys: set[tuple[str, str]] = set()
        for module_id in module_ids:
            for item in modules[module_id].get("outputs") or []:
                if not isinstance(item, dict) or not item.get("artifact_type"):
                    continue
                key = (str(item.get("name") or ""), str(item["artifact_type"]))
                if key in output_keys:
                    continue
                output_keys.add(key)
                outputs.append(item)
        capabilities = sorted(
            {
                str(capability)
                for module_id in module_ids
                for capability in modules[module_id].get("capabilities") or []
            }
        )
        return {
            "schema": "morphic.workflow_graph/v0",
            "graph_id": graph_id,
            "title": "Composed suite recipe path",
            "description": "Source-derived composed candidate assembled from SQLite compatibility edges.",
            "nodes": [
                {
                    "id": module_id,
                    "kind": "module",
                    "module_id": module_id,
                    "label": modules[module_id].get("title") or module_id,
                    "confidence_tier": modules[module_id].get("confidence_tier"),
                }
                for module_id in module_ids
            ],
            "edges": [
                {
                    "source": edge["source_module_id"],
                    "target": edge["target_module_id"],
                    "edge_type": "produces_consumed_by",
                    "source_output": edge["source_output"],
                    "target_input": edge["target_input"],
                    "artifact_type": edge["artifact_type"],
                    "compatibility_edge_id": edge["edge_id"],
                }
                for edge in compatibility_edges
            ],
            "inputs": inputs,
            "outputs": outputs,
            "capabilities": capabilities,
            "confidence_tier": "source_derived",
            "lifecycle_state": "candidate",
            "materialization_status": "graph_draft_only",
            "run_blocker": "Review and materialize through suite-specific renderers before execution.",
            "evidence": [{"kind": "sqlite_compatibility_edges", "edge_count": len(compatibility_edges)}],
        }

    def find_missing_contracts(self, candidate_graph: dict[str, Any]) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for node in candidate_graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            module_id = str(node.get("module_id") or "")
            if module_id and not self.catalog.get_module(module_id):
                missing.append({"kind": "module", "module_id": module_id, "reason": "module contract not found"})
        for edge in candidate_graph.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            if not edge.get("artifact_type"):
                missing.append({"kind": "edge", "edge": edge, "reason": "artifact_type is required"})
        schema = candidate_graph.get("params_schema") if isinstance(candidate_graph.get("params_schema"), dict) else {}
        for name in schema.get("required") or []:
            field = next((item for item in schema.get("fields") or [] if isinstance(item, dict) and item.get("name") == name), None)
            if not field:
                missing.append({"kind": "parameter", "name": name, "reason": "required field missing from schema"})
        return missing

    def rank_candidate_graphs(self, candidates: list[dict[str, Any]], objective: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        confidence_rank = {
            "published": 0,
            "verified": 0,
            "tested_local_recipe": 1,
            "curated_profile": 2,
            "mixed_recipe_and_source_derived": 3,
            "source_derived": 4,
            "experimental_adapter": 5,
        }
        requested_inputs = {str(item) for item in (objective or {}).get("input_artifacts") or [] if str(item).strip()}
        requested_outputs = {str(item) for item in (objective or {}).get("requested_outputs") or [] if str(item).strip()}

        def key(graph: dict[str, Any]) -> tuple[int, int, int, int, int, int, str]:
            lifecycle = str(graph.get("lifecycle_state") or "")
            confidence = str(graph.get("confidence_tier") or "")
            missing = len(self.find_missing_contracts(graph))
            materialization = str(graph.get("materialization_status") or "")
            materialization_rank = {
                "verified_recipe": 0,
                "runnable_bundle": 1,
                "runnable_smoke_bundle": 1,
                "graph_draft_only": 5,
            }.get(materialization, 3)
            node_count = len(graph.get("nodes") or [])
            best = min(confidence_rank.get(lifecycle, 9), confidence_rank.get(confidence, 9))
            graph_inputs = {
                str(item.get("artifact_type"))
                for item in graph.get("inputs") or []
                if isinstance(item, dict) and item.get("artifact_type")
            }
            graph_outputs = {
                str(item.get("artifact_type"))
                for item in graph.get("outputs") or []
                if isinstance(item, dict) and item.get("artifact_type")
            }
            input_miss = len(requested_inputs - graph_inputs) if requested_inputs else 0
            output_miss = len(requested_outputs - graph_outputs) if requested_outputs else 0
            return (best, input_miss, output_miss, missing, materialization_rank, node_count, str(graph.get("graph_id") or ""))

        return sorted([copy.deepcopy(candidate) for candidate in candidates], key=key)

    def explain_candidate_graph(self, graph_id: str) -> dict[str, Any]:
        graph = self.hydrate_graph(graph_id)
        return {
            "graph_id": graph_id,
            "title": graph.get("title"),
            "nodes": graph.get("nodes") or [],
            "edges": graph.get("edges") or [],
            "confidence_tier": graph.get("confidence_tier"),
            "materialization_status": graph.get("materialization_status"),
            "run_blocker": graph.get("run_blocker"),
            "evidence": graph.get("evidence") or [],
            "missing_contracts": self.find_missing_contracts(graph),
        }

    def explain_path(self, path_id: str) -> dict[str, Any]:
        return self.explain_candidate_graph(path_id)

    def store_verified_recipe(self, graph: dict[str, Any], execution_manifest: dict[str, Any]) -> dict[str, Any]:
        payload = copy.deepcopy(graph)
        payload["lifecycle_state"] = "verified"
        payload["materialization_status"] = "verified_recipe"
        if self.store is not None:
            result = self.store.store_verified_recipe(payload, execution_manifest)
            payload["verified_recipe_id"] = result["verified_recipe_id"]
            self._draft_cache[payload["graph_id"]] = payload
            return {**result, "workflow_graph": payload}
        if execution_manifest.get("status") != "verified" or execution_manifest.get("verified_recipe") is not True:
            raise ValueError("execution_manifest is not verified")
        self._draft_cache[payload["graph_id"]] = payload
        return {
            "verified_recipe_id": f"verified:{payload['graph_id']}",
            "graph_id": payload["graph_id"],
            "canonical_graph_hash": execution_manifest.get("canonical_graph_hash") or payload.get("canonical_graph_hash"),
            "lifecycle_state": "verified",
            "workflow_graph": payload,
        }

    def plan_star_mvp(self, goal: str) -> dict[str, Any]:
        graph = plan_star_mvp_composition(goal, graph_index=self.star_index)
        return graph.as_dict()
