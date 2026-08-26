"""Shared Workbench service contract for web routes and MCP adapters."""

from __future__ import annotations

import json
import os
import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from morphic_agent.bundle.containers import container_manifest_response, diagnose_container_manifest, load_container_manifest
from morphic_agent.bundle.path_bindings import (
    load_path_bindings,
    path_bindings_response,
    validate_path_bindings_for_location,
)
from morphic_agent.execution import (
    annotate_preflight_for_location,
    execution_dispatch_for_location,
    execution_location_gate,
    resolve_execution_location,
)
from morphic_agent.graph.index import MorphicGraphIndex
from morphic_agent.harvest.nfcore import (
    harvest_nfcore_pipeline_path_to_registry,
    harvest_nfcore_remote_pipeline_to_registry,
    harvest_nfcore_schema_file_to_registry,
)
from morphic_agent.harvest.nfcore_decomposition import decompose_nfcore_pipeline as decompose_nfcore_source
from morphic_agent.harvest.nfcore_remote import BytesFetcher, looks_like_nfcore_pipeline_spec
from morphic_agent.harvest.nfcore_validation import nfcore_reference_validation_record
from morphic_agent.harvest.nfcore_validation_matrix import build_nfcore_validation_matrix
from morphic_agent.planner.engine import PlannerEngine
from morphic_agent.planner.llm_fallback import check_llm_available
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore
from morphic_agent.suites.registry import discover_suite_inventory, list_suite_recipes
from morphic_agent.suites.star import list_star_workflows
from morphic_agent.tools.bundle import BundleTools
from morphic_agent.tools.graph import GraphTools
from morphic_agent.tools.registry import RegistryTools


