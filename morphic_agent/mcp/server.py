"""MCP stdio server for Workbench recipe and bundle operations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from morphic_agent.bundle.nfcore_pipeline import is_nfcore_pipeline_graph
from morphic_agent.harvest.nfcore import (
    harvest_nfcore_pipeline_path_to_registry,
    harvest_nfcore_remote_pipeline_to_registry,
    harvest_nfcore_schema_file_to_registry,
)
from morphic_agent.harvest.nfcore_decomposition import decompose_nfcore_pipeline
from morphic_agent.harvest.nfcore_remote import looks_like_nfcore_pipeline_spec
from morphic_agent.workbench import WorkbenchService

SUITE_IDS = ("star", "chromap", "multiomics")
TOOL_META_KEY = "morphic.workbench.tool_policy"


def _policy(
    *,
    read_only: bool,
    creates_artifact: bool = False,
    may_execute_code: bool = False,
    requires_human_approval: bool = False,
    elicits_user_input: bool = False,
    idempotent: bool | None = None,
    supported_execution_locations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "read_only": read_only,
        "idempotent": read_only if idempotent is None else idempotent,
        "creates_artifact": creates_artifact,
        "may_execute_code": may_execute_code,
        "requires_human_approval": requires_human_approval,
        "elicits_user_input": elicits_user_input,
        "supported_execution_locations": supported_execution_locations or [],
    }


TOOL_POLICIES: dict[str, dict[str, Any]] = {
    "workbench_model_status": _policy(read_only=True),
    "workbench_list_conversations": _policy(read_only=True),
    "workbench_get_conversation": _policy(read_only=True),
    "workbench_create_conversation": _policy(read_only=False, idempotent=False),
    "workbench_update_conversation": _policy(read_only=False, idempotent=False),
    "workbench_fork_conversation": _policy(read_only=False, idempotent=False),
    "workbench_list_suites": _policy(read_only=True),
    "workbench_list_recipes": _policy(read_only=True),
    "workbench_get_recipe": _policy(read_only=True),
    "workbench_list_modules": _policy(read_only=True),
    "workbench_get_module": _policy(read_only=True),
    "workbench_compose_graph": _policy(read_only=True),
    "workbench_search_graphs": _policy(read_only=True),
    "workbench_rebuild_graph_projection": _policy(read_only=False, idempotent=False),
    "workbench_get_projection_status": _policy(read_only=True),
    "workbench_validate_params": _policy(read_only=True),
    "workbench_start_run": _policy(
        read_only=False,
        idempotent=False,
        supported_execution_locations=["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
    ),
    "workbench_get_run": _policy(read_only=True),
    "workbench_attach_validation_to_run": _policy(read_only=False, idempotent=False),
    "workbench_request_user_review": _policy(
        read_only=True,
        requires_human_approval=True,
        elicits_user_input=True,
        idempotent=False,
        supported_execution_locations=["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
    ),
    "workbench_render_bundle": _policy(
        read_only=False,
        creates_artifact=True,
        requires_human_approval=True,
        supported_execution_locations=["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
    ),
    "workbench_preflight_bundle": _policy(
        read_only=True,
        supported_execution_locations=["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
    ),
    "workbench_execution_diagnostic": _policy(
        read_only=True,
        supported_execution_locations=["server", "local", "remote_ssh", "remote", "scheduler_temporal", "scheduler_remote_ssh"],
    ),
    "workbench_get_bundle_manifest": _policy(read_only=True),
    "workbench_decompose_nfcore_pipeline": _policy(read_only=True),
    "workbench_harvest_nfcore_pipeline": _policy(read_only=False, idempotent=False),
    "workbench_register_nfcore_recipe": _policy(read_only=False, idempotent=False),
    "workbench_list_nfcore_pipelines": _policy(read_only=True),
    "workbench_get_nfcore_recipe": _policy(read_only=True),
    "workbench_nfcore_validation_matrix": _policy(read_only=True),
    "workbench_list_nfcore_validations": _policy(read_only=True),
    "workbench_record_nfcore_reference_validation": _policy(read_only=False, idempotent=False),
    "workbench_render_nfcore_bundle": _policy(
        read_only=False,
        creates_artifact=True,
        requires_human_approval=True,
        supported_execution_locations=["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
    ),
    "workbench_preflight_nfcore_bundle": _policy(
        read_only=True,
        supported_execution_locations=["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"],
    ),
}


class WorkbenchUserReview(BaseModel):
    approved: bool = Field(
        description="True only after the user has reviewed and approved the graph, parameters, paths, and execution location."
    )
    execution_location: Literal["local", "server", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"] = Field(
        description="Execution location selected by the user for the next Workbench step."
    )
    remote_host: str = Field(default="", description="SSH host for remote_ssh execution.")
    remote_user: str = Field(default="", description="Optional SSH user for remote_ssh execution.")
    remote_workdir: str = Field(default="", description="Destination directory for the copied bundle on the SSH host.")
    remote_container_runtime: Literal["docker", "podman", "apptainer", "shell"] = Field(
        default="docker",
        description="Remote runtime used to launch the copied bundle.",
    )
    remote_path_overrides: str = Field(
        default="",
        description="Optional JSON object mapping binding_id/param/field to remote paths for manifests/path_bindings.json.",
    )
    verified_paths: bool = Field(
        description="True when the user has checked that the input and output paths match the selected execution location."
    )
    notes: str = Field(default="", description="Optional user notes, requested changes, or path corrections.")


def build_workbench_mcp(
    *,
    service: WorkbenchService | None = None,
    db_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    bundle_root: str | Path | None = None,
) -> FastMCP:
    """Build the Workbench MCP server without starting a transport."""

    workbench = service or WorkbenchService.create(db_path=db_path, catalog_path=catalog_path)
    root = Path(bundle_root or os.environ.get("MORPHIC_AGENT_BUNDLE_ROOT") or "/tmp/morphic-agent-bundles")
    mcp = FastMCP(
        "workbench",
        instructions=(
            "BioDepot Workbench recipe, graph, bundle, and preflight tools. "
            "This server renders review bundles but does not execute biological workflows."
        ),
        version="0.1.0",
    )

    @mcp.tool(
        name="workbench_model_status",
        description="Report whether the Workbench-configured built-in model is available.",
        annotations=_annotations("workbench_model_status"),
        meta=_tool_meta("workbench_model_status"),
    )
    def model_status(probe: bool = False) -> dict[str, Any]:
        return _with_policy("workbench_model_status", workbench.model_status(probe=probe))

    @mcp.tool(
        name="workbench_list_conversations",
        description="List conversations owned by the requested Workbench user, ordered by recent activity.",
        annotations=_annotations("workbench_list_conversations"),
        meta=_tool_meta("workbench_list_conversations"),
    )
    def list_conversations(
        user: str = "anonymous",
        status: Literal["active", "archived", "all"] = "active",
        query: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        try:
            payload = workbench.list_conversations(
                owner_user=user,
                status=status,
                query=query,
                limit=limit,
            )
        except ValueError as exc:
            payload = {"status": "error", "error": str(exc)}
        return _with_policy("workbench_list_conversations", payload)

    @mcp.tool(
        name="workbench_get_conversation",
        description="Get one owned conversation with its recent turns and linked workflow runs.",
        annotations=_annotations("workbench_get_conversation"),
        meta=_tool_meta("workbench_get_conversation"),
    )
    def get_conversation(
        conversation_id: str,
        user: str = "anonymous",
        turn_limit: int = 100,
        run_limit: int = 25,
    ) -> dict[str, Any]:
        payload, status = workbench.get_conversation(
            conversation_id,
            owner_user=user,
            turn_limit=turn_limit,
            run_limit=run_limit,
        )
        return _with_policy("workbench_get_conversation", {"http_status": status, **payload})

    @mcp.tool(
        name="workbench_create_conversation",
        description="Create a new owned Workbench conversation without adding a chat turn.",
        annotations=_annotations("workbench_create_conversation"),
        meta=_tool_meta("workbench_create_conversation"),
    )
    def create_conversation(
        user: str = "anonymous",
        session_id: str = "mcp",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _with_policy(
            "workbench_create_conversation",
            workbench.create_conversation(
                owner_user=user,
                session_id=session_id,
                title=title,
                metadata=metadata,
            ),
        )

    @mcp.tool(
        name="workbench_update_conversation",
        description="Rename, archive, or restore a conversation owned by the requested Workbench user.",
        annotations=_annotations("workbench_update_conversation"),
        meta=_tool_meta("workbench_update_conversation"),
    )
    def update_conversation(
        conversation_id: str,
        user: str = "anonymous",
        session_id: str = "mcp",
        title: str | None = None,
        status: Literal["active", "archived"] | None = None,
    ) -> dict[str, Any]:
        payload, http_status = workbench.update_conversation(
            conversation_id,
            owner_user=user,
            session_id=session_id,
            title=title,
            status=status,
        )
        return _with_policy("workbench_update_conversation", {"http_status": http_status, **payload})

    @mcp.tool(
        name="workbench_fork_conversation",
        description="Fork an owned conversation, optionally copying its turns and planner state.",
        annotations=_annotations("workbench_fork_conversation"),
        meta=_tool_meta("workbench_fork_conversation"),
    )
    def fork_conversation(
        conversation_id: str,
        user: str = "anonymous",
        session_id: str = "mcp",
        title: str = "",
        include_history: bool = True,
    ) -> dict[str, Any]:
        payload, http_status = workbench.fork_conversation(
            conversation_id,
            owner_user=user,
            session_id=session_id,
            title=title,
            include_history=include_history,
        )
        return _with_policy("workbench_fork_conversation", {"http_status": http_status, **payload})

    @mcp.tool(
        name="workbench_list_suites",
        description="List available Workbench assay suites and their default recipes.",
        annotations=_annotations("workbench_list_suites"),
        meta=_tool_meta("workbench_list_suites"),
    )
    def list_suites() -> dict[str, Any]:
        return _with_policy("workbench_list_suites", workbench.suites())

    @mcp.tool(
        name="workbench_list_recipes",
        description="List recipes, optionally filtered by suite, assay text, or complexity text.",
        annotations=_annotations("workbench_list_recipes"),
        meta=_tool_meta("workbench_list_recipes"),
    )
    def list_recipes(
        suite_id: str | None = None,
        assay: str | None = None,
        complexity: str | None = None,
    ) -> dict[str, Any]:
        suites = [str(suite_id).strip().lower()] if suite_id else list(SUITE_IDS)
        recipes: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for suite in suites:
            payload, status = workbench.suite_recipes(suite)
            if status != 200:
                errors.append({"suite_id": suite, "status": status, "payload": payload})
                continue
            for recipe in payload.get("recipes") or []:
                if isinstance(recipe, dict):
                    recipes.append({**recipe, "suite": recipe.get("suite") or suite})
        recipes = [
            recipe
            for recipe in recipes
            if _matches_filter(recipe, assay, fields=("id", "recipe_id", "workflow_id", "title", "summary", "kind", "suite"))
            and _matches_filter(recipe, complexity, fields=("kind", "runtime_class", "benchmark_policy", "visibility"))
        ]
        return _with_policy(
            "workbench_list_recipes",
            {
                "status": "ok" if not errors else "partial",
                "filters": {"suite_id": suite_id, "assay": assay, "complexity": complexity},
                "recipe_count": len(recipes),
                "recipes": recipes,
                "errors": errors,
            },
        )

    @mcp.tool(
        name="workbench_get_recipe",
        description="Get one recipe by id, recipe_id, or workflow_id.",
        annotations=_annotations("workbench_get_recipe"),
        meta=_tool_meta("workbench_get_recipe"),
    )
    def get_recipe(recipe_id: str, suite_id: str | None = None) -> dict[str, Any]:
        matches = _find_recipes(workbench, recipe_id, suite_id=suite_id)
        if not matches:
            return _with_policy(
                "workbench_get_recipe",
                {"status": "not_found", "recipe_id": recipe_id, "suite_id": suite_id, "recipe": None},
            )
        return _with_policy(
            "workbench_get_recipe",
            {
                "status": "ok",
                "recipe_id": recipe_id,
                "suite_id": suite_id,
                "recipe": matches[0],
                "alternate_matches": matches[1:],
            },
        )

    @mcp.tool(
        name="workbench_list_modules",
        description="List registered workbench modules, optionally filtered by query text.",
        annotations=_annotations("workbench_list_modules"),
        meta=_tool_meta("workbench_list_modules"),
    )
    def list_modules(query: str = "") -> dict[str, Any]:
        return _with_policy("workbench_list_modules", workbench.list_modules(query))

    @mcp.tool(
        name="workbench_get_module",
        description="Get one registered module contract by module id.",
        annotations=_annotations("workbench_get_module"),
        meta=_tool_meta("workbench_get_module"),
    )
    def get_module(module_id: str) -> dict[str, Any]:
        payload, status = workbench.get_module(module_id)
        return _with_policy("workbench_get_module", {"http_status": status, **payload})

    @mcp.tool(
        name="workbench_search_graphs",
        description=(
            "Search stored workflow graphs with text and typed filters. Returns ranked results "
            "with match reasons and workflow_graph payloads."
        ),
        annotations=_annotations("workbench_search_graphs"),
        meta=_tool_meta("workbench_search_graphs"),
    )
    def search_graphs(
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return _with_policy(
            "workbench_search_graphs",
            workbench.search_graphs(query=query, filters=filters or {}, limit=limit),
        )

    @mcp.tool(
        name="workbench_rebuild_graph_projection",
        description="Rebuild the disposable graph projection from canonical Workbench graph tables.",
        annotations=_annotations("workbench_rebuild_graph_projection"),
        meta=_tool_meta("workbench_rebuild_graph_projection"),
    )
    def rebuild_graph_projection(projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        return _with_policy(
            "workbench_rebuild_graph_projection",
            workbench.rebuild_graph_projection(projection_version),
        )

    @mcp.tool(
        name="workbench_get_projection_status",
        description="Return durable status and counts for a Workbench graph projection version.",
        annotations=_annotations("workbench_get_projection_status"),
        meta=_tool_meta("workbench_get_projection_status"),
    )
    def get_projection_status(projection_version: str = "morphic-agent-v0") -> dict[str, Any]:
        return _with_policy(
            "workbench_get_projection_status",
            workbench.projection_status(projection_version),
        )

    @mcp.tool(
        name="workbench_compose_graph",
        description="Draft a Workbench graph for a recipe goal. This returns review payload, not a runnable job.",
        annotations=_annotations("workbench_compose_graph"),
        meta=_tool_meta("workbench_compose_graph"),
    )
    def compose_graph(
        goal: str,
        constraints: dict[str, Any] | None = None,
        include_launchpad: bool = True,
    ) -> dict[str, Any]:
        if constraints:
            goal = f"{goal}\n\nConstraints:\n{json.dumps(constraints, indent=2, sort_keys=True)}"
        payload = workbench.draft_graph(goal, include_launchpad=include_launchpad)
        if constraints:
            payload["constraints"] = constraints
        return _with_policy("workbench_compose_graph", payload)

    @mcp.tool(
        name="workbench_validate_params",
        description="Validate graph parameters before bundle rendering.",
        annotations=_annotations("workbench_validate_params"),
        meta=_tool_meta("workbench_validate_params"),
    )
    def validate_params(graph_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return _with_policy("workbench_validate_params", workbench.validate_params(graph_id, params))

    @mcp.tool(
        name="workbench_start_run",
        description=(
            "Create a durable Workbench run state for a graph, params, and execution location. "
            "Pass the returned run_id to review, render, preflight, diagnostics, and execution calls."
        ),
        annotations=_annotations("workbench_start_run"),
        meta=_tool_meta("workbench_start_run"),
    )
    def start_run(
        graph_id: str,
        params: dict[str, Any] | None = None,
        execution_location: Any = "local",
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_workdir: str | None = None,
        remote_container_runtime: str | None = None,
        remote_path_overrides: dict[str, str] | None = None,
        remote_check: bool | None = None,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        execution_request = _execution_location_request(
            execution_location,
            remote_host=remote_host,
            remote_user=remote_user,
            remote_workdir=remote_workdir,
            remote_container_runtime=remote_container_runtime,
            remote_path_overrides=remote_path_overrides,
            remote_check=remote_check,
        )
        run = workbench.start_run(
            graph_id,
            params or {},
            execution_location=execution_request,
            request_context={"client": "mcp", "tool": "workbench_start_run", **(request_context or {})},
        )
        return _with_policy("workbench_start_run", {"status": "created", "run_id": run["run_id"], "run": run})

    @mcp.tool(
        name="workbench_get_run",
        description="Get the canonical server-side Workbench run state by run_id.",
        annotations=_annotations("workbench_get_run"),
        meta=_tool_meta("workbench_get_run"),
    )
    def get_run(run_id: str, user: str = "anonymous") -> dict[str, Any]:
        payload, status = workbench.get_run(run_id, owner_user=user)
        return _with_policy("workbench_get_run", {"http_status": status, **payload})

    @mcp.tool(
        name="workbench_attach_validation_to_run",
        description="Attach an existing workflow validation record to a durable Workbench run state.",
        annotations=_annotations("workbench_attach_validation_to_run"),
        meta=_tool_meta("workbench_attach_validation_to_run"),
    )
    def attach_validation_to_run(
        run_id: str,
        validation_id: str,
        user: str = "anonymous",
    ) -> dict[str, Any]:
        payload, status = workbench.attach_validation_to_run(
            run_id=run_id,
            validation_id=validation_id,
            owner_user=user,
        )
        return _with_policy("workbench_attach_validation_to_run", {"http_status": status, **payload})

    @mcp.tool(
        name="workbench_request_user_review",
        description=(
            "Ask the connected user to choose or verify the execution location and approve "
            "the graph parameters before rendering, preflight, or handoff. Uses MCP elicitation "
            "when the client supports it; never executes or renders a bundle."
        ),
        annotations=_annotations("workbench_request_user_review"),
        meta=_tool_meta("workbench_request_user_review"),
    )
    async def request_user_review(
        ctx: Context,
        graph_id: str,
        params: dict[str, Any] | None = None,
        proposed_execution_location: str = "local",
        bundle_path: str | None = None,
        review_stage: str = "before_render",
        review_surface: str | None = None,
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_workdir: str | None = None,
        remote_container_runtime: str | None = None,
        remote_path_overrides: dict[str, str] | None = None,
        remote_check: bool | None = None,
        request_context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        context = {"client": "mcp", "tool": "workbench_request_user_review", **(request_context or {})}
        execution_request = _execution_location_request(
            proposed_execution_location,
            remote_host=remote_host,
            remote_user=remote_user,
            remote_workdir=remote_workdir,
            remote_container_runtime=remote_container_runtime,
            remote_path_overrides=remote_path_overrides,
            remote_check=remote_check,
        )
        review = workbench.execution_review_request(
            graph_id,
            params or {},
            proposed_execution_location=execution_request,
            bundle_path=bundle_path,
            review_stage=review_stage,
            request_context=context,
            run_id=run_id,
        )
        if review.get("status") == "not_found":
            return _with_policy("workbench_request_user_review", review)

        surface = str(review_surface or os.environ.get("MORPHIC_WORKBENCH_REVIEW_SURFACE") or "mcp").strip().lower()
        if surface in {"browser", "web", "workbench"}:
            handoff = review.get("workbench_handoff") if isinstance(review.get("workbench_handoff"), dict) else {}
            browser_url = str(handoff.get("preferred_url") or handoff.get("url") or "").strip()
            return _with_policy(
                "workbench_request_user_review",
                {
                    **review,
                    "status": "needs_browser_review",
                    "interaction": {
                        "mode": "workbench_browser",
                        "action": "open_url",
                        "browser_review_url": browser_url,
                    },
                    "browser_review_url": browser_url,
                    "browser_handoff_url": browser_url,
                    "run_blocker": (
                        "Open browser_review_url in the Workbench browser form so the user can review "
                        "and approve graph, params, paths, and execution location on the server. "
                        "This MCP call intentionally does not return an approval token."
                    ),
                    "approved_next_step": None,
                    "browser_review_must_be_opened": True,
                    "mcp_render_blocked_until_browser_approval": True,
                    "required_next_step": {
                        "action": "open_browser_review_url",
                        "url": browser_url,
                        "instruction": (
                            "Open this URL for the user now. Do not call workbench_render_bundle, "
                            "workbench_preflight_bundle, or any local adapter until the Workbench browser "
                            "form has been approved."
                        ),
                    },
                    "forbidden_next_steps": [
                        "Do not call workbench_render_bundle from MCP for this review response.",
                        "Do not synthesize or reuse a review_approval_token.",
                        "Do not execute the bundle with local Python helpers or shell commands.",
                    ],
                    "elicitation": {"available": False, "reason": "browser review surface requested"},
                },
            )

        prompt = _review_prompt(review)
        try:
            response = await ctx.elicit(prompt, WorkbenchUserReview)
        except Exception as exc:
            return _with_policy(
                "workbench_request_user_review",
                _elicitation_unavailable_payload(review, str(exc)),
            )

        action = str(getattr(response, "action", "") or "")
        if action != "accept":
            return _with_policy(
                "workbench_request_user_review",
                {
                    **workbench.complete_execution_review(review, None, action=action, interaction_mode="mcp_elicitation"),
                    "elicitation": {"available": True, "action": action or "decline"},
                },
            )

        data = getattr(response, "data", None)
        if isinstance(data, BaseModel):
            human_review = data.model_dump()
        elif isinstance(data, dict):
            human_review = dict(data)
        else:
            human_review = {}
        return _with_policy(
            "workbench_request_user_review",
            {
                **workbench.complete_execution_review(
                    review,
                    human_review,
                    action="accept",
                    interaction_mode="mcp_elicitation",
                ),
                "elicitation": {"available": True, "action": "accept"},
            },
        )

    @mcp.tool(
        name="workbench_render_bundle",
        description=(
            "Render a review bundle for a graph and execution location. This does not run the bundle. "
            "Call workbench_request_user_review first and pass approved_next_step.arguments exactly, "
            "including review_approval_token."
        ),
        annotations=_annotations("workbench_render_bundle"),
        meta=_tool_meta("workbench_render_bundle"),
    )
    def render_bundle(
        graph_id: str,
        params: dict[str, Any],
        execution_location: Any = "local",
        out_root: str | None = None,
        review_approval_token: str | None = None,
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_workdir: str | None = None,
        remote_container_runtime: str | None = None,
        remote_path_overrides: dict[str, str] | None = None,
        remote_check: bool | None = None,
        request_context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        context = {"client": "mcp", "tool": "workbench_render_bundle", **(request_context or {})}
        execution_request = _execution_location_request(
            execution_location,
            remote_host=remote_host,
            remote_user=remote_user,
            remote_workdir=remote_workdir,
            remote_container_runtime=remote_container_runtime,
            remote_path_overrides=remote_path_overrides,
            remote_check=remote_check,
        )
        approval_blocker = workbench.review_approval_blocker(
            review_approval_token,
            graph_id,
            params,
            execution_location=execution_request,
        )
        if approval_blocker:
            return _with_policy(
                "workbench_render_bundle",
                {
                    "schema": "morphic.mcp_render_review_gate/v0",
                    "status": "blocked",
                    "graph_id": graph_id,
                    "execution_location": execution_request,
                    "run_blocker": approval_blocker,
                    "required_next_step": {
                        "tool_name": "workbench_request_user_review",
                        "instruction": (
                            "Ask the user to approve the graph, params, and execution location, then call "
                            "workbench_render_bundle with approved_next_step.arguments exactly."
                        ),
                    },
                },
            )
        payload = workbench.render_bundle(
            graph_id,
            params,
            out_root=Path(out_root).expanduser() if out_root else root,
            request_context=context,
            execution_location=execution_request,
            run_id=run_id,
        )
        return _with_policy("workbench_render_bundle", payload)

    @mcp.tool(
        name="workbench_preflight_bundle",
        description=(
            "Run Workbench preflight diagnostics for a graph or generated bundle. "
            "For local execution, pass the bundle_path returned by workbench_render_bundle; "
            "the result can validate bundle structure but direct API execution remains blocked."
        ),
        annotations=_annotations("workbench_preflight_bundle"),
        meta=_tool_meta("workbench_preflight_bundle"),
    )
    def preflight_bundle(
        graph_id: str,
        params: dict[str, Any] | None = None,
        execution_location: Any = "local",
        bundle_path: str | None = None,
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_workdir: str | None = None,
        remote_container_runtime: str | None = None,
        remote_path_overrides: dict[str, str] | None = None,
        remote_check: bool | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        execution_request = _execution_location_request(
            execution_location,
            remote_host=remote_host,
            remote_user=remote_user,
            remote_workdir=remote_workdir,
            remote_container_runtime=remote_container_runtime,
            remote_path_overrides=remote_path_overrides,
            remote_check=remote_check,
        )
        return _with_policy(
            "workbench_preflight_bundle",
            workbench.preflight_bundle(
                graph_id,
                params or {},
                execution_location=execution_request,
                bundle_path=bundle_path,
                run_id=run_id,
            ),
        )

    @mcp.tool(
        name="workbench_execution_diagnostic",
        description=(
            "Explain whether the selected execution location can run a generated bundle, "
            "including path manifest, container/runtime, and required local dependency diagnostics. "
            "This never executes the bundle."
        ),
        annotations=_annotations("workbench_execution_diagnostic"),
        meta=_tool_meta("workbench_execution_diagnostic"),
    )
    def execution_diagnostic(
        graph_id: str,
        bundle_path: str | None = None,
        params: dict[str, Any] | None = None,
        execution_location: Any = "local",
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_workdir: str | None = None,
        remote_container_runtime: str | None = None,
        remote_path_overrides: dict[str, str] | None = None,
        remote_check: bool | None = None,
        request_context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        context = {"client": "mcp", "tool": "workbench_execution_diagnostic", **(request_context or {})}
        execution_request = _execution_location_request(
            execution_location,
            remote_host=remote_host,
            remote_user=remote_user,
            remote_workdir=remote_workdir,
            remote_container_runtime=remote_container_runtime,
            remote_path_overrides=remote_path_overrides,
            remote_check=remote_check,
        )
        payload, status = workbench.execution_diagnostic(
            graph_id,
            params or {},
            execution_location=execution_request,
            bundle_path=bundle_path,
            request_context=context,
            run_id=run_id,
        )
        return _with_policy("workbench_execution_diagnostic", {"http_status": status, **payload})

    @mcp.tool(
        name="workbench_get_bundle_manifest",
        description="Read generated bundle manifests and file inventory. This does not execute scripts.",
        annotations=_annotations("workbench_get_bundle_manifest"),
        meta=_tool_meta("workbench_get_bundle_manifest"),
    )
    def get_bundle_manifest(bundle_path: str) -> dict[str, Any]:
        return _with_policy("workbench_get_bundle_manifest", _bundle_manifest(bundle_path))

    @mcp.tool(
        name="workbench_decompose_nfcore_pipeline",
        description=(
            "Index a local nf-core checkout into source files, declarations, include aliases, and statically resolved "
            "invocations. This is read-only, does not register components, and does not execute Nextflow."
        ),
        annotations=_annotations("workbench_decompose_nfcore_pipeline"),
        meta=_tool_meta("workbench_decompose_nfcore_pipeline"),
    )
    def decompose_nfcore_pipeline_tool(pipeline_path: str, strict: bool = False) -> dict[str, Any]:
        return _with_policy(
            "workbench_decompose_nfcore_pipeline",
            decompose_nfcore_pipeline(pipeline_path, strict=strict),
        )

    @mcp.tool(
        name="workbench_harvest_nfcore_pipeline",
        description=(
            "Harvest one local nf-core pipeline checkout or nextflow_schema.json into the Workbench registry. "
            "With allow_network=true, can fetch only small remote metadata files for nf-core/<pipeline> specs. "
            "This never downloads pipeline archives, containers, references, or workflow outputs."
        ),
        annotations=_annotations("workbench_harvest_nfcore_pipeline"),
        meta=_tool_meta("workbench_harvest_nfcore_pipeline"),
    )
    def harvest_nfcore_pipeline(
        pipeline_path: str,
        modules_json_path: str | None = None,
        schema_path: str | None = None,
        cache_root: str | None = None,
        release: str | None = None,
        allow_network: bool = False,
        decompose_source: bool = True,
        strict_decomposition: bool = False,
    ) -> dict[str, Any]:
        if schema_path:
            result = harvest_nfcore_schema_file_to_registry(
                schema_path,
                workbench.store,
                modules_json_path=modules_json_path,
                provenance={"harvested_by": "workbench_harvest_nfcore_pipeline"},
                cache_root=cache_root,
            )
        elif allow_network and looks_like_nfcore_pipeline_spec(pipeline_path):
            result = harvest_nfcore_remote_pipeline_to_registry(
                pipeline_path,
                workbench.store,
                release=release,
                provenance={"harvested_by": "workbench_harvest_nfcore_pipeline"},
                cache_root=cache_root,
            )
        elif looks_like_nfcore_pipeline_spec(pipeline_path):
            return _with_policy(
                "workbench_harvest_nfcore_pipeline",
                {
                    "status": "blocked",
                    "pipeline_path": pipeline_path,
                    "run_blocker": "Remote nf-core metadata harvest requires allow_network=true.",
                    "required_next_step": {
                        "tool_name": "workbench_harvest_nfcore_pipeline",
                        "arguments": {
                            "pipeline_path": pipeline_path,
                            "release": release,
                            "cache_root": cache_root,
                            "allow_network": True,
                        },
                    },
                },
            )
        else:
            result = harvest_nfcore_pipeline_path_to_registry(
                pipeline_path,
                workbench.store,
                decompose_source=decompose_source,
                strict_decomposition=strict_decomposition,
                provenance={"harvested_by": "workbench_harvest_nfcore_pipeline"},
                cache_root=cache_root,
            )
        workbench.catalog.reload()
        return _with_policy(
            "workbench_harvest_nfcore_pipeline",
            {
                **result.import_manifest,
                "workflow_graph": result.harvest_result.workflow_graph,
                "module_contract": result.harvest_result.module_contract,
            },
        )

    @mcp.tool(
        name="workbench_register_nfcore_recipe",
        description=(
            "Register one local nf-core nextflow_schema.json as a Workbench recipe graph. "
            "Alias for local schema harvest; does not download or execute workflows."
        ),
        annotations=_annotations("workbench_register_nfcore_recipe"),
        meta=_tool_meta("workbench_register_nfcore_recipe"),
    )
    def register_nfcore_recipe(
        schema_path: str,
        modules_json_path: str | None = None,
        cache_root: str | None = None,
    ) -> dict[str, Any]:
        result = harvest_nfcore_schema_file_to_registry(
            schema_path,
            workbench.store,
            modules_json_path=modules_json_path,
            provenance={"harvested_by": "workbench_register_nfcore_recipe"},
            cache_root=cache_root,
        )
        workbench.catalog.reload()
        return _with_policy(
            "workbench_register_nfcore_recipe",
            {
                **result.import_manifest,
                "workflow_graph": result.harvest_result.workflow_graph,
                "module_contract": result.harvest_result.module_contract,
            },
        )

    @mcp.tool(
        name="workbench_list_nfcore_pipelines",
        description="List harvested nf-core pipeline graphs currently stored in the Workbench registry.",
        annotations=_annotations("workbench_list_nfcore_pipelines"),
        meta=_tool_meta("workbench_list_nfcore_pipelines"),
    )
    def list_nfcore_pipelines(query: str = "", limit: int = 20) -> dict[str, Any]:
        return _with_policy(
            "workbench_list_nfcore_pipelines",
            workbench.search_graphs(query=query, filters={"suite": "nf-core"}, limit=limit),
        )

    @mcp.tool(
        name="workbench_get_nfcore_recipe",
        description="Get one harvested nf-core recipe graph and its module contract by graph id or module id.",
        annotations=_annotations("workbench_get_nfcore_recipe"),
        meta=_tool_meta("workbench_get_nfcore_recipe"),
    )
    def get_nfcore_recipe(identifier: str) -> dict[str, Any]:
        graph, module = _nfcore_graph_and_module(workbench, identifier)
        if graph is None:
            return _with_policy(
                "workbench_get_nfcore_recipe",
                {"status": "not_found", "identifier": identifier, "workflow_graph": None, "module_contract": None},
            )
        if not is_nfcore_pipeline_graph(graph):
            return _with_policy(
                "workbench_get_nfcore_recipe",
                {"status": "blocked", "identifier": identifier, "run_blocker": "The matched graph is not an nf-core pipeline graph."},
            )
        return _with_policy(
            "workbench_get_nfcore_recipe",
            {
                "status": "ok",
                "identifier": identifier,
                "graph_id": graph.get("graph_id"),
                "module_id": module.get("module_id") if isinstance(module, dict) else None,
                "workflow_graph": graph,
                "module_contract": module,
            },
        )

    @mcp.tool(
        name="workbench_nfcore_validation_matrix",
        description="Report default-safe indexed, render, preflight, and reference-validation status for harvested nf-core recipes.",
        annotations=_annotations("workbench_nfcore_validation_matrix"),
        meta=_tool_meta("workbench_nfcore_validation_matrix"),
    )
    def nfcore_validation_matrix(
        out_root: str = "",
        execution_location: str = "server",
        render: bool = True,
        preflight: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        return _with_policy(
            "workbench_nfcore_validation_matrix",
            workbench.nfcore_validation_matrix(
                out_root=out_root or None,
                execution_location=execution_location,
                render=render,
                preflight=preflight,
                limit=limit,
            ),
        )

    @mcp.tool(
        name="workbench_list_nfcore_validations",
        description=(
            "List stored nf-core validation records, optionally filtered by graph, status, comparator, "
            "executor, fixture, profile, or source manifest hash."
        ),
        annotations=_annotations("workbench_list_nfcore_validations"),
        meta=_tool_meta("workbench_list_nfcore_validations"),
    )
    def list_nfcore_validations(
        graph_id: str = "",
        status: str = "",
        comparator_kind: str = "",
        executor: str = "",
        fixture_id: str = "",
        profile: str = "",
        source_manifest_hash: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        return _with_policy(
            "workbench_list_nfcore_validations",
            workbench.list_nfcore_validations(
                graph_id=graph_id,
                status=status,
                comparator_kind=comparator_kind,
                executor=executor,
                fixture_id=fixture_id,
                profile=profile,
                source_manifest_hash=source_manifest_hash,
                limit=limit,
            ),
        )

    @mcp.tool(
        name="workbench_record_nfcore_reference_validation",
        description="Record an operator-produced nf-core reference-Nextflow comparison manifest as Workbench validation evidence.",
        annotations=_annotations("workbench_record_nfcore_reference_validation"),
        meta=_tool_meta("workbench_record_nfcore_reference_validation"),
    )
    def record_nfcore_reference_validation(graph_id: str, comparison_manifest: dict[str, Any], run_id: str = "") -> dict[str, Any]:
        payload, status = workbench.record_nfcore_reference_validation(
            graph_id=graph_id,
            comparison_manifest=comparison_manifest,
            run_id=run_id or None,
        )
        return _with_policy("workbench_record_nfcore_reference_validation", {"http_status": status, **payload})

    @mcp.tool(
        name="workbench_render_nfcore_bundle",
        description=(
            "Render a reviewable nf-core Nextflow bundle for a harvested nf-core graph. "
            "Requires the same review_approval_token gate as workbench_render_bundle."
        ),
        annotations=_annotations("workbench_render_nfcore_bundle"),
        meta=_tool_meta("workbench_render_nfcore_bundle"),
    )
    def render_nfcore_bundle(
        graph_id: str,
        params: dict[str, Any],
        execution_location: Any = "local",
        out_root: str | None = None,
        review_approval_token: str | None = None,
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_workdir: str | None = None,
        remote_container_runtime: str | None = None,
        remote_path_overrides: dict[str, str] | None = None,
        remote_check: bool | None = None,
        request_context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        graph, _ = _nfcore_graph_and_module(workbench, graph_id)
        if graph is None or not is_nfcore_pipeline_graph(graph):
            return _with_policy(
                "workbench_render_nfcore_bundle",
                {"status": "not_found", "graph_id": graph_id, "run_blocker": "No harvested nf-core graph matched graph_id."},
            )
        context = {"client": "mcp", "tool": "workbench_render_nfcore_bundle", **(request_context or {})}
        execution_request = _execution_location_request(
            execution_location,
            remote_host=remote_host,
            remote_user=remote_user,
            remote_workdir=remote_workdir,
            remote_container_runtime=remote_container_runtime,
            remote_path_overrides=remote_path_overrides,
            remote_check=remote_check,
        )
        approval_blocker = workbench.review_approval_blocker(
            review_approval_token,
            graph_id,
            params,
            execution_location=execution_request,
        )
        if approval_blocker:
            return _with_policy(
                "workbench_render_nfcore_bundle",
                {
                    "schema": "morphic.mcp_render_review_gate/v0",
                    "status": "blocked",
                    "graph_id": graph_id,
                    "execution_location": execution_request,
                    "run_blocker": approval_blocker,
                    "required_next_step": {"tool_name": "workbench_request_user_review"},
                },
            )
        payload = workbench.render_bundle(
            graph_id,
            params,
            out_root=Path(out_root).expanduser() if out_root else root,
            request_context=context,
            execution_location=execution_request,
            run_id=run_id,
        )
        return _with_policy("workbench_render_nfcore_bundle", payload)

    @mcp.tool(
        name="workbench_preflight_nfcore_bundle",
        description="Run nf-core bundle preflight diagnostics for a harvested nf-core graph or generated bundle.",
        annotations=_annotations("workbench_preflight_nfcore_bundle"),
        meta=_tool_meta("workbench_preflight_nfcore_bundle"),
    )
    def preflight_nfcore_bundle_tool(
        graph_id: str,
        params: dict[str, Any] | None = None,
        execution_location: Any = "local",
        bundle_path: str | None = None,
        remote_host: str | None = None,
        remote_user: str | None = None,
        remote_workdir: str | None = None,
        remote_container_runtime: str | None = None,
        remote_path_overrides: dict[str, str] | None = None,
        remote_check: bool | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        graph, _ = _nfcore_graph_and_module(workbench, graph_id)
        if graph is None or not is_nfcore_pipeline_graph(graph):
            return _with_policy(
                "workbench_preflight_nfcore_bundle",
                {"status": "not_found", "graph_id": graph_id, "run_blocker": "No harvested nf-core graph matched graph_id."},
            )
        execution_request = _execution_location_request(
            execution_location,
            remote_host=remote_host,
            remote_user=remote_user,
            remote_workdir=remote_workdir,
            remote_container_runtime=remote_container_runtime,
            remote_path_overrides=remote_path_overrides,
            remote_check=remote_check,
        )
        return _with_policy(
            "workbench_preflight_nfcore_bundle",
            workbench.preflight_bundle(
                graph_id,
                params or {},
                execution_location=execution_request,
                bundle_path=bundle_path,
                run_id=run_id,
            ),
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Workbench MCP server.")
    parser.add_argument("--transport", default="stdio", choices=("stdio",), help="MCP transport to serve.")
    parser.add_argument("--db-path", default=os.environ.get("MORPHIC_AGENT_DB"), help="Optional Workbench sqlite DB path.")
    parser.add_argument("--catalog-path", default=os.environ.get("MORPHIC_AGENT_CATALOG"), help="Optional registry catalog path.")
    parser.add_argument(
        "--bundle-root",
        default=os.environ.get("MORPHIC_AGENT_BUNDLE_ROOT") or "/tmp/morphic-agent-bundles",
        help="Default root for generated review bundles.",
    )
    args = parser.parse_args(argv)
    mcp = build_workbench_mcp(db_path=args.db_path, catalog_path=args.catalog_path, bundle_root=args.bundle_root)
    mcp.run(transport=args.transport, show_banner=False)


def _tool_meta(tool_name: str) -> dict[str, Any]:
    return {TOOL_META_KEY: TOOL_POLICIES[tool_name]}


def _execution_location_request(
    execution_location: Any,
    *,
    remote_host: str | None = None,
    remote_user: str | None = None,
    remote_workdir: str | None = None,
    remote_container_runtime: str | None = None,
    remote_path_overrides: dict[str, str] | None = None,
    remote_check: bool | None = None,
) -> Any:
    if isinstance(execution_location, dict):
        payload = dict(execution_location)
    else:
        payload = {"location_id": str(execution_location or "local")}
    location_id = str(payload.get("location_id") or payload.get("kind") or "").strip()
    has_remote_details = any(
        value is not None and value != "" and value != {}
        for value in (
            remote_host,
            remote_user,
            remote_workdir,
            remote_container_runtime,
            remote_path_overrides,
            remote_check,
        )
    )
    remote_capable_ids = {"remote_ssh", "scheduler_remote_ssh", "temporal_ssh", "scheduler_ssh", "ssh_scheduler", "remote_ssh_scheduler"}
    if location_id not in remote_capable_ids and has_remote_details:
        payload = {"location_id": "remote_ssh", "metadata": dict(payload.get("metadata") or {})}
        location_id = "remote_ssh"
    if location_id not in remote_capable_ids:
        return execution_location
    metadata = dict(payload.get("metadata") or {})
    for key, value in {
        "remote_host": remote_host,
        "remote_user": remote_user,
        "remote_workdir": remote_workdir,
        "remote_container_runtime": remote_container_runtime,
        "remote_path_overrides": remote_path_overrides,
        "remote_check": remote_check,
    }.items():
        if value is not None and value != "":
            metadata[key] = value
    payload["metadata"] = metadata
    return payload


def _annotations(tool_name: str) -> dict[str, Any]:
    policy = TOOL_POLICIES[tool_name]
    return {
        "readOnlyHint": bool(policy["read_only"]),
        "destructiveHint": False,
        "idempotentHint": bool(policy["idempotent"]),
        "openWorldHint": False,
    }


def _with_policy(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "mcp_tool": {"name": tool_name, **TOOL_POLICIES[tool_name]}}


def _nfcore_graph_and_module(workbench: WorkbenchService, identifier: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    text = str(identifier or "").strip()
    if not text:
        return None, None
    graph = workbench.store.get_subgraph(text)
    module = None
    if graph is None:
        module = workbench.catalog.get_module(text)
        if module is not None:
            graph_id = f"{text}_v0"
            runtime = module.get("runtime") if isinstance(module.get("runtime"), dict) else {}
            release = str(runtime.get("release") or "").strip()
            if release:
                release_id = "v" + release.replace(".", "_").replace("-", "_")
                graph_id = f"{text}_{release_id}"
            graph = workbench.store.get_subgraph(graph_id)
    if graph is None:
        results = workbench.search_graphs(query=text, filters={"suite": "nf-core"}, limit=1)
        first = (results.get("results") or [None])[0]
        graph = first.get("workflow_graph") if isinstance(first, dict) else None
    if graph is None:
        return None, module
    if module is None:
        module_id = ""
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and node.get("module_id"):
                module_id = str(node["module_id"])
                break
        module = workbench.catalog.get_module(module_id) if module_id else None
    return graph, module


def _review_prompt(review: dict[str, Any]) -> str:
    location = review.get("proposed_execution_location") if isinstance(review.get("proposed_execution_location"), dict) else {}
    validation = review.get("params_validation") if isinstance(review.get("params_validation"), dict) else {}
    diagnostic = review.get("diagnostic") if isinstance(review.get("diagnostic"), dict) else {}
    items = "\n".join(f"- {item}" for item in review.get("review_items") or [])
    blockers = diagnostic.get("blockers") or []
    blocker_text = "\n".join(f"- {item}" for item in blockers) if blockers else "- none"
    return "\n".join(
        [
            "Workbench user review required.",
            f"Graph: {review.get('graph_title') or review.get('graph_id')}",
            f"Review stage: {review.get('review_stage')}",
            f"Proposed execution location: {location.get('label') or location.get('kind') or location.get('location_id')}",
            f"Parameter validation: {validation.get('status') or 'not_run'}",
            f"Bundle path: {review.get('bundle_path') or 'not rendered yet'}",
            "",
            "Review items:",
            items or "- Review graph, parameters, paths, and execution location.",
            "",
            "Current blockers or location limits:",
            blocker_text,
            "",
            "Approve only if this is the intended graph, the selected execution location is correct, "
            "and paths have been checked for that location.",
        ]
    )


def _elicitation_unavailable_payload(review: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        **review,
        "status": "needs_user_input",
        "elicitation": {
            "available": False,
            "error": error,
            "response_schema": WorkbenchUserReview.model_json_schema(),
        },
        "human_review": None,
        "run_blocker": "Client did not complete MCP elicitation; ask the user to review this form and call the next Workbench step only after approval.",
    }


def _matches_filter(recipe: dict[str, Any], needle: str | None, *, fields: tuple[str, ...]) -> bool:
    value = str(needle or "").strip().lower()
    if not value:
        return True
    haystack = " ".join(str(recipe.get(field) or "") for field in fields).lower()
    return value in haystack


def _find_recipes(service: WorkbenchService, recipe_id: str, *, suite_id: str | None = None) -> list[dict[str, Any]]:
    target = str(recipe_id or "").strip()
    if not target:
        return []
    suites = [str(suite_id).strip().lower()] if suite_id else list(SUITE_IDS)
    matches: list[dict[str, Any]] = []
    for suite in suites:
        payload, status = service.suite_recipes(suite)
        if status != 200:
            continue
        for recipe in payload.get("recipes") or []:
            if not isinstance(recipe, dict):
                continue
            aliases = {
                str(recipe.get("id") or ""),
                str(recipe.get("recipe_id") or ""),
                str(recipe.get("workflow_id") or ""),
            }
            if target in aliases:
                matches.append({**recipe, "suite": recipe.get("suite") or suite})
    return matches


def _bundle_manifest(bundle_path: str) -> dict[str, Any]:
    bundle = Path(bundle_path).expanduser()
    if not bundle.exists() or not bundle.is_dir():
        return {"status": "not_found", "bundle_path": str(bundle), "error": "bundle_path does not exist or is not a directory"}

    manifests = {
        "workflow_graph": _read_json(bundle / "workflow_graph.json"),
        "recipe": _read_json(bundle / "recipe.json"),
        "params_review": _read_json(bundle / "params.review.json"),
        "params_schema": _read_json(bundle / "params.schema.json"),
        "source_manifest": _read_json(bundle / "manifests" / "source_manifest.json"),
        "path_bindings": _read_json(bundle / "manifests" / "path_bindings.json"),
        "container": _read_json(bundle / "manifests" / "container.json"),
    }
    files = sorted(str(path.relative_to(bundle)) for path in bundle.rglob("*") if path.is_file())
    return {
        "status": "ok",
        "bundle_path": str(bundle),
        "files": files,
        "has_run_script": (bundle / "run.sh").is_file(),
        "manifests": manifests,
    }


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.is_file():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, (dict, list)) else None


if __name__ == "__main__":
    main()
