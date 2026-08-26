"""Conversational planner — LangGraph-shaped state machine without UI route policy."""

from __future__ import annotations

import re
from typing import Any

from morphic_agent.graph.contracts import GraphIndex
from morphic_agent.graph.drafts import draft_workflow_graph, graph_draft_message, graph_intent_supported
from morphic_agent.graph.index import MorphicGraphIndex
from morphic_agent.planner.llm_fallback import complete_with_llm_fallback
from morphic_agent.planner.intent import (
    assay_catalog_modules,
    conversation_goal_text,
    downstream_catalog_modules,
    module_matches_for_request,
    planning_state_for_rnaseq,
    requests_assay_catalog,
    requests_differential_expression,
    requests_downstream_catalog,
    requests_explain_plan,
    requests_visualization_catalog,
    visualization_catalog_modules,
)
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore
from morphic_agent.suites.registry import discover_suite_inventory
from morphic_agent.suites.star import list_star_workflows


def _compact_text(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _suite_inventory_context() -> dict[str, Any]:
    inventory = discover_suite_inventory()
    suites: list[dict[str, Any]] = []
    for suite in inventory.get("suites") or []:
        if not isinstance(suite, dict):
            continue
        recipes: list[dict[str, Any]] = []
        for recipe in suite.get("recipes") or []:
            if not isinstance(recipe, dict):
                continue
            recipes.append(
                {
                    "workflow_id": recipe.get("workflow_id") or recipe.get("id"),
                    "title": _compact_text(recipe.get("title")),
                    "summary": _compact_text(recipe.get("summary")),
                    "kind": recipe.get("kind"),
                    "suite": recipe.get("suite") or suite.get("suite"),
                    "source_kind": recipe.get("source_kind"),
                }
            )
        suites.append(
            {
                "suite": suite.get("suite"),
                "label": suite.get("label"),
                "available": bool(suite.get("available")),
                "recipe_count": suite.get("recipe_count") or len(recipes),
                "recipes": recipes[:40],
            }
        )
    return {
        "schema": "morphic.suite_inventory_context/v0",
        "suite_count": len(suites),
        "suites": suites,
    }


def _candidate_graph_preview(graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not graph:
        return None
    schema = graph.get("params_schema") if isinstance(graph.get("params_schema"), dict) else {}
    fields: list[dict[str, Any]] = []
    for field in schema.get("fields") or []:
        if not isinstance(field, dict):
            continue
        fields.append(
            {
                "name": field.get("name"),
                "label": field.get("label"),
                "type": field.get("type"),
                "artifact_type": field.get("artifact_type"),
                "required": bool(field.get("required")),
                "choices": field.get("choices"),
                "default": field.get("default"),
            }
        )
    return {
        "graph_id": graph.get("graph_id"),
        "title": graph.get("title"),
        "materialization_status": graph.get("materialization_status"),
        "run_blocker": graph.get("run_blocker"),
        "nodes": [
            {
                "module_id": node.get("module_id"),
                "label": node.get("label"),
                "confidence_tier": node.get("confidence_tier"),
            }
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
        ],
        "required_human_inputs": graph.get("required_human_inputs") or schema.get("required") or [],
        "params_schema": {"fields": fields},
    }


def _compact_module_for_model(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "module_id": module.get("module_id"),
        "title": module.get("title"),
        "capabilities": module.get("capabilities") or [],
        "input_artifact_types": module.get("input_artifact_types") or [],
        "output_artifact_types": module.get("output_artifact_types") or [],
        "confidence_tier": module.get("confidence_tier"),
        "recipe_family": module.get("recipe_family"),
        "assay_profile": module.get("assay_profile"),
        "modalities": module.get("modalities") or [],
        "dataset_scope": module.get("dataset_scope"),
        "execution_policy": module.get("execution_policy") or {},
    }


class PlannerEngine:
    """Owns durable planning state; the API/UI only streams events."""

    def __init__(
        self,
        store: AgentStore | None = None,
        catalog: ModuleCatalog | None = None,
        graph_index: GraphIndex | None = None,
    ) -> None:
        self.store = store or AgentStore()
        self.catalog = catalog or ModuleCatalog()
        self.graph_index = graph_index or MorphicGraphIndex(self.catalog)

    def _load_state(self, thread_id: str) -> dict[str, Any]:
        return self.store.load_planner_state(thread_id) or {
            "thread_id": thread_id,
            "user_goal": "",
            "problem_signature": {},
            "known_facts": {},
            "pending_questions": [],
            "pending_downstream_requests": [],
            "candidate_graphs": [],
            "selected_graph": None,
            "approval_state": "none",
            "blockers": [],
            "confidence_summary": "unverified",
        }

    def _save_state(self, thread_id: str, state: dict[str, Any]) -> None:
        self.store.save_planner_state(thread_id, state)

    def handle_message(self, *, thread_id: str | None, goal: str) -> dict[str, Any]:
        thread_id = self.store.ensure_thread(thread_id)
        state = self._load_state(thread_id)
        turns = self.store.recent_turns(thread_id)
        session_context = {"recent_turns": [{"goal": turn["goal"]} for turn in turns if turn.get("goal")]}

        self.store.append_turn(thread_id, role="user", goal=goal)
        combined = conversation_goal_text(goal, session_context)

        def finish(response: dict[str, Any]) -> dict[str, Any]:
            response = self._dedupe_assistant_message(response, turns)
            self.store.append_turn(thread_id, role="assistant", goal="", payload=response)
            return response

        model_first = self._model_first_answer(thread_id, goal, state, turns)
        if model_first.get("ok") and self._requests_draft_confirmation(goal, state):
            pending = state.get("pending_model_action") if isinstance(state.get("pending_model_action"), dict) else {}
            draft_goal = str(pending.get("goal") or state.get("user_goal") or combined)
            response = self._draft_workflow_response(
                thread_id,
                draft_goal,
                state,
                model_first=model_first,
            )
            return finish(response)

        if model_first.get("ok") and model_first.get("text"):
            self._maybe_store_pending_draft(thread_id, combined, state)
            response = {
                "status": "model_response",
                "thread_id": thread_id,
                "assistant_message": model_first["text"],
                "model": {"provider": model_first.get("provider"), "name": model_first.get("model")},
                "model_first": True,
                "proposed_action": self._proposed_action_for_model_response(combined),
                "confidence_summary": "model_first_guidance",
            }
            return finish(response)

        if requests_explain_plan(goal) and state.get("selected_graph"):
            response = self.explain_current_plan(thread_id)
            return finish(response)

        if requests_assay_catalog(goal):
            response = self._model_first_assay_catalog_answer(thread_id, combined, state)
            return finish(response)

        if requests_downstream_catalog(goal):
            modules = downstream_catalog_modules(self.catalog)
            message = "Current downstream module candidates from the local catalog:\n" + "\n".join(
                f"- `{module['module_id']}` — {module['title']}" for module in modules
            )
            response = {
                "status": "planning",
                "thread_id": thread_id,
                "assistant_message": message,
                "downstream_catalog": {"modules": modules},
                "proposed_action": {"action": "answer_downstream_catalog"},
            }
            return finish(response)

        if requests_visualization_catalog(goal):
            response = self._visualization_catalog_answer(thread_id, state)
            return finish(response)

        if self._requires_capability_fallback(goal, state):
            response = self._fallback_answer(thread_id, combined, state)
            return finish(response)

        planning = planning_state_for_rnaseq(combined, session_context)
        if planning and not planning.get("ready_to_compose"):
            state["known_facts"] = planning.get("facts") or {}
            state["pending_questions"] = [planning.get("next_question") or ""]
            state["pending_downstream_requests"] = planning.get("pending_downstream_requests") or []
            self._save_state(thread_id, state)
            message = planning.get("next_question") or planning.get("status_message") or ""
            if not str(message).strip() and not model_first.get("ok"):
                message = (
                    "This prompt needs the configured model before the workbench can choose the right walkthrough response, "
                    f"but the model is not available. {model_first.get('error') or 'The model returned no response.'}"
                )
                response = {
                    "status": "model_unavailable",
                    "thread_id": thread_id,
                    "ready_to_draft": False,
                    "planning": planning,
                    "assistant_message": message,
                    "model_first": {
                        "ok": False,
                        "provider": model_first.get("provider"),
                        "model": model_first.get("model"),
                        "error": model_first.get("error"),
                    },
                    "workflow_id": planning.get("workflow_id"),
                }
                return finish(response)
            response = {
                "status": "planning",
                "thread_id": thread_id,
                "ready_to_draft": False,
                "planning": planning,
                "assistant_message": message,
                "workflow_id": planning.get("workflow_id"),
            }
            return finish(response)

        if not graph_intent_supported(combined) and not planning:
            response = self._fallback_answer(thread_id, combined, state)
            return finish(response)

        return finish(self._draft_workflow_response(thread_id, combined, state))

    def explain_current_plan(self, thread_id: str) -> dict[str, Any]:
        state = self._load_state(thread_id)
        graph = state.get("selected_graph")
        if not graph:
            return {
                "status": "planning",
                "thread_id": thread_id,
                "assistant_message": "No workflow graph is selected yet. Describe the analysis goal first.",
            }
        nodes = ", ".join(str(node.get("module_id")) for node in graph.get("nodes") or [])
        return {
            "status": "graph_draft",
            "thread_id": thread_id,
            "graph_id": graph.get("graph_id"),
            "assistant_message": f"I am composing: {nodes}. Blockers: {', '.join(state.get('blockers') or []) or 'none'}.",
            "workflow_graph": graph,
            "planner_state": state,
        }

    def _model_first_answer(
        self,
        thread_id: str,
        goal: str,
        state: dict[str, Any],
        turns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        context = self._model_first_context(thread_id, goal, state, turns)
        llm = complete_with_llm_fallback(goal, context)
        llm["model_first"] = True
        return llm

    def _model_first_context(
        self,
        thread_id: str,
        goal: str,
        state: dict[str, Any],
        turns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        planning = planning_state_for_rnaseq(goal, {"recent_turns": []})
        workflows_payload = list_star_workflows()
        workflows = workflows_payload.get("workflows") or []
        graph_preview = None
        if graph_intent_supported(goal) or (planning and planning.get("ready_to_compose")):
            try:
                graph_preview = _candidate_graph_preview(draft_workflow_graph(goal, self.catalog))
            except Exception:
                graph_preview = None
        return {
            "thread_id": thread_id,
            "routing_policy": (
                "The model is the first conversational decision-maker. Local recipes, graphs, modules, and "
                "workflow names are hints/tools for the model. Answer directly or ask clarifying questions first. "
                "If local tooling should draft parameters, workflow graphs, scripts, or execution bundles, ask the "
                "user to confirm before invoking those deterministic tools."
            ),
            "recent_turns": [
                {
                    "role": turn.get("role"),
                    "goal": turn.get("goal"),
                    "assistant_message": (turn.get("payload") or {}).get("assistant_message")
                    if isinstance(turn.get("payload"), dict)
                    else None,
                }
                for turn in turns[-8:]
            ],
            "planner_state": {
                "known_facts": state.get("known_facts") or {},
                "selected_graph_id": (state.get("selected_graph") or {}).get("graph_id")
                if isinstance(state.get("selected_graph"), dict)
                else None,
                "pending_model_action": state.get("pending_model_action"),
                "blockers": state.get("blockers") or [],
            },
            "input_clues": {
                "paired_end_fastq": bool(re.search(r"paired[- ]end|\bpe\b", goal.lower()) and "fastq" in goal.lower()),
                "fastq": "fastq" in goal.lower(),
            },
            "local_context": {
                "assay_modules": [_compact_module_for_model(module) for module in assay_catalog_modules(self.catalog)[:40]],
                "downstream_modules": [_compact_module_for_model(module) for module in downstream_catalog_modules(self.catalog)[:20]],
                "visualization_modules": [_compact_module_for_model(module) for module in visualization_catalog_modules(self.catalog)[:20]],
                "star_workflows": workflows[:20],
                "star_workflow_error": workflows_payload.get("error"),
                "suite_inventory": _suite_inventory_context(),
                "candidate_graph_preview": graph_preview,
            },
            "deterministic_hints": {
                "requests_assay_catalog": requests_assay_catalog(goal),
                "requests_downstream_catalog": requests_downstream_catalog(goal),
                "requests_visualization_catalog": requests_visualization_catalog(goal),
                "requests_explain_plan": requests_explain_plan(goal),
                "requests_differential_expression": requests_differential_expression(goal),
                "graph_intent_supported": graph_intent_supported(goal),
                "rnaseq_planning": planning,
            },
            "available_local_actions": [
                "answer directly from model",
                "ask a clarifying question",
                "suggest a local workflow graph draft and ask the user to confirm",
                "after confirmation, draft a reviewable parameter schema from local tooling",
                "after approval, render scripts/bundles through local tooling",
            ],
        }

    def _maybe_store_pending_draft(self, thread_id: str, goal: str, state: dict[str, Any]) -> None:
        if self._mentions_slam_seq(goal):
            known_facts = dict(state.get("known_facts") or {})
            known_facts["current_unmaterialized_topic"] = "slam_seq"
            state["known_facts"] = known_facts
            state.pop("pending_model_action", None)
            self._save_state(thread_id, state)
            return
        planning = planning_state_for_rnaseq(goal, {"recent_turns": []})
        if planning:
            state["known_facts"] = planning.get("facts") or state.get("known_facts") or {}
            state["pending_downstream_requests"] = planning.get("pending_downstream_requests") or []

        if graph_intent_supported(goal) or (planning and planning.get("ready_to_compose")):
            state["pending_model_action"] = {
                "action": "draft_workflow_after_confirmation",
                "goal": goal,
            }
            self._save_state(thread_id, state)
        elif planning:
            state.pop("pending_model_action", None)
            self._save_state(thread_id, state)

    def _proposed_action_for_model_response(self, goal: str) -> dict[str, Any]:
        if self._mentions_slam_seq(goal):
            return {
                "action": "model_answer_or_clarify",
                "requires_confirmation": False,
            }
        planning = planning_state_for_rnaseq(goal, {"recent_turns": []})
        if graph_intent_supported(goal) or (planning and planning.get("ready_to_compose")):
            return {
                "action": "ask_confirmation_to_draft",
                "requires_confirmation": True,
            }
        return {
            "action": "model_answer_or_clarify",
            "requires_confirmation": False,
        }

    @staticmethod
    def _requests_draft_confirmation(goal: str, state: dict[str, Any]) -> bool:
        pending = state.get("pending_model_action") if isinstance(state.get("pending_model_action"), dict) else {}
        if pending.get("action") != "draft_workflow_after_confirmation":
            return False
        lowered = goal.lower().strip()
        return bool(
            re.search(
                r"\b(yes|yep|draft|go ahead|proceed|compose|create|build|generate|make|do it|looks good)\b",
                lowered,
            )
        )

    def _draft_workflow_response(
        self,
        thread_id: str,
        goal: str,
        state: dict[str, Any],
        *,
        model_first: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        graph = draft_workflow_graph(goal, self.catalog)
        matches = module_matches_for_request(goal, self.catalog)
        unsupported = self._unsupported_downstream_requests(state.get("pending_downstream_requests") or [], graph)

        state["user_goal"] = goal
        state["candidate_graphs"] = [graph["graph_id"]]
        state["selected_graph"] = graph
        state["problem_signature"] = {"goal": goal, "capabilities": graph.get("capabilities") or []}
        state["blockers"] = [graph.get("run_blocker") or ""]
        if unsupported:
            state["blockers"].extend(unsupported)
        state.pop("pending_model_action", None)
        self._save_state(thread_id, state)

        assistant_bits = []
        assistant_bits.append(graph_draft_message(graph))
        deg_note = next((item.get("interpretation") for item in matches if item.get("interpretation")), None)
        if deg_note:
            assistant_bits.insert(0, deg_note)
        if any(item.get("module_id") == "volcano_plot" for item in matches):
            assistant_bits.append(
                "I also recognized the volcano-plot request; that is a visualization after DESeq2 produces "
                "a differential-expression table."
            )
        if unsupported:
            assistant_bits.append("Some requested downstream steps are not wired in the current graph: " + "; ".join(unsupported))

        response = {
            "status": "graph_draft",
            "thread_id": thread_id,
            "graph_id": graph["graph_id"],
            "workflow_graph": graph,
            "params_schema": graph.get("params_schema"),
            "required_human_inputs": graph.get("required_human_inputs"),
            "confidence_tier": graph.get("confidence_tier"),
            "materialization_status": graph.get("materialization_status"),
            "run_blocker": graph.get("run_blocker"),
            "assistant_message": " ".join(assistant_bits),
            "module_matches": matches,
            "draft_confirmation_required": False,
            "compose_confirmation_required": False,
            "proposed_action": {"action": "review_plan", "requires_confirmation": False},
            "planner_state": {
                "selected_graph_id": graph["graph_id"],
                "pending_downstream_requests": state.get("pending_downstream_requests") or [],
            },
        }
        if model_first:
            response["model_first"] = {
                "ok": bool(model_first.get("ok")),
                "provider": model_first.get("provider"),
                "model": model_first.get("model"),
            }
        return response

    @staticmethod
    def _unsupported_downstream_requests(pending: list[dict[str, Any]], graph: dict[str, Any]) -> list[str]:
        if not pending:
            return []
        present = {str(node.get("module_id")) for node in graph.get("nodes") or []}
        blockers: list[str] = []
        for request in pending:
            preferred = str(request.get("preferred_module") or "")
            capability = str(request.get("capability") or "")
            if preferred and preferred not in present:
                blockers.append(f"missing module `{preferred}` for capability `{capability}`")
            elif capability == "volcano_plot" and "volcano_plot" not in present:
                blockers.append("volcano plot requested but not included in the drafted graph")
        return blockers

    def _visualization_catalog_answer(self, thread_id: str, state: dict[str, Any]) -> dict[str, Any]:
        modules = visualization_catalog_modules(self.catalog)
        selected_graph = state.get("selected_graph") if isinstance(state.get("selected_graph"), dict) else {}
        current_ids = {
            str(node.get("module_id") or "")
            for node in selected_graph.get("nodes") or []
            if isinstance(node, dict)
        }
        module_by_id = {str(module.get("module_id") or ""): module for module in modules}
        current_visuals = [module_by_id[module_id] for module_id in current_ids if module_id in module_by_id]
        other_visuals = [module for module in modules if str(module.get("module_id") or "") not in current_ids]

        def line(module: dict[str, Any]) -> str:
            outputs = ", ".join(str(item) for item in module.get("output_artifact_types") or []) or "declared outputs"
            confidence = str(module.get("confidence_tier") or "unclassified")
            return f"- `{module.get('module_id')}` — {module.get('title')} ({outputs}; {confidence})"

        sections: list[str] = []
        if current_visuals:
            sections.append("Already in the current draft:\n" + "\n".join(line(module) for module in current_visuals))
        sections.append("Available visualization modules in the local catalog:\n" + "\n".join(line(module) for module in other_visuals[:12]))
        if len(other_visuals) > 12:
            sections.append(f"{len(other_visuals) - 12} additional visualization modules are registered but not shown here.")
        sections.append(
            "Some entries are runnable/tested recipes, while several Example perturbation plot surfaces are source-derived contracts "
            "until their renderers are registered. Asking for one should start a planning discussion before parameters are drafted."
        )
        return {
            "status": "answer",
            "thread_id": thread_id,
            "assistant_message": "\n\n".join(sections),
            "visualization_catalog": {"modules": modules},
            "proposed_action": {
                "action": "answer_visualization_catalog",
                "requires_confirmation": False,
            },
        }

    def _model_first_assay_catalog_answer(self, thread_id: str, goal: str, state: dict[str, Any]) -> dict[str, Any]:
        modules = assay_catalog_modules(self.catalog)
        context = {
            "routing_policy": (
                "This is an assay/workflow discovery question. The model must answer first from the local context "
                "and should not draft a workflow graph or parameter set yet, even if a local module appears to match."
            ),
            "known_facts": state.get("known_facts") or {},
            "selected_graph_id": (state.get("selected_graph") or {}).get("graph_id")
            if isinstance(state.get("selected_graph"), dict)
            else None,
            "input_clues": {
                "paired_end_fastq": bool(re.search(r"paired[- ]end|\\bpe\\b", goal.lower()) and "fastq" in goal.lower()),
                "fastq": "fastq" in goal.lower(),
            },
            "local_assay_and_module_catalog": [_compact_module_for_model(module) for module in modules[:40]],
            "suite_inventory": _suite_inventory_context(),
        }
        llm = complete_with_llm_fallback(goal, context)
        if llm.get("ok") and llm.get("text"):
            return {
                "status": "llm_fallback",
                "thread_id": thread_id,
                "assistant_message": llm["text"],
                "model": {"provider": llm.get("provider"), "name": llm.get("model")},
                "assay_catalog": {"modules": modules},
                "proposed_action": {
                    "action": "model_first_assay_discovery",
                    "requires_confirmation": False,
                },
                "confidence_summary": "llm_general_guidance_with_local_catalog",
            }

        return {
            "status": "fallback",
            "thread_id": thread_id,
            "assistant_message": (
                "This is an assay discovery question, so I should let the model reason over the local catalog before "
                "choosing a workbench recipe or drafting parameters. The LLM fallback is not available. "
                f"{llm.get('error') or 'No fallback error was reported.'}"
            ),
            "assay_catalog": {"modules": modules},
            "llm_fallback": {"ok": False, "error": llm.get("error")},
            "confidence_summary": "model_required_for_discovery",
        }

    @classmethod
    def _dedupe_assistant_message(cls, response: dict[str, Any], turns: list[dict[str, Any]]) -> dict[str, Any]:
        message = str(response.get("assistant_message") or "")
        if not message.strip():
            return response

        prior_messages = [
            str((turn.get("payload") or {}).get("assistant_message") or "")
            for turn in turns
            if turn.get("role") == "assistant" and isinstance(turn.get("payload"), dict)
        ]
        if not prior_messages:
            return response

        normalized_message = cls._normalize_text(message)
        prior_normalized = {cls._normalize_text(item) for item in prior_messages if item.strip()}
        if normalized_message in prior_normalized:
            deduped = dict(response)
            deduped["assistant_message"] = "No new details beyond the previous answer."
            deduped["response_deduped"] = True
            return deduped

        prior_units = {
            cls._normalize_text(unit)
            for prior in prior_messages
            for unit in cls._message_units(prior)
            if unit.strip()
        }
        units = cls._message_units(message)
        kept = [unit for unit in units if cls._normalize_text(unit) not in prior_units]
        if kept and len(kept) < len(units):
            deduped = dict(response)
            deduped["assistant_message"] = "\n".join(kept)
            deduped["response_deduped"] = True
            return deduped
        return response

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip()).casefold()

    @staticmethod
    def _message_units(text: str) -> list[str]:
        units: list[str] = []
        for block in re.split(r"\n{2,}", text.strip()):
            lines = [line.rstrip() for line in block.splitlines() if line.strip()]
            if len(lines) > 1:
                units.extend(lines)
            elif lines:
                units.append(lines[0])
        return units

    def _fallback_answer(self, thread_id: str, goal: str, state: dict[str, Any]) -> dict[str, Any]:
        local = self._local_capability_answer(goal)
        if local:
            topic = local.get("capability_topic")
            if topic:
                known_facts = dict(state.get("known_facts") or {})
                known_facts["current_unmaterialized_topic"] = topic
                state["known_facts"] = known_facts
                self._save_state(thread_id, state)
            return {
                "status": "answer",
                "thread_id": thread_id,
                **local,
            }

        context = {
            "selected_graph_id": (state.get("selected_graph") or {}).get("graph_id")
            if isinstance(state.get("selected_graph"), dict)
            else None,
            "known_facts": state.get("known_facts") or {},
            "candidate_graphs": state.get("candidate_graphs") or [],
            "local_modules": downstream_catalog_modules(self.catalog),
        }
        llm = complete_with_llm_fallback(goal, context)
        if llm.get("ok") and llm.get("text"):
            return {
                "status": "llm_fallback",
                "thread_id": thread_id,
                "assistant_message": llm["text"],
                "model": {"provider": llm.get("provider"), "name": llm.get("model")},
                "confidence_summary": "llm_general_guidance",
            }

        return {
            "status": "fallback",
            "thread_id": thread_id,
            "assistant_message": (
                "I do not have a verified BioDepot graph for that request in the current local registry, "
                "and the LLM fallback is not available. "
                f"{llm.get('error') or 'No fallback error was reported.'}"
            ),
            "confidence_summary": "unprepared_guidance",
            "llm_fallback": {"ok": False, "error": llm.get("error")},
        }

    @staticmethod
    def _mentions_slam_seq(goal: str) -> bool:
        lowered = goal.lower()
        return any(term in lowered for term in ("slam", "slam-seq", "slam seq", "thiolutin"))

    def _requires_capability_fallback(self, goal: str, state: dict[str, Any]) -> bool:
        if self._mentions_slam_seq(goal):
            return True

        known_facts = state.get("known_facts") if isinstance(state.get("known_facts"), dict) else {}
        if known_facts.get("current_unmaterialized_topic") != "slam_seq":
            return False

        lowered = goal.lower()
        if "bulk" in lowered and not any(term in lowered for term in ("slam", "it", "this", "that")):
            return False

        if requests_differential_expression(goal):
            return True
        return any(term in lowered for term in ("compose", "workflow", "run", "analy", "with it", "for it"))

    def _local_capability_answer(self, goal: str) -> dict[str, Any] | None:
        if not self._mentions_slam_seq(goal):
            return None

        workflows_payload = list_star_workflows()
        workflows = [
            item
            for item in workflows_payload.get("workflows") or []
            if "slam" in " ".join(
                [
                    str(item.get("workflow_id") or item.get("id") or ""),
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                ]
            ).lower()
        ]
        if not workflows:
            return None

        workflow_lines = "\n".join(
            f"- `{item.get('workflow_id') or item.get('id')}` — {item.get('title') or item.get('summary') or 'SLAM workflow'}"
            for item in workflows[:6]
        )
        if requests_differential_expression(goal):
            deg_workflows = [
                item
                for item in workflows
                if "deseq" in " ".join(
                    [
                        str(item.get("workflow_id") or item.get("id") or ""),
                        str(item.get("title") or ""),
                        str(item.get("summary") or ""),
                    ]
                ).lower()
            ]
            deg_lines = "\n".join(
                f"- `{item.get('workflow_id') or item.get('id')}` — {item.get('title') or item.get('summary') or 'SLAM DEG workflow'}"
                for item in deg_workflows[:3]
            )
            return {
                "assistant_message": (
                    "For SLAM-seq differential expression, the STAR Suite registry has SLAM/DESeq2 source material"
                    f"{':' if deg_lines else '.'}\n{deg_lines}\n\n"
                    "I should not substitute the generic bulk PE/DESeq2 graph for this. The SLAM DEG path still needs "
                    "the SLAM workflow decomposition/materializer work and is not yet decomposed into a verified composed graph."
                ),
                "suite_workflows": workflows,
                "confidence_summary": "local_suite_registry_answer",
                "proposed_action": {
                    "action": "answer_local_capability",
                    "requires_confirmation": False,
                },
                "capability_topic": "slam_seq",
            }
        return {
            "assistant_message": (
                "Yes. The local STAR Suite registry includes SLAM-seq workflow surfaces, including:\n"
                f"{workflow_lines}\n\n"
                "In this walking skeleton, those SLAM recipes are discoverable as suite workflows, but they are not yet "
                "decomposed into verified composable graph nodes like the current STAR post-MEX smoke and bulk PE/DESeq2 MVP paths. "
                "So I can discuss them and use their suite definitions as source material, but a fully verified composed SLAM graph "
                "still needs the graph decomposition/materializer work."
            ),
            "suite_workflows": workflows,
            "confidence_summary": "local_suite_registry_answer",
            "proposed_action": {
                "action": "answer_local_capability",
                "requires_confirmation": False,
            },
            "capability_topic": "slam_seq",
        }