@dataclass
class WorkbenchService:
    """Stable internal API shared by Workbench clients.

    The web app currently owns HTTP details such as request parsing, cookies,
    user/session headers, and file responses. This service owns deterministic
    Workbench operations so an MCP adapter can call the same contracts.
    """

    store: AgentStore
    catalog: ModuleCatalog
    graph_index: MorphicGraphIndex
    graph_tools: GraphTools
    registry_tools: RegistryTools
    bundle_tools: BundleTools
    planner: PlannerEngine
    _review_approvals: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def create(
        cls,
        *,
        db_path: str | Path | None = None,
        catalog_path: str | Path | None = None,
    ) -> "WorkbenchService":
        store = AgentStore(db_path or os.environ.get("MORPHIC_AGENT_DB"))
        catalog = ModuleCatalog(catalog_path, store=store)
        graph_index = MorphicGraphIndex(catalog, store=store)
        graph_tools = GraphTools(catalog, graph_index)
        registry_tools = RegistryTools(catalog)
        bundle_tools = BundleTools(catalog, graph_tools, store=store)
        planner = PlannerEngine(store, catalog, graph_tools.index)
        return cls(
            store=store,
            catalog=catalog,
            graph_index=graph_index,
            graph_tools=graph_tools,
            registry_tools=registry_tools,
            bundle_tools=bundle_tools,
            planner=planner,
        )

    def model_status(self, *, probe: bool = False) -> dict[str, Any]:
        payload = check_llm_available(probe=probe)
        payload["status"] = "ok" if payload.get("available") is not False else "unavailable"
        return payload

    def suites(self) -> dict[str, Any]:
        inventory = discover_suite_inventory()
        suite_payloads = {str(item.get("suite") or ""): item for item in inventory.get("suites") or [] if isinstance(item, dict)}
        workflows = suite_payloads.get("star") or list_star_workflows()
        default_workflow = "star_bulk_pe_batch"
        default_label = default_workflow
        suite_cards: list[dict[str, Any]] = []
        for suite_id in ("star", "chromap", "multiomics"):
            suite_inventory = suite_payloads.get(suite_id) or list_suite_recipes(suite_id)
            recipes = suite_inventory.get("recipes") or []
            default_recipe = recipes[0] if recipes else {}
            if suite_id == "star":
                for recipe in recipes:
                    if recipe.get("workflow_id") == default_workflow or recipe.get("id") == default_workflow:
                        default_recipe = recipe
                        default_label = str(recipe.get("title") or default_workflow)
                        break
            suite_cards.append(
                {
                    "id": suite_id,
                    "label": suite_inventory.get("label") or suite_id,
                    "available": bool(suite_inventory.get("available")),
                    "recipe_count": int(suite_inventory.get("recipe_count") or len(recipes)),
                    "default_workflow": default_workflow if suite_id == "star" else default_recipe.get("workflow_id"),
                    "default_workflow_label": default_label if suite_id == "star" else default_recipe.get("title"),
                    "default_recipe": default_recipe.get("id") or default_recipe.get("recipe_id"),
                    "api_url": f"/api/suites/{suite_id}/",
                    "recipes_url": f"/api/suites/{suite_id}/recipes",
                    "launchpad_url": (
                        os.environ.get("STAR_LAUNCHPAD_URL") or "/suites/star/launchpad/"
                        if suite_id == "star"
                        else None
                    ),
                }
            )
        default_model = os.environ.get("MORPHIC_AGENT_DEFAULT_MODEL") or os.environ.get("DEFAULT_MODEL") or "local"
        return {
            "status": "ok",
            "default_model": default_model,
            "models": [default_model],
            "suites": suite_cards,
            "suite_observations": {
                "star_workflow_count": int((suite_payloads.get("star") or {}).get("recipe_count") or len(workflows.get("workflows") or [])),
                "star_error": bool((suite_payloads.get("star") or {}).get("errors") or workflows.get("error")),
                "available_suite_count": inventory.get("available_suite_count"),
            },
        }

    def suite_recipes(self, suite_id: str) -> tuple[dict[str, Any], int]:
        payload = list_suite_recipes(str(suite_id or "").strip().lower())
        errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
        status = 404 if errors and str(errors[0]).startswith("unknown suite") else 200
        return payload, status

    def assistant_message(
        self,
        body: dict[str, Any],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        goal = str(body.get("goal") or body.get("message") or "").strip()
        owner_user, session_id = _conversation_identity(request_context)
        requested_conversation_id = str(body.get("conversation_id") or body.get("thread_id") or "").strip()
        if str(body.get("intent") or "") == "explain_plan":
            if not requested_conversation_id:
                return {"error": "thread_id is required"}, 400
            try:
                conversation = self.store.get_conversation(
                    requested_conversation_id,
                    owner_user=owner_user,
                )
            except PermissionError as exc:
                return {"status": "forbidden", "error": str(exc)}, 403
            if conversation is None:
                return {"status": "not_found", "conversation_id": requested_conversation_id}, 404
            return {
                **self.planner.explain_current_plan(conversation["thread_id"]),
                "conversation_id": conversation["conversation_id"],
                "conversation": conversation,
            }, 200
        if not goal:
            return {"error": "goal is required"}, 400
        try:
            conversation = self.store.ensure_conversation(
                requested_conversation_id or None,
                owner_user=owner_user,
                session_id=session_id,
                title=goal,
            )
        except PermissionError as exc:
            return {"status": "forbidden", "error": str(exc)}, 403
        except ValueError as exc:
            return {"status": "blocked", "error": str(exc)}, 409
        if body.get("require_model") is True:
            llm_status = self.model_status(probe=True)
            if llm_status.get("available") is not True:
                message = (
                    "This walkthrough requires the configured model, but the model is not available. "
                    f"{llm_status.get('error') or 'The model probe failed.'}"
                )
                return (
                    {
                        "status": "model_unavailable",
                        "thread_id": conversation["thread_id"],
                        "conversation_id": conversation["conversation_id"],
                        "conversation": conversation,
                        "assistant_message": message,
                        "model_status": llm_status,
                        "ready_to_draft": False,
                    },
                    503,
                )
        response = self.planner.handle_message(
            thread_id=conversation["thread_id"],
            goal=goal,
        )
        refreshed = self.store.get_conversation(conversation["conversation_id"], owner_user=owner_user) or conversation
        return {
            **response,
            "conversation_id": refreshed["conversation_id"],
            "conversation": refreshed,
        }, 200

    def create_conversation(
        self,
        *,
        owner_user: str,
        session_id: str,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conversation = self.store.create_conversation(
            owner_user=owner_user,
            title=title,
            session_id=session_id,
            metadata=metadata,
        )
        return {"status": "created", "conversation": conversation, "conversation_id": conversation["conversation_id"]}

    def list_conversations(
        self,
        *,
        owner_user: str,
        status: str = "active",
        query: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        conversations = self.store.list_conversations(
            owner_user=owner_user,
            status=status,
            query=query,
            limit=limit,
        )
        return {
            "schema": "morphic.conversation_list/v1",
            "status": "ok",
            "conversation_count": len(conversations),
            "conversations": conversations,
        }

    def get_conversation(
        self,
        conversation_id: str,
        *,
        owner_user: str,
        turn_limit: int = 100,
        run_limit: int = 25,
    ) -> tuple[dict[str, Any], int]:
        try:
            conversation = self.store.get_conversation(conversation_id, owner_user=owner_user)
        except PermissionError as exc:
            return {"status": "forbidden", "error": str(exc), "conversation_id": conversation_id}, 403
        if conversation is None:
            return {"status": "not_found", "conversation_id": conversation_id}, 404
        return {
            "status": "ok",
            "conversation": conversation,
            "turns": self.store.recent_turns(conversation["thread_id"], limit=turn_limit),
            "runs": self.store.conversation_runs(conversation_id, owner_user=owner_user, limit=run_limit),
        }, 200

    def update_conversation(
        self,
        conversation_id: str,
        *,
        owner_user: str,
        session_id: str = "",
        title: str | None = None,
        status: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        try:
            conversation = self.store.update_conversation(
                conversation_id,
                owner_user=owner_user,
                title=title,
                status=status,
                session_id=session_id,
            )
        except PermissionError as exc:
            return {"status": "forbidden", "error": str(exc), "conversation_id": conversation_id}, 403
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "conversation_id": conversation_id}, 400
        if conversation is None:
            return {"status": "not_found", "conversation_id": conversation_id}, 404
        return {"status": "ok", "conversation": conversation}, 200

    def fork_conversation(
        self,
        conversation_id: str,
        *,
        owner_user: str,
        session_id: str = "",
        title: str = "",
        include_history: bool = True,
    ) -> tuple[dict[str, Any], int]:
        try:
            conversation = self.store.fork_conversation(
                conversation_id,
                owner_user=owner_user,
                session_id=session_id,
                title=title,
                include_history=include_history,
            )
        except PermissionError as exc:
            return {"status": "forbidden", "error": str(exc), "conversation_id": conversation_id}, 403
        if conversation is None:
            return {"status": "not_found", "conversation_id": conversation_id}, 404
        return {"status": "created", "conversation": conversation}, 201

    def thread_turns(
        self,
        thread_id: str,
        *,
        owner_user: str = "anonymous",
        limit: int = 50,
    ) -> tuple[dict[str, Any], int]:
        payload, status = self.get_conversation(
            thread_id,
            owner_user=owner_user,
            turn_limit=limit,
            run_limit=1,
        )
        if status != 200:
            return payload, status
        return {
            "status": "ok",
            "thread_id": thread_id,
            "conversation_id": thread_id,
            "conversation": payload["conversation"],
            "turns": payload["turns"],
        }, 200

    def list_modules(self, query: str = "") -> dict[str, Any]:
        return self.registry_tools.list_modules(query).as_dict()

    def get_module(self, module_id: str) -> tuple[dict[str, Any], int]:
        response = self.registry_tools.get_module_contract(module_id)
        return response.as_dict(), 404 if response.status == "not_found" else 200

    def draft_graph(
        self,
        goal: str,
        *,
        include_launchpad: bool = True,
        thread_id: str = "",
        log_interaction: bool = False,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        active_thread_id = str(thread_id or "").strip()
        conversation = None
        if log_interaction or active_thread_id:
            owner_user, session_id = _conversation_identity(request_context)
            conversation = self.store.ensure_conversation(
                active_thread_id or None,
                owner_user=owner_user,
                session_id=session_id,
                title=goal,
            )
            active_thread_id = conversation["thread_id"]
        if log_interaction:
            self.store.append_turn(active_thread_id, role="user", goal=goal, payload={"surface": "graph_draft"})
        response = self.graph_tools.draft_graph(goal, include_launchpad=include_launchpad)
        payload = response.payload
        response_payload = {
            "status": response.status,
            "graph_id": payload.get("graph_id"),
            "workflow_graph": payload.get("workflow_graph"),
            "params_schema": payload.get("params_schema"),
            "required_human_inputs": payload.get("required_human_inputs"),
            "confidence_tier": response.confidence_tier,
            "materialization_status": payload.get("materialization_status"),
            "durability": (payload.get("workflow_graph") or {}).get("durability") or "stored",
            "run_blocker": payload.get("run_blocker") or (response.blockers[0] if response.blockers else None),
            "assistant_message": response.summary,
        }
        if active_thread_id:
            response_payload["thread_id"] = active_thread_id
            self.store.append_turn(active_thread_id, role="assistant", goal="", payload={**response_payload, "surface": "graph_draft"})
            refreshed = self.store.get_conversation(active_thread_id, owner_user=conversation["owner_user"])
            response_payload["conversation_id"] = active_thread_id
            response_payload["conversation"] = refreshed or conversation
        return response_payload

    def get_graph(self, graph_id: str) -> tuple[dict[str, Any], int]:
        graph = self.graph_tools.get_graph(graph_id)
        if not graph:
            return {"error": "graph not found", "graph_id": graph_id}, 404
        return {"status": "ok", "graph_id": graph_id, "workflow_graph": graph}, 200

    def rebuild_graph_projection(self, projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        response = self.graph_tools.rebuild_graph_index(projection_version)
        payload = dict(response.payload)
        projection_status = payload.pop("status", None)
        if projection_status is not None:
            payload["projection_status"] = projection_status
        return {"status": response.status, **payload}

    def projection_status(self, projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        response = self.graph_tools.projection_status(projection_version)
        payload = dict(response.payload)
        projection_status = payload.pop("status", None)
        if projection_status is not None:
            payload["projection_status"] = projection_status
        return {"status": response.status, **payload}

    def find_verified_subgraphs(self, problem_signature: dict[str, Any]) -> dict[str, Any]:
        response = self.graph_tools.find_verified_subgraphs(problem_signature)
        return {"status": response.status, **response.payload}

    def search_graphs(
        self,
        *,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.store.search_graphs(query=query, filters=filters or {}, limit=limit)

    def harvest_nfcore_pipeline(
        self,
        *,
        pipeline_path: str = "",
        schema_path: str | Path | None = None,
        modules_json_path: str | Path | None = None,
        release: str | None = None,
        cache_root: str | Path | None = None,
        allow_network: bool = False,
        timeout: float = 20.0,
        provenance: dict[str, Any] | None = None,
        fetch_bytes: BytesFetcher | None = None,
        decompose_source: bool = True,
        strict_decomposition: bool = False,
    ) -> dict[str, Any]:
        """Harvest one nf-core pipeline into the Workbench registry.

        Remote ``nf-core/<pipeline>`` specs are blocked unless ``allow_network``
        is true. Remote harvest fetches only small metadata files.
        """

        source = str(pipeline_path or "").strip()
        provenance = {"harvested_by": "workbench_service", **(provenance or {})}
        if schema_path:
            result = harvest_nfcore_schema_file_to_registry(
                schema_path,
                self.store,
                modules_json_path=modules_json_path,
                provenance=provenance,
                cache_root=cache_root,
            )
            source_kind = "local_schema"
        elif allow_network and looks_like_nfcore_pipeline_spec(source):
            result = harvest_nfcore_remote_pipeline_to_registry(
                source,
                self.store,
                release=release,
                provenance=provenance,
                cache_root=cache_root,
                timeout=timeout,
                fetch_bytes=fetch_bytes,
            )
            source_kind = "remote_metadata"
        elif looks_like_nfcore_pipeline_spec(source):
            return {
                "schema": "morphic.nfcore_harvest_response/v0",
                "status": "blocked",
                "pipeline_path": source,
                "release": release,
                "allow_network": False,
                "run_blocker": "Remote nf-core metadata harvest requires allow_network=true.",
                "required_next_step": {
                    "endpoint": "/api/nfcore/harvest",
                    "method": "POST",
                    "body": {
                        "pipeline_path": source,
                        "release": release,
                        "cache_root": str(cache_root) if cache_root is not None else None,
                        "allow_network": True,
                    },
                },
            }
        else:
            if not source:
                raise ValueError("pipeline_path or schema_path is required")
            result = harvest_nfcore_pipeline_path_to_registry(
                source,
                self.store,
                decompose_source=decompose_source,
                strict_decomposition=strict_decomposition,
                provenance=provenance,
                cache_root=cache_root,
            )
            source_kind = "local_pipeline_path"
        self.catalog.reload()
        return {
            "schema": "morphic.nfcore_harvest_response/v0",
            **result.import_manifest,
            "status": result.import_manifest.get("status") or "ok",
            "source_kind": source_kind,
            "workflow_graph": result.harvest_result.workflow_graph,
            "module_contract": result.harvest_result.module_contract,
        }

    def decompose_nfcore_pipeline(self, pipeline_path: str | Path, *, strict: bool = False) -> dict[str, Any]:
        """Return an editing index for local nf-core sources without registering them."""

        return decompose_nfcore_source(pipeline_path, strict=strict)

    def register_nfcore_recipe(
        self,
        *,
        schema_path: str | Path,
        modules_json_path: str | Path | None = None,
        cache_root: str | Path | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.harvest_nfcore_pipeline(
            schema_path=schema_path,
            modules_json_path=modules_json_path,
            cache_root=cache_root,
            provenance={"harvested_by": "workbench_service_register", **(provenance or {})},
        )

    def list_nfcore_pipelines(self, *, query: str = "", limit: int = 20) -> dict[str, Any]:
        return self.search_graphs(query=query, filters={"suite": "nf-core"}, limit=limit)

    def nfcore_validation_matrix(
        self,
        *,
        out_root: str | Path | None = None,
        execution_location: str = "server",
        render: bool = True,
        preflight: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        return build_nfcore_validation_matrix(
            self.store,
            out_root=out_root,
            execution_location=execution_location,
            render=render,
            preflight=preflight,
            limit=limit,
        )

    def get_nfcore_recipe(self, identifier: str) -> tuple[dict[str, Any], int]:
        graph, module = _nfcore_graph_and_module(self, identifier)
        if graph is None:
            return {
                "status": "not_found",
                "identifier": str(identifier or ""),
                "workflow_graph": None,
                "module_contract": None,
            }, 404
        return {
            "status": "ok",
            "identifier": str(identifier or ""),
            "graph_id": graph.get("graph_id"),
            "module_id": module.get("module_id") if isinstance(module, dict) else None,
            "workflow_graph": graph,
            "module_contract": module,
        }, 200

    def list_nfcore_validations(
        self,
        *,
        graph_id: str = "",
        status: str = "",
        comparator_kind: str = "",
        executor: str = "",
        fixture_id: str = "",
        profile: str = "",
        source_manifest_hash: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        filters = {
            key: value
            for key, value in {
                "status": status,
                "validation_kind": "nfcore_reference_comparison",
                "comparator_kind": comparator_kind,
                "executor": executor,
                "fixture_id": fixture_id,
                "profile": profile,
                "source_manifest_hash": source_manifest_hash,
            }.items()
            if str(value or "").strip()
        }
        validations = self.store.list_workflow_validations(
            graph_id=str(graph_id or "").strip() or None,
            filters=filters,
            limit=limit,
        )
        return {
            "schema": "morphic.nfcore_validation_list/v0",
            "status": "ok",
            "filters": {"graph_id": graph_id, **filters},
            "validation_count": len(validations),
            "validations": validations,
        }

    def record_nfcore_reference_validation(
        self,
        *,
        graph_id: str,
        comparison_manifest: dict[str, Any],
        run_id: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        graph, _module = _nfcore_graph_and_module(self, graph_id)
        if graph is None:
            return {"status": "not_found", "graph_id": graph_id, "validation_record": None}, 404
        runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
        if runtime.get("kind") != "nfcore_pipeline":
            return {
                "status": "blocked",
                "graph_id": graph_id,
                "run_blocker": "The matched graph is not an nf-core pipeline graph.",
            }, 400
        if run_id:
            candidate_run = self.store.get_workbench_run(str(run_id))
            if candidate_run is None:
                return {"status": "not_found", "error": "run not found", "run_id": str(run_id), "validation_record": None}, 404
            if str(candidate_run.get("graph_id") or "") != str(graph.get("graph_id") or ""):
                return {
                    "status": "blocked",
                    "error": (
                        f"run `{run_id}` belongs to graph `{candidate_run.get('graph_id')}`, "
                        f"not nf-core graph `{graph.get('graph_id')}`"
                    ),
                    "run_id": str(run_id),
                    "graph_id": graph.get("graph_id"),
                    "validation_record": None,
                }, 400
        manifest = dict(comparison_manifest or {})
        manifest.setdefault("graph_id", graph.get("graph_id"))
        if run_id:
            manifest["run_id"] = str(run_id).strip()
            candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
            manifest["candidate"] = {**candidate, "run_id": str(run_id).strip()}
        record = nfcore_reference_validation_record(manifest, graph=graph)
        stored = self.store.record_workflow_validation(record)
        attached_run = None
        if run_id:
            attach_payload, attach_status = self.attach_validation_to_run(
                run_id=str(run_id),
                validation_id=stored["validation_id"],
            )
            if attach_status != 200:
                return attach_payload, attach_status
            attached_run = attach_payload["run"]
        return {
            "schema": "morphic.nfcore_validation_record_response/v0",
            "status": "ok",
            "graph_id": graph.get("graph_id"),
            "validation_record": stored,
            "run_id": str(run_id or "").strip() or None,
            "run": attached_run,
        }, 201

    def attach_validation_to_run(
        self,
        *,
        run_id: str,
        validation_id: str,
        owner_user: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        run_id = str(run_id or "").strip()
        validation_id = str(validation_id or "").strip()
        if not run_id:
            return {"status": "error", "error": "run_id is required", "run_id": run_id}, 400
        if not validation_id:
            return {"status": "error", "error": "validation_id is required", "run_id": run_id}, 400
        run = self.store.get_workbench_run(run_id)
        if run is None:
            return {"status": "not_found", "error": "run not found", "run_id": run_id}, 404
        owner_error = _run_owner_error(run, owner_user)
        if owner_error:
            return {"status": "forbidden", "error": owner_error, "run_id": run_id}, 403
        validation = self.store.get_workflow_validation(validation_id)
        if validation is None:
            return {
                "status": "not_found",
                "error": "validation record not found",
                "run_id": run_id,
                "validation_id": validation_id,
            }, 404
        try:
            updated = self.store.attach_workflow_validation_to_run(run_id, validation_id)
        except ValueError as exc:
            return {
                "status": "blocked",
                "error": str(exc),
                "run_id": run_id,
                "validation_id": validation_id,
            }, 400
        if updated is None:
            return {
                "status": "not_found",
                "error": "run or validation record not found",
                "run_id": run_id,
                "validation_id": validation_id,
            }, 404
        return {
            "schema": "morphic.workbench_run_validation_attachment/v0",
            "status": "ok",
            "run_id": run_id,
            "validation_id": validation_id,
            "validation_record": validation,
            "run": updated,
        }, 200

    def store_verified_recipe(self, graph_id: str, execution_manifest: dict[str, Any]) -> tuple[dict[str, Any], int]:
        response = self.graph_tools.store_verified_recipe(graph_id, execution_manifest)
        return {"status": response.status, **response.payload}, 400 if response.status == "blocked" else 200

    def params_schema(self, graph_id: str) -> tuple[dict[str, Any], int]:
        graph = self.graph_tools.get_graph(graph_id)
        if not graph:
            return {"error": "graph not found", "graph_id": graph_id}, 404
        return {"status": "ok", "graph_id": graph_id, "params_schema": graph.get("params_schema") or {}}, 200

    def validate_params(self, graph_id: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.bundle_tools.validate_parameters(graph_id, params)
        return {"status": response.status, "graph_id": graph_id, **response.payload}

    def start_run(
        self,
        graph_id: str,
        params: dict[str, Any] | None = None,
        *,
        execution_location: Any = None,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        location = resolve_execution_location(execution_location)
        return self.store.create_workbench_run(
            graph_id,
            params or {},
            execution_location=location.as_dict(),
            request_context=_normalized_request_context(request_context),
            status="created",
            current_step="created",
        )

    def get_run(self, run_id: str, *, owner_user: str | None = None) -> tuple[dict[str, Any], int]:
        run = self.store.get_workbench_run(run_id)
        if run is None:
            return {"status": "not_found", "run_id": str(run_id or ""), "error": "run not found"}, 404
        owner_error = _run_owner_error(run, owner_user)
        if owner_error:
            return {"status": "forbidden", "run_id": str(run_id or ""), "error": owner_error}, 403
        return {"status": "ok", "run": run}, 200

    def list_runs(
        self,
        *,
        graph_id: str | None = None,
        limit: int = 25,
        owner_user: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 25), 100))
        runs = self.store.list_workbench_runs(graph_id=graph_id, limit=limit, owner_user=owner_user)
        return {"status": "ok", "run_count": len(runs), "runs": runs}

    def render_bundle(
        self,
        graph_id: str,
        params: dict[str, Any],
        *,
        out_root: str | Path,
        request_context: dict[str, Any],
        execution_location: Any,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        location = resolve_execution_location(execution_location)
        run, run_blocker = self._prepare_run_for_step(
            graph_id,
            params or {},
            execution_location=location.as_dict(),
            request_context=request_context,
            run_id=run_id,
            status="rendering",
            current_step="render",
            event="render_started",
        )
        if run_blocker:
            return {
                "schema": "morphic.workbench_run_gate/v0",
                "status": "blocked",
                "graph_id": graph_id,
                "run_id": str(run_id or "").strip() or None,
                "run_blocker": run_blocker,
            }
        effective_params = _run_effective_params(run, params or {})
        response = self.bundle_tools.render_bundle(
            graph_id,
            effective_params,
            out_root=out_root,
            request_context=request_context,
            execution_location=location.as_dict(),
        )
        payload = {"status": response.status, **response.payload, "request_context": request_context}
        if run is not None:
            bundle_state = {
                "bundle_id": payload.get("bundle_id"),
                "bundle_path": payload.get("bundle_path"),
                "status": payload.get("status"),
                "execution_readiness": payload.get("execution_readiness"),
                "run_blocker": payload.get("run_blocker"),
                "files": payload.get("files") or [],
            }
            updated = self.store.update_workbench_run(
                str(run["run_id"]),
                {
                    "status": "bundle_materialized" if response.status == "materialized" else "render_blocked",
                    "current_step": "bundle",
                    "params": effective_params,
                    "params_hash": _params_hash(effective_params),
                    "execution_location": location.as_dict(),
                    "request_context": _normalized_request_context(request_context),
                    "bundle": bundle_state,
                },
                event="bundle_rendered" if response.status == "materialized" else "bundle_render_blocked",
                event_payload={"bundle_id": payload.get("bundle_id"), "bundle_path": payload.get("bundle_path")},
            )
            payload = _attach_run(payload, updated)
        return payload

    def preflight_bundle(
        self,
        graph_id: str,
        params: dict[str, Any],
        *,
        execution_location: Any,
        bundle_path: Any = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        location = resolve_execution_location(execution_location)
        run, run_blocker = self._prepare_run_for_step(
            graph_id,
            params or {},
            execution_location=location.as_dict(),
            request_context=None,
            run_id=run_id,
            status="preflight_running",
            current_step="preflight",
            event="preflight_started",
        )
        if run_blocker:
            return {
                "schema": "morphic.workbench_run_gate/v0",
                "status": "blocked",
                "graph_id": graph_id,
                "run_id": str(run_id or "").strip() or None,
                "run_blocker": run_blocker,
            }
        effective_params = _run_effective_params(run, params or {})
        response = self.bundle_tools.preflight_bundle(
            graph_id,
            effective_params,
            execution_location=location.as_dict(),
            bundle_path=bundle_path,
        )
        payload = annotate_preflight_for_location({"status": response.status, **response.payload}, location)
        preflight_record = self.store.record_preflight(graph_id, effective_params, payload)
        payload.update(preflight_record)
        if run is not None:
            bundle_state = run.get("bundle") if isinstance(run.get("bundle"), dict) else {}
            if bundle_path and not bundle_state.get("bundle_path"):
                bundle_record = self.store.get_bundle_by_path(bundle_path)
                bundle_state = {
                    **bundle_state,
                    "bundle_id": bundle_record.get("bundle_id") if isinstance(bundle_record, dict) else None,
                    "bundle_path": str(bundle_path),
                }
            updated = self.store.update_workbench_run(
                str(run["run_id"]),
                {
                    "status": "preflight_passed" if payload.get("status") == "preflight_passed" else "preflight_blocked",
                    "current_step": "preflight",
                    "params": effective_params,
                    "params_hash": _params_hash(effective_params),
                    "execution_location": location.as_dict(),
                    "bundle": bundle_state or None,
                    "preflight": {
                        "preflight_id": preflight_record.get("preflight_id"),
                        "status": payload.get("status"),
                        "run_blocker": payload.get("run_blocker"),
                        "executable_ready": payload.get("executable_ready"),
                    },
                },
                event="preflight_completed",
                event_payload={"preflight_id": preflight_record.get("preflight_id"), "preflight_status": payload.get("status")},
            )
            payload = _attach_run(payload, updated)
        return payload

    def execution_review_request(
        self,
        graph_id: str,
        params: dict[str, Any],
        *,
        proposed_execution_location: Any,
        bundle_path: Any = None,
        review_stage: str = "before_render",
        request_context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        location = resolve_execution_location(proposed_execution_location)
        graph = self.graph_tools.get_graph(graph_id)
        if not graph:
            return {
                "schema": "morphic.execution_review_request/v0",
                "status": "not_found",
                "graph_id": graph_id,
                "run_blocker": "Graph not found.",
            }

        validation = self.validate_params(graph_id, params or {})
        run, run_blocker = self._prepare_run_for_step(
            graph_id,
            params or {},
            execution_location=location.as_dict(),
            request_context=request_context,
            run_id=run_id,
            status="review_required",
            current_step=str(review_stage or "review"),
            event="review_requested",
        )
        if run_blocker:
            return {
                "schema": "morphic.execution_review_request/v0",
                "status": "blocked",
                "graph_id": graph_id,
                "run_id": str(run_id or "").strip() or None,
                "run_blocker": run_blocker,
            }
        active_run_id = str(run["run_id"]) if run is not None else None
        diagnostic: dict[str, Any] | None = None
        diagnostic_status: int | None = None
        if bundle_path:
            diagnostic, diagnostic_status = self.execution_diagnostic(
                graph_id,
                params or {},
                execution_location=location.location_id,
                bundle_path=bundle_path,
                request_context=request_context,
                run_id=active_run_id,
            )

        review_items = [
            "Confirm the graph is the intended recipe or workflow.",
            "Confirm the parameter values and input paths are correct for the selected execution location.",
            "Confirm the execution location before rendering or running preflight.",
        ]
        if bundle_path:
            review_items.append("Review the generated bundle path bindings before any local shell or container run.")
        if location.kind == "local":
            review_items.append("Local execution is caller-managed; the Workbench API will not execute run.sh.")
            review_items.append("The browser cannot automatically start run.sh, Docker, or Apptainer; the user must start the final bundle manually.")
        elif location.kind == "server":
            review_items.append("Server execution requires server-visible paths and a passing server preflight.")
        elif location.kind == "remote_ssh":
            review_items.append("Remote SSH execution requires a reachable host, a destination path for the bundle, and a selected container runtime.")
            review_items.append("Remote path overrides can localize manifests/path_bindings.json before the bundle is copied to the SSH host.")
        elif location.kind == "scheduler_temporal":
            review_items.append("Local scheduler execution stages server-readable inputs into scheduler storage and submits the bundle to Temporal.")
            review_items.append("The local Temporal scheduler stack must be running before preflight and execution can proceed.")
        elif location.kind == "scheduler_remote_ssh":
            review_items.append("Scheduler SSH execution stages server-readable inputs into scheduler storage and submits the bundle to a Temporal SSH Docker workflow.")
            review_items.append("The Temporal scheduler stack and its SSH Docker worker must be running before preflight and execution can proceed.")

        review_payload = {
            "schema": "morphic.execution_review_request/v0",
            "status": "needs_user_review",
            "run_id": active_run_id,
            "graph_id": graph_id,
            "graph_title": graph.get("title") or graph_id,
            "review_stage": str(review_stage or "before_render"),
            "proposed_execution_location": location.as_dict(),
            "reviewed_params": params or {},
            "params_validation": validation,
            "params_valid": validation.get("status") == "valid",
            "bundle_path": str(bundle_path or "").strip() or None,
            "diagnostic": diagnostic,
            "diagnostic_http_status": diagnostic_status,
            "review_items": review_items,
            "question": (
                "Choose the execution location and approve only after verifying "
                "the graph, parameters, paths, and run location."
            ),
            "allowed_execution_locations": ["local", "server", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
            "response_schema": execution_review_response_schema(),
            "workbench_handoff": _workbench_handoff(
                graph_id,
                params or {},
                execution_location=location.as_dict(),
                bundle_path=bundle_path,
                review_stage=review_stage,
                action="open_execution_review",
                run_id=active_run_id,
            ),
        }
        if active_run_id:
            updated = self.store.update_workbench_run(
                active_run_id,
                {
                    "status": "review_required",
                    "current_step": str(review_stage or "review"),
                    "review": _review_state_for_run(review_payload),
                    "execution_location": location.as_dict(),
                    "params": params or {},
                    "params_hash": _params_hash(params or {}),
                    "request_context": _normalized_request_context(request_context),
                },
                event="review_request_ready",
                event_payload={"review_stage": str(review_stage or "before_render")},
            )
            review_payload = _attach_run(review_payload, updated)
        return review_payload

    def complete_execution_review(
        self,
        review: dict[str, Any],
        human_review: dict[str, Any] | None,
        *,
        action: str = "accept",
        interaction_mode: str = "api",
    ) -> dict[str, Any]:
        action = str(action or "accept").strip().lower()
        if action != "accept":
            status = "cancelled" if action == "cancel" else "declined"
            payload = {
                **review,
                "status": status,
                "interaction": {"mode": interaction_mode, "action": action or status},
                "human_review": None,
                "run_blocker": f"User {status} the Workbench review request.",
            }
            payload = self._update_run_from_completed_review(payload, approved=False, interaction_mode=interaction_mode)
            return payload

        response = dict(human_review or {})
        approved = bool(response.get("approved"))
        verified_paths = bool(response.get("verified_paths"))
        final_location_request = _review_location_request(response, review)
        try:
            final_location_profile = resolve_execution_location(final_location_request)
            final_location = final_location_profile.location_id
        except ValueError:
            final_location_profile = None
            final_location = str(response.get("execution_location") or "").strip()
        blockers: list[str] = []
        if not approved:
            blockers.append("User did not approve the Workbench review request.")
        if not verified_paths:
            blockers.append("User did not verify paths for the selected execution location.")
        if final_location not in {"local", "server", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"}:
            blockers.append("User did not select a supported execution location.")
        if final_location_profile is not None:
            gate = execution_location_gate(final_location_profile, "execute")
            if final_location in {"remote_ssh", "scheduler_remote_ssh"} and not gate.allowed:
                blockers.append(gate.run_blocker or "SSH execution is missing required destination details.")
        proposed_location = str(review.get("proposed_execution_location", {}).get("location_id") or "").strip()
        approved = not blockers
        next_step = None
        if approved:
            approved_execution_argument: Any = (
                final_location_profile.as_dict()
                if final_location_profile is not None and final_location_profile.location_id in {"remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"}
                else final_location
            )
            approved_handoff = _workbench_handoff(
                str(review.get("graph_id") or ""),
                review.get("reviewed_params") or {},
                execution_location=final_location_profile.as_dict() if final_location_profile is not None else final_location,
                bundle_path=review.get("bundle_path"),
                review_stage=review.get("review_stage"),
                action="open_execution_review",
                run_id=str(review.get("run_id") or "").strip() or None,
            )
            review_approval = self._issue_review_approval(
                str(review.get("graph_id") or ""),
                review.get("reviewed_params") or {},
                approved_execution_argument,
                interaction_mode=interaction_mode,
            )
            next_step = {
                "tool_name": "workbench_render_bundle",
                "arguments": {
                    "graph_id": review.get("graph_id"),
                    "params": review.get("reviewed_params") or {},
                    "execution_location": approved_execution_argument,
                    "review_approval_token": review_approval["token"],
                    "run_id": review.get("run_id"),
                },
                "must_use_approved_execution_location": True,
                "requires_review_approval_token": True,
                "instruction": (
                    "Call workbench_render_bundle with approved_next_step.arguments exactly, including "
                    "review_approval_token. Do not reuse the originally proposed execution location if "
                    "the user changed it."
                ),
            }
        payload = {
            **review,
            "status": "approved" if approved else "blocked",
            "interaction": {"mode": interaction_mode, "action": "accept"},
            "human_review": response,
            "approved_execution_location": final_location or None,
            "approved_execution_location_request": final_location_profile.as_dict() if final_location_profile is not None else None,
            "execution_location_changed_by_user": bool(approved and proposed_location and final_location != proposed_location),
            "review_approval": review_approval if approved else None,
            "approved_next_step": next_step,
            "workbench_handoff": approved_handoff if approved else review.get("workbench_handoff"),
            "run_blocker": "; ".join(blockers) if blockers else None,
        }
        payload = self._update_run_from_completed_review(payload, approved=approved, interaction_mode=interaction_mode)
        return payload

    def review_approval_blocker(
        self,
        token: Any,
        graph_id: str,
        params: dict[str, Any],
        *,
        execution_location: Any,
    ) -> str | None:
        location = resolve_execution_location(execution_location)
        expected = _review_approval_payload(graph_id, params or {}, location.as_dict())
        token_text = str(token or "").strip()
        if not str(token or "").strip():
            return (
                "workbench_render_bundle requires review_approval_token from "
                "workbench_request_user_review.approved_next_step.arguments."
            )
        approval = self.store.get_review_approval(token_text) or self._review_approvals.get(token_text)
        if not approval:
            return (
                "review_approval_token was not issued by a completed Workbench user review. "
                "Open the browser review URL or complete MCP elicitation, then use the returned "
                "approved_next_step.arguments exactly."
            )
        expected_fields = ("graph_id", "execution_location", "execution_location_metadata", "params_hash")
        if any(approval.get(field) != expected.get(field) for field in expected_fields):
            return (
                "review_approval_token does not match graph_id, params, or execution_location. "
                "Call workbench_request_user_review again and use approved_next_step.arguments exactly."
            )
        return None

    def _issue_review_approval(
        self,
        graph_id: str,
        params: dict[str, Any],
        execution_location: Any,
        *,
        interaction_mode: str,
    ) -> dict[str, Any]:
        approval = {
            **_review_approval_payload(graph_id, params, execution_location),
            "token": f"review-{secrets.token_urlsafe(24)}",
            "issued_via": str(interaction_mode or "unknown"),
        }
        self._review_approvals[approval["token"]] = approval
        self.store.record_review_approval(approval)
        return approval

    def _prepare_run_for_step(
        self,
        graph_id: str,
        params: dict[str, Any],
        *,
        execution_location: Any,
        request_context: dict[str, Any] | None,
        run_id: str | None,
        status: str,
        current_step: str,
        event: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        location = resolve_execution_location(execution_location)
        normalized_context = _normalized_request_context(request_context) if request_context is not None else {}
        run_id = str(run_id or "").strip()
        if not run_id:
            return (
                self.store.create_workbench_run(
                    graph_id,
                    params or {},
                    execution_location=location.as_dict(),
                    request_context=normalized_context,
                    status=status,
                    current_step=current_step,
                ),
                None,
            )

        run = self.store.get_workbench_run(run_id)
        if run is None:
            return None, f"run_id `{run_id}` was not found; start a new Workbench run before continuing."
        if normalized_context:
            owner_error = _run_owner_error(run, _conversation_identity(normalized_context)[0])
            if owner_error:
                return None, owner_error
        conversation_id = str(normalized_context.get("conversation_id") or normalized_context.get("thread_id") or "").strip()
        if conversation_id:
            requested_owner = _conversation_identity(normalized_context)[0]
            try:
                self.store.ensure_conversation(
                    conversation_id,
                    owner_user=requested_owner,
                    session_id=_conversation_identity(normalized_context)[1],
                )
            except (PermissionError, ValueError) as exc:
                return None, str(exc)
        if str(run.get("graph_id") or "") != str(graph_id or ""):
            return None, f"run_id `{run_id}` belongs to graph `{run.get('graph_id')}`, not `{graph_id}`."

        existing_params = run.get("params") if isinstance(run.get("params"), dict) else {}
        incoming_params = params or {}
        if incoming_params and existing_params and _params_hash(incoming_params) != str(run.get("params_hash") or ""):
            return None, f"run_id `{run_id}` has different parameters; start a new Workbench run for changed params."
        effective_params = incoming_params or existing_params
        updated = self.store.update_workbench_run(
            run_id,
            {
                "status": status,
                "current_step": current_step,
                "params": effective_params,
                "params_hash": _params_hash(effective_params),
                "execution_location": location.as_dict(),
                "request_context": normalized_context or run.get("request_context") or {},
            },
            event=event,
        )
        if conversation_id:
            self.store.link_conversation_run(
                conversation_id,
                run_id,
                owner_user=_conversation_identity(normalized_context)[0],
            )
        return updated, None

    def _update_run_from_completed_review(
        self,
        payload: dict[str, Any],
        *,
        approved: bool,
        interaction_mode: str,
    ) -> dict[str, Any]:
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            return payload
        current = self.store.get_workbench_run(run_id)
        if current is None:
            return payload
        location = payload.get("approved_execution_location_request")
        if not isinstance(location, dict):
            location = payload.get("proposed_execution_location") if isinstance(payload.get("proposed_execution_location"), dict) else current.get("execution_location")
        review_approval = payload.get("review_approval") if isinstance(payload.get("review_approval"), dict) else {}
        updated = self.store.update_workbench_run(
            run_id,
            {
                "status": "review_approved" if approved else str(payload.get("status") or "review_blocked"),
                "current_step": "review",
                "execution_location": location if isinstance(location, dict) else current.get("execution_location"),
                "review": {
                    **_review_state_for_run(payload),
                    "interaction_mode": str(interaction_mode or ""),
                    "approval_token": review_approval.get("token"),
                },
            },
            event="review_completed",
            event_payload={"review_status": payload.get("status"), "approved": bool(approved)},
        )
        return _attach_run(payload, updated)

    def execution_diagnostic(
        self,
        graph_id: str,
        params: dict[str, Any],
        *,
        execution_location: Any,
        bundle_path: Any = None,
        request_context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        location = resolve_execution_location(execution_location)
        context = _normalized_request_context(request_context)
        run, run_blocker = self._prepare_run_for_step(
            graph_id,
            params or {},
            execution_location=location.as_dict(),
            request_context=context,
            run_id=run_id,
            status="diagnostic_running",
            current_step="diagnostic",
            event="diagnostic_started",
        )
        if run_blocker:
            return (
                {
                    "schema": "morphic.workbench_run_gate/v0",
                    "status": "blocked",
                    "graph_id": graph_id,
                    "run_id": str(run_id or "").strip() or None,
                    "run_blocker": run_blocker,
                },
                400,
            )
        active_run_id = str(run["run_id"]) if run is not None else None
        effective_params = _run_effective_params(run, params or {})
        gate = execution_location_gate(location, "execute")
        checks: list[dict[str, Any]] = [
            {
                "check": "execution locale selected",
                "status": "pass",
                "location_id": location.location_id,
                "location_kind": location.kind,
            },
            {
                "check": "direct Workbench API execution supported",
                "status": "pass" if gate.allowed else "fail",
                "run_blocker": gate.run_blocker,
            },
        ]
        blockers: list[str] = []
        if not gate.allowed:
            _append_unique(blockers, gate.run_blocker)

        bundle: Path | None = None
        bundle_record: dict[str, Any] | None = None
        path_metadata: dict[str, Any] = {"path_bindings_path": None, "path_bindings_hash": None}
        container_metadata: dict[str, Any] = {"container_manifest_path": None, "container_manifest_hash": None}
        container_diagnostic: dict[str, Any] = diagnose_container_manifest(None, execution_location_kind=location.kind)
        path_manifest_present = False
        raw_bundle_path = bundle_path
        if raw_bundle_path:
            bundle, bundle_record, bundle_error, bundle_status = self._registered_bundle_for_graph(graph_id, raw_bundle_path, context)
            if bundle_error is not None:
                checks.append(
                    {
                        "check": "registered generated bundle available",
                        "status": "fail",
                        "message": bundle_error.get("run_blocker") or bundle_error.get("error"),
                    }
                )
                _append_unique(blockers, bundle_error.get("run_blocker") or bundle_error.get("error"))
                if bundle_status == 403:
                    payload = {
                        "schema": "morphic.execution_location_diagnostic/v0",
                        "status": "blocked",
                        "run_id": active_run_id,
                        "graph_id": graph_id,
                        "execution_location": location.as_dict(),
                        "execution_dispatch": execution_dispatch_for_location(location),
                        "execution_run_gate": gate.as_dict(),
                        "checks": checks,
                        "blockers": blockers,
                        "action_items": _diagnostic_action_items(location, has_bundle=False, has_path_manifest=False),
                        "resolution_options": _diagnostic_resolution_options(
                            location,
                            bundle_path=str(raw_bundle_path or "").strip() or None,
                            has_bundle=False,
                            has_path_manifest=False,
                            container_diagnostic=container_diagnostic,
                        ),
                        "requirements": _execution_requirements_for_graph(graph_id),
                        "workbench_handoff": _workbench_handoff(
                            graph_id,
                            effective_params,
                            execution_location=location.as_dict(),
                            bundle_path=str(raw_bundle_path or "").strip() or None,
                            review_stage="diagnostic",
                            action="open_execution_diagnostic",
                            run_id=active_run_id,
                        ),
                        "request_context": context,
                    }
                    if active_run_id:
                        updated = self.store.update_workbench_run(
                            active_run_id,
                            {
                                "status": "diagnostic_blocked",
                                "current_step": "diagnostic",
                                "diagnostic": {
                                    "status": "blocked",
                                    "run_blocker": "; ".join(blockers) if blockers else None,
                                    "blockers": blockers,
                                    "can_execute_in_api": False,
                                },
                            },
                            event="diagnostic_completed",
                            event_payload={"diagnostic_status": "blocked"},
                        )
                        payload = _attach_run(payload, updated)
                    return (
                        payload,
                        403,
                    )
            elif bundle is not None:
                checks.append({"check": "registered generated bundle available", "status": "pass", "path": str(bundle)})
                run_sh = bundle / "run.sh"
                checks.append({"check": "bundle contains run.sh", "status": "pass" if run_sh.is_file() else "fail", "path": str(run_sh)})
                if not run_sh.is_file():
                    _append_unique(blockers, "bundle is missing run.sh")
                try:
                    path_manifest = load_path_bindings(bundle)
                    path_manifest_present = path_manifest is not None
                    path_metadata = path_bindings_response(bundle)
                    checks.append(
                        {
                            "check": "path bindings manifest present",
                            "status": "pass" if path_manifest_present else "fail",
                            "path": str(bundle / "manifests" / "path_bindings.json"),
                        }
                    )
                    if not path_manifest_present:
                        _append_unique(blockers, "Bundle is missing manifests/path_bindings.json; regenerate the run directory before changing execution locale.")
                    validation = validate_path_bindings_for_location(
                        path_manifest,
                        bundle_dir=bundle,
                        execution_location=location.location_id,
                    )
                    checks.extend(validation.get("checks") or [])
                    for blocker in validation.get("blockers") or []:
                        _append_unique(blockers, blocker)
                except (OSError, json.JSONDecodeError) as exc:
                    checks.append({"check": "path bindings manifest readable", "status": "fail", "message": str(exc)})
                    _append_unique(blockers, f"path bindings manifest cannot be read: {exc}")

                try:
                    container_manifest = load_container_manifest(bundle)
                    container_metadata = container_manifest_response(bundle)
                    container_diagnostic = diagnose_container_manifest(container_manifest, execution_location_kind=location.kind)
                    checks.extend(container_diagnostic.get("checks") or [])
                except (OSError, json.JSONDecodeError) as exc:
                    container_diagnostic = {
                        "schema": "morphic.container_diagnostic/v0",
                        "status": "blocked",
                        "run_available": False,
                        "checks": [{"check": "container manifest readable", "status": "fail", "message": str(exc)}],
                        "blockers": [f"container manifest cannot be read: {exc}"],
                        "available_runtimes": [],
                        "supported_runtimes": [],
                        "preferred_runtime": None,
                        "command": None,
                    }
                    checks.extend(container_diagnostic["checks"])

                if location.kind == "server":
                    preflight = self.preflight_bundle(
                        graph_id,
                        effective_params,
                        execution_location=location.as_dict(),
                        bundle_path=bundle,
                        run_id=active_run_id,
                    )
                    preflight_passed = preflight.get("status") == "preflight_passed" or preflight.get("executable_ready") is True
                    checks.append(
                        {
                            "check": "server preflight passes",
                            "status": "pass" if preflight_passed else "fail",
                            "preflight_status": preflight.get("status"),
                            "run_blocker": preflight.get("run_blocker"),
                        }
                    )
                    if not preflight_passed:
                        _append_unique(blockers, preflight.get("run_blocker") or "server preflight did not pass")
                elif location.kind == "remote_ssh":
                    preflight = self.preflight_bundle(
                        graph_id,
                        effective_params,
                        execution_location=location.as_dict(),
                        bundle_path=bundle,
                        run_id=active_run_id,
                    )
                    preflight_passed = preflight.get("status") == "preflight_passed" or preflight.get("executable_ready") is True
                    checks.append(
                        {
                            "check": "remote SSH preflight passes",
                            "status": "pass" if preflight_passed else "fail",
                            "preflight_status": preflight.get("status"),
                            "run_blocker": preflight.get("run_blocker"),
                        }
                    )
                    if not preflight_passed:
                        _append_unique(blockers, preflight.get("run_blocker") or "remote SSH preflight did not pass")
                elif location.kind == "local":
                    checks.append(
                        {
                            "check": "caller-visible local input paths verified by Workbench API",
                            "status": "not_run",
                            "reason": "The API cannot inspect the caller's local shell or filesystem.",
                        }
                    )
                elif location.kind == "scheduler_temporal":
                    preflight = self.preflight_bundle(
                        graph_id,
                        effective_params,
                        execution_location=location.as_dict(),
                        bundle_path=bundle,
                        run_id=active_run_id,
                    )
                    preflight_passed = preflight.get("status") == "preflight_passed" or preflight.get("executable_ready") is True
                    checks.append(
                        {
                            "check": "local scheduler preflight passes",
                            "status": "pass" if preflight_passed else "fail",
                            "preflight_status": preflight.get("status"),
                            "run_blocker": preflight.get("run_blocker"),
                        }
                    )
                    if not preflight_passed:
                        _append_unique(blockers, preflight.get("run_blocker") or "local scheduler preflight did not pass")
                elif location.kind == "scheduler_remote_ssh":
                    preflight = self.preflight_bundle(
                        graph_id,
                        effective_params,
                        execution_location=location.as_dict(),
                        bundle_path=bundle,
                        run_id=active_run_id,
                    )
                    preflight_passed = preflight.get("status") == "preflight_passed" or preflight.get("executable_ready") is True
                    checks.append(
                        {
                            "check": "scheduler SSH preflight passes",
                            "status": "pass" if preflight_passed else "fail",
                            "preflight_status": preflight.get("status"),
                            "run_blocker": preflight.get("run_blocker"),
                        }
                    )
                    if not preflight_passed:
                        _append_unique(blockers, preflight.get("run_blocker") or "scheduler SSH preflight did not pass")
                elif location.kind == "remote":
                    checks.append(
                        {
                            "check": "execution connector configured",
                            "status": "fail",
                            "required_connectors": list(location.required_connectors),
                        }
                    )
        else:
            checks.append({"check": "generated run directory selected", "status": "fail"})
            _append_unique(blockers, "Generate a run directory before diagnosing execution.")

        action_items = _diagnostic_action_items(location, has_bundle=bundle is not None, has_path_manifest=path_manifest_present)
        if location.kind == "local":
            if container_diagnostic.get("run_available") and container_diagnostic.get("command"):
                action_items.insert(0, f"Container route available: run {container_diagnostic['command']} from the downloaded bundle directory.")
            elif container_diagnostic.get("status") not in {"missing", "not_run"}:
                for blocker in container_diagnostic.get("blockers") or []:
                    action_items.append(str(blocker))
        status = "ready" if gate.allowed and not blockers else "blocked"
        handoff_params = _handoff_params(effective_params, bundle)
        payload = {
                "schema": "morphic.execution_location_diagnostic/v0",
                "status": status,
                "run_id": active_run_id,
                "graph_id": graph_id,
                "bundle_path": str(bundle) if bundle is not None else str(raw_bundle_path or "").strip() or None,
                "bundle_id": bundle_record.get("bundle_id") if isinstance(bundle_record, dict) else None,
                "execution_location": location.as_dict(),
                "execution_dispatch": execution_dispatch_for_location(location),
                "execution_run_gate": gate.as_dict(),
                "can_execute_in_api": gate.allowed and not blockers,
                "checks": checks,
                "blockers": blockers,
                "run_blocker": "; ".join(blockers) if blockers else None,
                "action_items": action_items,
                "resolution_options": _diagnostic_resolution_options(
                    location,
                    bundle_path=str(bundle) if bundle is not None else str(raw_bundle_path or "").strip() or None,
                    has_bundle=bundle is not None,
                    has_path_manifest=path_manifest_present,
                    container_diagnostic=container_diagnostic,
                ),
                "requirements": _execution_requirements_for_graph(graph_id),
                "container": container_diagnostic,
                "workbench_handoff": _workbench_handoff(
                    graph_id,
                    handoff_params,
                    execution_location=location.as_dict(),
                    bundle_path=str(bundle) if bundle is not None else str(raw_bundle_path or "").strip() or None,
                    review_stage="diagnostic",
                    action="open_execution_diagnostic",
                    run_id=active_run_id,
                ),
                "request_context": context,
                **path_metadata,
                **container_metadata,
        }
        if active_run_id:
            updated = self.store.update_workbench_run(
                active_run_id,
                {
                    "status": "diagnostic_ready" if status == "ready" else "diagnostic_blocked",
                    "current_step": "diagnostic",
                    "params": effective_params,
                    "params_hash": _params_hash(effective_params),
                    "execution_location": location.as_dict(),
                    "bundle": {
                        "bundle_id": payload.get("bundle_id"),
                        "bundle_path": payload.get("bundle_path"),
                    }
                    if payload.get("bundle_path")
                    else (run.get("bundle") if isinstance(run, dict) else None),
                    "diagnostic": {
                        "status": status,
                        "run_blocker": payload.get("run_blocker"),
                        "blockers": blockers,
                        "can_execute_in_api": payload.get("can_execute_in_api"),
                    },
                },
                event="diagnostic_completed",
                event_payload={"diagnostic_status": status},
            )
            payload = _attach_run(payload, updated)
        return (payload, 200)

    def _registered_bundle_for_graph(
        self,
        graph_id: str,
        raw_bundle_path: Any,
        context: dict[str, Any],
    ) -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None, int]:
        bundle_path = str(raw_bundle_path or "").strip()
        if not graph_id:
            return None, None, {"error": "graph_id is required"}, 400
        if not bundle_path:
            return None, None, {"error": "bundle_path is required", "run_blocker": "Generate a run directory first."}, 400

        bundle = Path(bundle_path).expanduser()
        try:
            bundle = bundle.resolve()
        except OSError:
            bundle = bundle.absolute()
        if not bundle.is_dir():
            return None, None, {"status": "blocked", "run_blocker": "Bundle path is not a directory.", "bundle_path": str(bundle)}, 400

        bundle_record = self.store.get_bundle_by_path(bundle) if self.store is not None else None
        if bundle_record is None:
            return (
                None,
                None,
                {
                    "status": "blocked",
                    "run_blocker": "Bundle path is not registered as a generated workbench bundle.",
                    "bundle_path": str(bundle),
                },
                400,
            )
        if str(bundle_record.get("graph_id") or "") != graph_id:
            return (
                None,
                None,
                {
                    "status": "blocked",
                    "run_blocker": "Bundle graph does not match requested graph.",
                    "graph_id": graph_id,
                    "bundle_graph_id": bundle_record.get("graph_id"),
                },
                400,
            )
        owner_allowed, owner_blocker = _bundle_owner_allows_request(bundle_record, context)
        if not owner_allowed:
            return (
                None,
                None,
                {
                    "status": "blocked",
                    "graph_id": graph_id,
                    "bundle_path": str(bundle),
                    "run_blocker": owner_blocker,
                    "request_context": context,
                },
                403,
            )
        return bundle, bundle_record, None, 200


def _append_unique(items: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _normalized_request_context(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(context or {})
    payload.setdefault("user", "anonymous")
    payload.setdefault("session_id", "")
    payload.setdefault("session_supplied", False)
    return payload


def _safe_identity_slug(value: Any, fallback: str = "anonymous") -> str:
    text = "-".join(str(value or "").strip().lower().split())
    text = "".join(character for character in text if character.isalnum() or character in "._-")
    return text.strip(".-")[:80] or fallback


def _conversation_identity(context: dict[str, Any] | None) -> tuple[str, str]:
    payload = context if isinstance(context, dict) else {}
    owner_user = _safe_identity_slug(
        payload.get("storage_user")
        or payload.get("user_slug")
        or payload.get("user")
        or "anonymous",
        "anonymous",
    )
    session_id = _safe_identity_slug(payload.get("session_slug") or payload.get("session_id") or "", "")
    return owner_user, session_id


def _run_owner_error(run: dict[str, Any], owner_user: str | None) -> str | None:
    if owner_user is None:
        return None
    context = run.get("request_context") if isinstance(run.get("request_context"), dict) else {}
    persisted_owner, _ = _conversation_identity(context)
    requested_owner = _safe_identity_slug(owner_user, "anonymous")
    if persisted_owner == requested_owner:
        return None
    return f"Run is owned by `{persisted_owner}`, but this request is from `{requested_owner}`."


def _bundle_owner_allows_request(bundle_record: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str | None]:
    manifest = bundle_record.get("manifest") if isinstance(bundle_record.get("manifest"), dict) else {}
    owner = manifest.get("request_context") if isinstance(manifest.get("request_context"), dict) else {}
    owner_user = str(owner.get("user") or "anonymous")
    request_user = str(context.get("user") or "anonymous")
    if owner_user != "anonymous" and request_user != owner_user:
        return False, f"Bundle is owned by `{owner_user}`, but this request is from `{request_user}`."
    owner_session = str(owner.get("session_id") or "")
    request_session = str(context.get("session_id") or "")
    if bool(owner.get("session_supplied")) and bool(context.get("session_supplied")) and owner_session != request_session:
        return False, "Bundle was generated by a different workbench session."
    return True, None


def _execution_requirements_for_graph(graph_id: str) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = [
        {"name": "bash", "kind": "command", "required_for": "run.sh"},
        {"name": "python3", "kind": "command", "required_for": "bundle helpers"},
    ]
    if graph_id == "trimodal_qc_report_v0":
        for package in ("mudata", "plotly", "scanpy", "pandas", "numpy"):
            requirements.append(
                {
                    "name": package,
                    "kind": "python_package",
                    "required_for": "trimodal MuData QC local run",
                    "check_hint": f"python3 -c 'import {package}'",
                }
            )
    elif graph_id in {"bulk_pe_deseq2_v0", "bulk_pe_deseq2_plots_v0"}:
        requirements.extend(
            [
                {"name": "STAR Suite", "kind": "suite", "required_for": "bulk paired-end RNA-seq workflow"},
                {"name": "Rscript", "kind": "command", "required_for": "DESeq2 helper scripts"},
            ]
        )
    return requirements


def _diagnostic_action_items(location: Any, *, has_bundle: bool, has_path_manifest: bool) -> list[str]:
    actions: list[str] = []
    if not has_bundle:
        actions.append("Generate a run directory for this graph first.")
    if location.kind == "local":
        if has_bundle:
            actions.append("Download Run Directory, unzip it on the machine where the input files are visible, then run bash run.sh from the bundle root.")
        if not has_path_manifest:
            actions.append("Regenerate the run directory so it includes manifests/path_bindings.json.")
        else:
            actions.append("Review manifests/path_bindings.json and edit paths to match the local shell before running.")
        actions.append("Install the listed local commands and Python packages in that shell.")
    elif location.kind == "server":
        actions.append("Use server-visible input paths, or mount/upload the data so the Workbench server can read it.")
        if not has_path_manifest:
            actions.append("Regenerate the run directory so server path bindings can be validated.")
    elif location.kind == "remote_ssh":
        actions.append("Provide remote_host and remote_workdir for the SSH destination.")
        actions.append("Localize manifests/path_bindings.json with remote_path_overrides for any input or output paths that differ on the SSH host.")
        actions.append("Confirm Docker, Podman, Apptainer, or the requested shell runtime is available on the SSH host.")
    elif location.kind == "remote":
        actions.append("Configure a remote executor connector before submitting this bundle to a remote host or cluster.")
    elif location.kind == "scheduler_temporal":
        actions.append("Start the local Temporal scheduler stack before preflight or execution.")
        actions.append("Generate the run directory with Local Temporal scheduler selected so inputs are staged into the bundle.")
    elif location.kind == "scheduler_remote_ssh":
        actions.append("Start the local Temporal scheduler stack and the SSH Docker worker before preflight or execution.")
        actions.append("Provide remote_host, remote_user, and remote_workdir for the SSH Docker worker target.")
        actions.append("Generate the run directory with Remote SSH via Temporal scheduler selected so inputs are staged into the bundle.")
    return actions


def _handoff_params(params: dict[str, Any], bundle: Path | None) -> dict[str, Any]:
    if params:
        return params
    if bundle is None:
        return {}
    try:
        payload = json.loads((bundle / "params.review.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    reviewed = payload.get("params") if isinstance(payload, dict) else None
    return dict(reviewed) if isinstance(reviewed, dict) else {}


def _review_location_request(response: dict[str, Any], review: dict[str, Any]) -> Any:
    raw = response.get("execution_location") or review.get("proposed_execution_location", {}).get("location_id") or ""
    if isinstance(raw, dict):
        payload = dict(raw)
    else:
        payload = {"location_id": str(raw).strip()}
    proposed = review.get("proposed_execution_location") if isinstance(review.get("proposed_execution_location"), dict) else {}
    proposed_metadata = proposed.get("metadata") if isinstance(proposed.get("metadata"), dict) else {}
    normalized_location_id = str(payload.get("location_id") or "").strip().lower().replace("-", "_")
    if normalized_location_id in {"remote_ssh", "ssh", "ssh_remote", "scheduler_remote_ssh", "temporal_ssh", "scheduler_ssh", "ssh_scheduler", "remote_ssh_scheduler"}:
        metadata = dict(proposed_metadata)
        for key in (
            "remote_host",
            "remote_user",
            "remote_workdir",
            "remote_port",
            "remote_container_runtime",
            "remote_path_overrides",
            "remote_check",
        ):
            value = response.get(key)
            if key in response and value is not None and value != "":
                metadata[key] = value
        if metadata:
            payload["metadata"] = {**dict(payload.get("metadata") or {}), **metadata}
    if normalized_location_id in {"scheduler_temporal", "scheduler", "temporal", "temporal_scheduler", "scheduler_remote_ssh", "temporal_ssh", "scheduler_ssh", "ssh_scheduler", "remote_ssh_scheduler"}:
        metadata = dict(proposed_metadata)
        for key in (
            "scheduler_api_url",
            "scheduler_storage_dir",
            "scheduler_worker_queue",
            "scheduler_worker_cpus",
            "scheduler_worker_mem_mb",
            "scheduler_worker_ram",
            "scheduler_worker_gpus",
            "scheduler_startup_script",
        ):
            value = response.get(key)
            if key in response and value is not None and value != "":
                metadata[key] = value
        if metadata:
            payload["metadata"] = {**dict(payload.get("metadata") or {}), **metadata}
    return payload


def _review_approval_payload(graph_id: str, params: dict[str, Any], execution_location: Any) -> dict[str, Any]:
    location = resolve_execution_location(execution_location)
    params_payload = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
    params_hash = hashlib.sha256(params_payload.encode("utf-8")).hexdigest()
    return {
        "schema": "morphic.execution_review_approval/v0",
        "graph_id": graph_id,
        "execution_location": location.location_id,
        "execution_location_metadata": dict(location.metadata or {}),
        "params_hash": f"sha256:{params_hash}",
    }


def _params_hash(params: dict[str, Any]) -> str:
    params_payload = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(params_payload.encode('utf-8')).hexdigest()}"


def _run_effective_params(run: dict[str, Any] | None, params: dict[str, Any]) -> dict[str, Any]:
    if params:
        return params
    if isinstance(run, dict) and isinstance(run.get("params"), dict):
        return dict(run["params"])
    return {}


def _attach_run(payload: dict[str, Any], run: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run, dict):
        return payload
    return {**payload, "run_id": run.get("run_id"), "run": run}


def _review_state_for_run(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": review.get("status"),
        "review_stage": review.get("review_stage"),
        "params_valid": review.get("params_valid"),
        "human_review": review.get("human_review"),
        "approved_execution_location": review.get("approved_execution_location"),
        "execution_location_changed_by_user": review.get("execution_location_changed_by_user"),
        "run_blocker": review.get("run_blocker"),
    }


def _diagnostic_resolution_options(
    location: Any,
    *,
    bundle_path: str | None,
    has_bundle: bool,
    has_path_manifest: bool,
    container_diagnostic: dict[str, Any],
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if location.kind == "local":
        container_command = str(container_diagnostic.get("command") or "").strip()
        container_available = bool(container_diagnostic.get("run_available") and container_command)
        runtime = str(container_diagnostic.get("preferred_runtime") or "").strip() or "container runtime"
        options.append(
            {
                "id": "run_local_container",
                "label": f"Run the downloaded bundle with {runtime}" if container_available else "Run the downloaded bundle with a container runtime",
                "recommended": container_available,
                "available": container_available,
                "api_managed": False,
                "execution_location": "local",
                "why": (
                    "This preserves caller-local file ownership while avoiding local Python package setup."
                    if container_available
                    else "Install Docker, Podman, or Apptainer before using the container launcher."
                ),
                "commands": ([f"cd {bundle_path}", container_command] if has_bundle and bundle_path and container_command else []),
                "requires": [f"{runtime} available"] if container_available else ["Docker, Podman, or Apptainer installed"],
            }
        )
        options.append(
            {
                "id": "run_local_shell",
                "label": "Run the downloaded bundle in the caller shell",
                "recommended": not container_available,
                "available": has_bundle,
                "api_managed": False,
                "execution_location": "local",
                "why": "Use this when the local shell has the required Python packages and can see the input files.",
                "commands": ([f"cd {bundle_path}", "bash run.sh"] if has_bundle and bundle_path else []),
                "requires": ["bash", "python3", "recipe Python packages", "caller-visible input paths"],
            }
        )
        options.append(
            {
                "id": "regenerate_for_server",
                "label": "Regenerate the bundle for Workbench server execution",
                "recommended": False,
                "available": True,
                "api_managed": True,
                "execution_location": "server",
                "why": "Use this when the Workbench API should run the job; all paths must be visible to the server.",
                "commands": [],
                "requires": ["Render again with execution_location=server", "server-visible input and output paths", "passing server preflight"],
            }
        )
    elif location.kind == "server":
        options.append(
            {
                "id": "fix_server_paths_and_preflight",
                "label": "Use server-visible paths and rerun preflight",
                "recommended": True,
                "available": has_bundle,
                "api_managed": True,
                "execution_location": "server",
                "why": "Workbench server execution is API-managed only after server preflight passes.",
                "commands": [],
                "requires": ["server-visible inputs", "writable output location", "passing preflight"],
            }
        )
    elif location.kind == "remote_ssh":
        metadata = dict(getattr(location, "metadata", None) or {})
        runtime = str(metadata.get("remote_container_runtime") or metadata.get("preferred_container_runtime") or "docker")
        host = str(metadata.get("remote_host") or "").strip()
        workdir = str(metadata.get("remote_workdir") or "").strip()
        commands = []
        if host and workdir:
            user = str(metadata.get("remote_user") or "").strip()
            hostspec = f"{user}@{host}" if user else host
            launcher = "./run.apptainer.sh" if runtime == "apptainer" else ("bash run.sh" if runtime == "shell" else "./run.docker.sh")
            commands = [f"ssh {hostspec}", f"cd {workdir}", launcher]
        options.append(
            {
                "id": "run_remote_ssh_container",
                "label": "Run the copied bundle on a remote SSH host",
                "recommended": True,
                "available": bool(has_bundle and host and workdir),
                "api_managed": True,
                "execution_location": "remote_ssh",
                "why": "The Workbench API can copy the generated bundle over SSH, run its container launcher, and copy outputs back.",
                "commands": commands,
                "requires": ["remote_host", "remote_workdir", f"{runtime} available on the SSH host", "remote-visible path bindings"],
            }
        )
    elif location.kind == "scheduler_temporal":
        metadata = dict(getattr(location, "metadata", None) or {})
        api_url = str(metadata.get("scheduler_api_url") or "http://127.0.0.1:8000")
        options.append(
            {
                "id": "run_local_temporal_scheduler",
                "label": "Run through the local Temporal scheduler",
                "recommended": True,
                "available": has_bundle,
                "api_managed": True,
                "execution_location": "scheduler_temporal",
                "why": "The Workbench API can stage the bundle into scheduler storage, submit a Temporal workflow, and collect outputs back into the bundle.",
                "commands": [],
                "requires": [f"scheduler API reachable at {api_url}", "local scheduler worker registered", "bundle-relative scheduler path bindings"],
            }
        )
    elif location.kind == "scheduler_remote_ssh":
        metadata = dict(getattr(location, "metadata", None) or {})
        api_url = str(metadata.get("scheduler_api_url") or "http://127.0.0.1:8000")
        host = str(metadata.get("remote_host") or "").strip()
        user = str(metadata.get("remote_user") or "").strip()
        workdir = str(metadata.get("remote_workdir") or "").strip()
        port = str(metadata.get("remote_port") or "22")
        queue = f"{user}@{host}:{port}" if host and user else ""
        options.append(
            {
                "id": "run_temporal_ssh_docker_scheduler",
                "label": "Run on remote SSH through the Temporal scheduler",
                "recommended": True,
                "available": bool(has_bundle and host and user and workdir),
                "api_managed": True,
                "execution_location": "scheduler_remote_ssh",
                "why": "The Workbench API can stage the bundle, submit a Temporal SSH Docker workflow, and collect outputs back into the bundle.",
                "commands": [],
                "requires": [
                    f"scheduler API reachable at {api_url}",
                    f"SSH Docker worker listening on {queue or 'user@host:port'}",
                    "remote Docker and rsync available",
                    "bundle-relative scheduler path bindings",
                ],
            }
        )
    else:
        options.append(
            {
                "id": "configure_executor_connector",
                "label": "Configure the required executor connector",
                "recommended": True,
                "available": False,
                "api_managed": False,
                "execution_location": location.location_id,
                "why": "This execution location is modeled but no connector is currently configured.",
                "commands": [],
                "requires": list(getattr(location, "required_connectors", []) or []),
            }
        )
    if not has_path_manifest:
        options.append(
            {
                "id": "regenerate_path_manifest",
                "label": "Regenerate the bundle so manifests/path_bindings.json is present",
                "recommended": not has_bundle,
                "available": True,
                "api_managed": False,
                "execution_location": location.location_id,
                "why": "Execution-location diagnostics need path bindings to explain what each locale can see.",
                "commands": [],
                "requires": ["render bundle again"],
            }
        )
    return options


def _workbench_handoff(
    graph_id: str,
    params: dict[str, Any],
    *,
    execution_location: Any,
    bundle_path: Any = None,
    review_stage: Any = None,
    action: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    location = resolve_execution_location(execution_location)
    payload = {
        "schema": "morphic.workbench_handoff/v0",
        "action": action,
        "run_id": str(run_id or "").strip() or None,
        "graph_id": graph_id,
        "params": params or {},
        "execution_location": location.location_id,
        "execution_location_request": location.as_dict(),
        "execution_location_metadata": dict(location.metadata or {}),
        "bundle_path": str(bundle_path or "").strip() or None,
        "review_stage": str(review_stage or "").strip() or None,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    fragment = f"#workbench={encoded}"
    base_url = os.environ.get("MORPHIC_WORKBENCH_PUBLIC_URL", "http://127.0.0.1:8890/").strip()
    if not base_url.endswith("/"):
        base_url = f"{base_url}/"
    query_url = f"{base_url}?workbench={encoded}"
    fragment_url = f"{base_url}{fragment}"
    return {
        "schema": "morphic.workbench_handoff/v0",
        "mode": "url_fragment",
        "url_fragment": fragment,
        "url": query_url,
        "preferred_url": query_url,
        "url_query": query_url,
        "url_fragment_full": fragment_url,
        "payload": payload,
        "instructions": (
            "Open preferred_url to prefill the Workbench browser form from this MCP result. "
            "url_fragment is retained for clients that need to append a fragment themselves."
        ),
    }


def _nfcore_graph_and_module(service: WorkbenchService, identifier: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    text = str(identifier or "").strip()
    if not text:
        return None, None

    graph = service.store.get_subgraph(text)
    module = None
    if graph is not None and not _is_nfcore_graph(graph):
        return None, None

    if graph is None:
        module = service.catalog.get_module(text)
        if module is not None and not _is_nfcore_module(module):
            return None, module
        for graph_id in _candidate_nfcore_graph_ids(text, module):
            graph = service.store.get_subgraph(graph_id)
            if graph is not None:
                break

    if graph is None:
        results = service.search_graphs(query=text, filters={"suite": "nf-core"}, limit=10)
        for item in results.get("results") or []:
            candidate = item.get("workflow_graph") if isinstance(item, dict) else None
            if isinstance(candidate, dict) and _is_nfcore_graph(candidate):
                graph = candidate
                break

    if graph is None or not _is_nfcore_graph(graph):
        return None, module

    if module is None:
        module_id = ""
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and node.get("module_id"):
                module_id = str(node["module_id"])
                break
        module = service.catalog.get_module(module_id) if module_id else None
    return graph, module


def _candidate_nfcore_graph_ids(module_id: str, module: dict[str, Any] | None) -> list[str]:
    candidates = [f"{module_id}_v0"]
    runtime = module.get("runtime") if isinstance(module, dict) and isinstance(module.get("runtime"), dict) else {}
    release = str(runtime.get("release") or "").strip() if isinstance(runtime, dict) else ""
    if release:
        candidates.insert(0, f"{module_id}_{_normalize_graph_component('v' + release)}")
    return candidates


def _is_nfcore_graph(graph: dict[str, Any]) -> bool:
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    return (
        str(graph.get("suite") or "") == "nf-core"
        or str(graph.get("recipe_family") or "") == "nf-core"
        or runtime.get("kind") == "nfcore_pipeline"
    )


def _is_nfcore_module(module: dict[str, Any]) -> bool:
    runtime = module.get("runtime") if isinstance(module.get("runtime"), dict) else {}
    return (
        str(module.get("recipe_family") or "") == "nf-core"
        or str(runtime.get("suite") or "") == "nf-core"
        or runtime.get("kind") == "nfcore_pipeline"
    )


def _normalize_graph_component(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "")).strip("_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized or "v0"


def execution_review_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["approved", "execution_location", "verified_paths"],
        "properties": {
            "approved": {
                "type": "boolean",
                "description": "True only after the user has reviewed and approved the graph, parameters, paths, and execution location.",
            },
            "execution_location": {
                "type": "string",
                "enum": ["local", "server", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
                "description": "Execution location selected by the user for the next Workbench step.",
            },
            "remote_host": {
                "type": "string",
                "description": "SSH host for remote_ssh execution.",
                "default": "",
            },
            "remote_user": {
                "type": "string",
                "description": "Optional SSH username for remote_ssh execution.",
                "default": "",
            },
            "remote_workdir": {
                "type": "string",
                "description": "Destination directory for the copied bundle on the SSH host.",
                "default": "",
            },
            "remote_container_runtime": {
                "type": "string",
                "enum": ["docker", "podman", "apptainer", "shell"],
                "description": "Remote runtime used to launch the copied bundle.",
                "default": "docker",
            },
            "remote_path_overrides": {
                "type": "object",
                "description": "Optional binding_id/param/field to remote path map used to localize manifests/path_bindings.json.",
                "additionalProperties": {"type": "string"},
                "default": {},
            },
            "verified_paths": {
                "type": "boolean",
                "description": "True when the user has checked that input and output paths match the selected execution location.",
            },
            "notes": {
                "type": "string",
                "description": "Optional user notes, requested changes, or path corrections.",
                "default": "",
            },
        },
    }
