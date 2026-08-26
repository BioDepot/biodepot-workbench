"""Durable agent thread and planner state — SQLite-backed Postgres-shaped store."""

from __future__ import annotations

import json
import sqlite3
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from morphic_agent.db.session import initialize_sqlite_database
from morphic_agent.registry.repositories import (
    BundleRepository,
    ConversationRepository,
    ExecutionRepository,
    GraphRepository,
    GraphSearchRepository,
    ProjectionRepository,
    PreflightRepository,
    ReviewApprovalRepository,
    RunRepository,
    WorkflowValidationRepository,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{_sha256_json(payload)[:16]}"


class AgentStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        config = initialize_sqlite_database(db_path)
        if config.sqlite_path is None:
            raise ValueError("AgentStore requires a SQLite database path")
        self.db_path = config.sqlite_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph_repository = GraphRepository(self._connect)
        self.conversation_repository = ConversationRepository(self._connect)
        self.graph_search_repository = GraphSearchRepository(self.graph_repository)
        self.projection_repository = ProjectionRepository(self._connect)
        self.bundle_repository = BundleRepository(self._connect)
        self.review_approval_repository = ReviewApprovalRepository(self._connect)
        self.run_repository = RunRepository(self._connect)
        self.preflight_repository = PreflightRepository(self._connect)
        self.execution_repository = ExecutionRepository(self._connect)
        self.workflow_validation_repository = WorkflowValidationRepository(self._connect)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_thread(self, thread_id: str | None = None) -> str:
        thread_id = thread_id or f"thread-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_threads(thread_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (thread_id, now, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO conversations(
                  conversation_id, thread_id, owner_user, title, status,
                  origin_session_id, last_session_id, parent_conversation_id,
                  metadata_json, created_at, updated_at, archived_at
                ) VALUES (?, ?, 'anonymous', 'New conversation', 'active',
                          NULL, NULL, NULL, ?, ?, ?, NULL)
                """,
                (thread_id, thread_id, json.dumps({"created_by": "ensure_thread"}), now, now),
            )
        return thread_id

    def append_turn(self, thread_id: str, *, role: str, goal: str = "", payload: dict[str, Any] | None = None) -> None:
        self.ensure_thread(thread_id)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_turns(thread_id, role, goal, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, role, goal, json.dumps(payload or {}), now),
            )
            conn.execute("UPDATE agent_threads SET updated_at=? WHERE thread_id=?", (now, thread_id))
            conn.execute("UPDATE conversations SET updated_at=? WHERE thread_id=?", (now, thread_id))

    def recent_turns(self, thread_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, goal, payload_json, created_at
                FROM agent_turns
                WHERE thread_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        turns = []
        for row in reversed(rows):
            turns.append(
                {
                    "role": row["role"],
                    "goal": row["goal"],
                    "payload": json.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                }
            )
        return turns

    def save_planner_state(self, thread_id: str, state: dict[str, Any]) -> None:
        self.ensure_thread(thread_id)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO planner_states(thread_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                  state_json=excluded.state_json,
                  updated_at=excluded.updated_at
                """,
                (thread_id, json.dumps(state), now),
            )
            conn.execute("UPDATE conversations SET updated_at=? WHERE thread_id=?", (now, thread_id))

    def create_conversation(
        self,
        *,
        owner_user: str,
        title: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        parent_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        return self.conversation_repository.create(
            owner_user=owner_user,
            title=title,
            origin_session_id=session_id,
            metadata=metadata,
            conversation_id=conversation_id,
            parent_conversation_id=parent_conversation_id,
        )

    def ensure_conversation(
        self,
        conversation_id: str | None,
        *,
        owner_user: str,
        session_id: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        return self.conversation_repository.ensure_for_thread(
            conversation_id,
            owner_user=owner_user,
            session_id=session_id,
            title=title,
        )

    def get_conversation(self, conversation_id: str, *, owner_user: str) -> dict[str, Any] | None:
        return self.conversation_repository.get(conversation_id, owner_user=owner_user)

    def list_conversations(
        self,
        *,
        owner_user: str,
        status: str = "active",
        query: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.conversation_repository.list(
            owner_user=owner_user,
            status=status,
            query=query,
            limit=limit,
        )

    def update_conversation(
        self,
        conversation_id: str,
        *,
        owner_user: str,
        title: str | None = None,
        status: str | None = None,
        session_id: str = "",
    ) -> dict[str, Any] | None:
        return self.conversation_repository.update(
            conversation_id,
            owner_user=owner_user,
            title=title,
            status=status,
            session_id=session_id,
        )

    def fork_conversation(
        self,
        conversation_id: str,
        *,
        owner_user: str,
        session_id: str = "",
        title: str = "",
        include_history: bool = True,
    ) -> dict[str, Any] | None:
        return self.conversation_repository.fork(
            conversation_id,
            owner_user=owner_user,
            session_id=session_id,
            title=title,
            include_history=include_history,
        )

    def conversation_runs(self, conversation_id: str, *, owner_user: str, limit: int = 25) -> list[dict[str, Any]]:
        return self.conversation_repository.runs(conversation_id, owner_user=owner_user, limit=limit)

    def link_conversation_run(self, conversation_id: str, run_id: str, *, owner_user: str) -> None:
        self.conversation_repository.link_run(conversation_id, run_id, owner_user=owner_user)

    def load_planner_state(self, thread_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM planner_states WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["state_json"])

    def import_module_catalog(self, payload: dict[str, Any], *, source_path: str | Path = "") -> dict[str, Any]:
        modules = payload.get("modules") if isinstance(payload.get("modules"), list) else []
        source_payload = {"schema": payload.get("schema"), "modules": modules}
        source_hash = _sha256_json(source_payload)
        source_file_id = _stable_id("source", {"path": str(source_path), "hash": source_hash})
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_files(source_file_id, source_kind, source_path, source_hash, raw_payload_json, extracted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_file_id) DO UPDATE SET
                  source_hash=excluded.source_hash,
                  raw_payload_json=excluded.raw_payload_json,
                  extracted_at=excluded.extracted_at
                """,
                (source_file_id, "module_catalog", str(source_path), source_hash, json.dumps(source_payload), now),
            )
            imported = 0
            for module in modules:
                if not isinstance(module, dict) or not module.get("module_id"):
                    continue
                module_id = str(module["module_id"])
                contract_hash = _sha256_json(module)
                version_id = _stable_id("module", {"module_id": module_id, "hash": contract_hash})
                runtime = module.get("runtime") if isinstance(module.get("runtime"), dict) else {}
                evidence = module.get("evidence") if isinstance(module.get("evidence"), list) else []
                conn.execute(
                    """
                    INSERT INTO module_versions(
                      version_id, module_id, version, title, runtime_kind, contract_json,
                      confidence_tier, provenance_json, source_file_id, source_hash, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(version_id) DO UPDATE SET
                      title=excluded.title,
                      runtime_kind=excluded.runtime_kind,
                      contract_json=excluded.contract_json,
                      confidence_tier=excluded.confidence_tier,
                      provenance_json=excluded.provenance_json,
                      source_hash=excluded.source_hash,
                      updated_at=excluded.updated_at
                    """,
                    (
                        version_id,
                        module_id,
                        "v0",
                        str(module.get("title") or module_id),
                        str(runtime.get("kind") or ""),
                        json.dumps(module),
                        module.get("confidence_tier"),
                        json.dumps({"evidence": evidence, "runtime": runtime}),
                        source_file_id,
                        contract_hash,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO modules(module_id, current_version_id, title, confidence_tier, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(module_id) DO UPDATE SET
                      current_version_id=excluded.current_version_id,
                      title=excluded.title,
                      confidence_tier=excluded.confidence_tier,
                      updated_at=excluded.updated_at
                    """,
                    (module_id, version_id, str(module.get("title") or module_id), module.get("confidence_tier"), now),
                )
                conn.execute("DELETE FROM module_inputs WHERE module_version_id=?", (version_id,))
                conn.execute("DELETE FROM module_outputs WHERE module_version_id=?", (version_id,))
                for field_name, table_name in (("inputs", "module_inputs"), ("outputs", "module_outputs")):
                    for item in module.get(field_name) or []:
                        if not isinstance(item, dict) or not item.get("name") or not item.get("artifact_type"):
                            continue
                        artifact_type = str(item["artifact_type"])
                        conn.execute(
                            """
                            INSERT INTO artifact_contracts(artifact_type, schema_json, validation_json, version, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(artifact_type) DO UPDATE SET updated_at=excluded.updated_at
                            """,
                            (
                                artifact_type,
                                json.dumps({"artifact_type": artifact_type}),
                                json.dumps({}),
                                "v0",
                                now,
                            ),
                        )
                        if table_name == "module_inputs":
                            conn.execute(
                                """
                                INSERT INTO module_inputs(module_version_id, name, artifact_type, required, constraints_json)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    version_id,
                                    str(item["name"]),
                                    artifact_type,
                                    1 if item.get("required", False) else 0,
                                    json.dumps(item),
                                ),
                            )
                        else:
                            conn.execute(
                                """
                                INSERT INTO module_outputs(module_version_id, name, artifact_type, optional, constraints_json)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    version_id,
                                    str(item["name"]),
                                    artifact_type,
                                    1 if item.get("optional", False) else 0,
                                    json.dumps(item),
                                ),
                            )
                if module.get("parameters"):
                    schema_payload = {
                        "schema": "morphic.module_params_schema/v0",
                        "module_id": module_id,
                        "parameters": module.get("parameters") or [],
                    }
                    schema_id = _stable_id("params", {"module_id": module_id, "hash": _sha256_json(schema_payload)})
                    conn.execute(
                        """
                        INSERT INTO parameter_schemas(schema_id, owner_type, owner_id, schema_json, source_hash, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(schema_id) DO UPDATE SET
                          schema_json=excluded.schema_json,
                          source_hash=excluded.source_hash,
                          updated_at=excluded.updated_at
                        """,
                        (schema_id, "module", module_id, json.dumps(schema_payload), _sha256_json(schema_payload), now),
                    )
                imported += 1
        return {"source_file_id": source_file_id, "source_hash": source_hash, "module_count": imported}

    def list_module_contracts(self, query: str = "", filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        needle = query.lower().strip()
        capability = str(filters.get("capability") or "").lower().strip()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT mv.contract_json
                FROM modules m
                JOIN module_versions mv ON mv.version_id=m.current_version_id
                ORDER BY m.module_id
                """
            ).fetchall()
        modules = [json.loads(row["contract_json"]) for row in rows]
        out: list[dict[str, Any]] = []
        for module in modules:
            haystack = " ".join(
                [
                    str(module.get("module_id") or ""),
                    str(module.get("title") or ""),
                    str(module.get("description") or ""),
                    " ".join(module.get("capabilities") or []),
                    json.dumps(module.get("runtime") or {}, sort_keys=True),
                    json.dumps(module.get("suite_recipe") or {}, sort_keys=True),
                ]
            ).lower()
            if needle and needle not in haystack:
                continue
            if capability and capability not in haystack:
                continue
            out.append(module)
        return out

    def get_module_contract(self, module_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT mv.contract_json
                FROM modules m
                JOIN module_versions mv ON mv.version_id=m.current_version_id
                WHERE m.module_id=?
                """,
                (module_id,),
            ).fetchone()
        return json.loads(row["contract_json"]) if row else None

    def rebuild_compatibility_edges(self) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  source_m.module_id AS source_module_id,
                  mo.name AS source_output,
                  target_m.module_id AS target_module_id,
                  mi.name AS target_input,
                  mo.artifact_type AS artifact_type
                FROM modules source_m
                JOIN module_outputs mo ON mo.module_version_id=source_m.current_version_id
                JOIN module_inputs mi ON mi.artifact_type=mo.artifact_type
                JOIN modules target_m ON target_m.current_version_id=mi.module_version_id
                WHERE source_m.module_id != target_m.module_id
                ORDER BY source_m.module_id, target_m.module_id, mo.name, mi.name
                """
            ).fetchall()
            conn.execute("DELETE FROM compatibility_edges")
            inserted = 0
            for row in rows:
                payload = {
                    "source_module_id": row["source_module_id"],
                    "source_output": row["source_output"],
                    "target_module_id": row["target_module_id"],
                    "target_input": row["target_input"],
                    "artifact_type": row["artifact_type"],
                }
                edge_id = _stable_id("compat", payload)
                conn.execute(
                    """
                    INSERT INTO compatibility_edges(
                      edge_id, source_module_id, source_output, target_module_id,
                      target_input, artifact_type, confidence_tier, evidence_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge_id,
                        row["source_module_id"],
                        row["source_output"],
                        row["target_module_id"],
                        row["target_input"],
                        row["artifact_type"],
                        "artifact_type_match",
                        json.dumps({"kind": "artifact_type_match", "artifact_type": row["artifact_type"]}),
                        now,
                    ),
                )
                inserted += 1
        return {"compatibility_edge_count": inserted, "updated_at": now}

    def list_compatibility_edges(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT edge_id, source_module_id, source_output, target_module_id,
                       target_input, artifact_type, confidence_tier, evidence_json, updated_at
                FROM compatibility_edges
                ORDER BY source_module_id, target_module_id, source_output, target_input
                """
            ).fetchall()
        return [
            {
                "edge_id": row["edge_id"],
                "source_module_id": row["source_module_id"],
                "source_output": row["source_output"],
                "target_module_id": row["target_module_id"],
                "target_input": row["target_input"],
                "artifact_type": row["artifact_type"],
                "confidence_tier": row["confidence_tier"],
                "evidence": json.loads(row["evidence_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def count_rows(self, table_name: str) -> int:
        allowed = {
            "source_files",
            "modules",
            "module_versions",
            "module_inputs",
            "module_outputs",
            "artifact_contracts",
            "parameter_schemas",
            "compatibility_edges",
            "subgraph_versions",
            "workflow_graphs",
            "workflow_graph_versions",
            "workflow_graph_nodes",
            "workflow_graph_edges",
            "workflow_graph_inputs",
            "workflow_graph_outputs",
            "workflow_graph_capabilities",
            "workflow_graph_modalities",
            "workflow_graph_execution_locations",
            "graph_projection_vertices",
            "graph_projection_edges",
            "graph_projection_manifests",
            "generated_bundles",
            "execution_review_approvals",
            "workbench_runs",
            "preflight_runs",
            "execution_runs",
            "verified_recipes",
            "workflow_validation_records",
        }
        if table_name not in allowed:
            raise ValueError(f"unsupported table: {table_name}")
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table_name}").fetchone()
        return int(row["n"])

    def upsert_projection_batch(
        self,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        projection_version: str,
    ) -> dict[str, Any]:
        return self.projection_repository.upsert_projection_batch(
            vertices,
            edges,
            projection_version=projection_version,
        )

    def rebuild_projection(
        self,
        *,
        projection_version: str,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.projection_repository.rebuild_projection(
            projection_version=projection_version,
            vertices=vertices,
            edges=edges,
            manifest=manifest,
        )

    def projection_status(self, projection_version: str) -> dict[str, Any]:
        return self.projection_repository.projection_status(projection_version)

    def record_subgraph(self, graph: dict[str, Any], *, version: str = "v0") -> dict[str, Any]:
        return self.graph_repository.upsert_graph(graph, version=version)

    def list_verified_recipes(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT verified_recipe_id, graph_id, graph_json, execution_manifest_json, canonical_graph_hash, lifecycle_state, created_at FROM verified_recipes ORDER BY created_at"
            ).fetchall()
        return [
            {
                "verified_recipe_id": row["verified_recipe_id"],
                "graph_id": row["graph_id"],
                "graph": json.loads(row["graph_json"]),
                "execution_manifest": json.loads(row["execution_manifest_json"]),
                "canonical_graph_hash": row["canonical_graph_hash"],
                "lifecycle_state": row["lifecycle_state"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_subgraphs(self) -> list[dict[str, Any]]:
        return self.graph_repository.list_subgraphs()

    def get_subgraph(self, subgraph_id: str) -> dict[str, Any] | None:
        return self.graph_repository.get_graph(subgraph_id)

    def search_graphs(self, *, query: str = "", filters: dict[str, Any] | None = None, limit: int = 20) -> dict[str, Any]:
        return self.graph_search_repository.search_graphs(query=query, filters=filters, limit=limit)

    def record_bundle(self, graph_id: str, bundle_path: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
        return self.bundle_repository.record_bundle(graph_id, bundle_path, manifest)

    def record_review_approval(self, approval: dict[str, Any]) -> dict[str, Any]:
        return self.review_approval_repository.record_review_approval(approval)

    def get_review_approval(self, token: str) -> dict[str, Any] | None:
        return self.review_approval_repository.get_review_approval(token)

    def create_workbench_run(
        self,
        graph_id: str,
        params: dict[str, Any] | None,
        *,
        execution_location: dict[str, Any] | None = None,
        request_context: dict[str, Any] | None = None,
        status: str = "created",
        current_step: str = "created",
    ) -> dict[str, Any]:
        context = request_context if isinstance(request_context, dict) else {}
        conversation_id = str(context.get("conversation_id") or context.get("thread_id") or "").strip()
        owner_user = str(
            context.get("storage_user")
            or context.get("user_slug")
            or context.get("user")
            or "anonymous"
        ).strip() or "anonymous"
        if conversation_id:
            self.conversation_repository.ensure_for_thread(
                conversation_id,
                owner_user=owner_user,
                session_id=str(context.get("session_slug") or context.get("session_id") or ""),
            )
        run = self.run_repository.create_run(
            graph_id,
            params,
            execution_location=execution_location,
            request_context=request_context,
            status=status,
            current_step=current_step,
        )
        if conversation_id:
            self.conversation_repository.link_run(
                conversation_id,
                str(run.get("run_id") or ""),
                owner_user=owner_user,
            )
        return run

    def get_workbench_run(self, run_id: str) -> dict[str, Any] | None:
        return self.run_repository.get_run(run_id)

    def list_workbench_runs(
        self,
        *,
        graph_id: str | None = None,
        limit: int = 25,
        owner_user: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.run_repository.list_runs(graph_id=graph_id, limit=limit, owner_user=owner_user)

    def update_workbench_run(
        self,
        run_id: str,
        updates: dict[str, Any],
        *,
        event: str,
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        updated = self.run_repository.update_run(
            run_id,
            updates,
            event=event,
            event_payload=event_payload,
        )
        if updated is not None:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE conversations SET updated_at=?
                    WHERE conversation_id IN (
                      SELECT conversation_id FROM conversation_run_links WHERE run_id=?
                    )
                    """,
                    (str(updated.get("updated_at") or _utc_now()), run_id),
                )
        return updated

    def _write_workbench_run(self, state: dict[str, Any]) -> None:
        self.run_repository.write_run(state)

    def get_bundle_by_path(self, bundle_path: str | Path) -> dict[str, Any] | None:
        return self.bundle_repository.get_bundle_by_path(bundle_path)

    def record_preflight(self, graph_id: str, params: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return self.preflight_repository.record_preflight(graph_id, params, result)

    def record_execution(self, graph_id: str, result: dict[str, Any], *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.execution_repository.record_execution(graph_id, result, params=params)

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        return self.execution_repository.get_execution(execution_id)

    def record_workflow_validation(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_validation_repository.record_validation(record)

    def get_workflow_validation(self, validation_id: str) -> dict[str, Any] | None:
        return self.workflow_validation_repository.get_validation(validation_id)

    def list_workflow_validations(
        self,
        *,
        graph_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.workflow_validation_repository.list_validations(graph_id=graph_id, filters=filters, limit=limit)

    def attach_workflow_validation_to_run(self, run_id: str, validation_id: str) -> dict[str, Any] | None:
        run = self.get_workbench_run(run_id)
        validation = self.get_workflow_validation(validation_id)
        if run is None or validation is None:
            return None
        if str(run.get("graph_id") or "") != str(validation.get("graph_id") or ""):
            raise ValueError(
                f"validation `{validation_id}` belongs to graph `{validation.get('graph_id')}`, "
                f"not run graph `{run.get('graph_id')}`"
            )
        validation_summary = {
            "validation_id": validation["validation_id"],
            "graph_id": validation["graph_id"],
            "validation_kind": validation.get("validation_kind"),
            "comparator_kind": validation.get("comparator_kind"),
            "fixture_id": validation.get("fixture_id"),
            "executor": validation.get("executor"),
            "status": validation.get("status"),
            "created_at": validation.get("created_at"),
            "manifest_hash": validation.get("manifest_hash"),
            "source_manifest_hash": validation.get("source_manifest_hash"),
            "canonical_graph_hash": validation.get("canonical_graph_hash"),
            "summary": validation.get("summary") or {},
        }
        validations = run.get("validations") if isinstance(run.get("validations"), list) else []
        validations = [item for item in validations if str(item.get("validation_id") if isinstance(item, dict) else "") != validation["validation_id"]]
        validations.insert(0, validation_summary)
        return self.update_workbench_run(
            str(run["run_id"]),
            {"validations": validations, "latest_validation": validation_summary},
            event="validation_attached",
            event_payload={
                "validation_id": validation["validation_id"],
                "validation_status": validation.get("status"),
                "validation_kind": validation.get("validation_kind"),
                "comparator_kind": validation.get("comparator_kind"),
                "fixture_id": validation.get("fixture_id"),
            },
        )

    def store_verified_recipe(self, graph: dict[str, Any], execution_manifest: dict[str, Any]) -> dict[str, Any]:
        if execution_manifest.get("status") != "verified" or execution_manifest.get("verified_recipe") is not True:
            raise ValueError("execution_manifest is not verified")
        graph_id = str(graph.get("graph_id") or execution_manifest.get("graph_id") or "")
        if not graph_id:
            raise ValueError("graph_id is required")
        canonical_hash = str(
            execution_manifest.get("canonical_graph_hash")
            or graph.get("canonical_graph_hash")
            or _sha256_json({"graph_id": graph_id, "nodes": graph.get("nodes") or [], "edges": graph.get("edges") or []})
        )
        verified_id = _stable_id("verified", {"graph_id": graph_id, "canonical_graph_hash": canonical_hash})
        verified_graph = dict(graph)
        verified_graph["lifecycle_state"] = "verified"
        verified_graph["canonical_graph_hash"] = canonical_hash
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO verified_recipes(
                  verified_recipe_id, graph_id, graph_json, execution_manifest_json,
                  canonical_graph_hash, lifecycle_state, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(verified_recipe_id) DO UPDATE SET
                  graph_json=excluded.graph_json,
                  execution_manifest_json=excluded.execution_manifest_json,
                  lifecycle_state=excluded.lifecycle_state
                """,
                (
                    verified_id,
                    graph_id,
                    json.dumps(verified_graph),
                    json.dumps(execution_manifest),
                    canonical_hash,
                    "verified",
                    now,
                ),
            )
        self.record_execution(graph_id, execution_manifest)
        self.record_subgraph(verified_graph, version="verified")
        return {
            "verified_recipe_id": verified_id,
            "graph_id": graph_id,
            "canonical_graph_hash": canonical_hash,
            "lifecycle_state": "verified",
        }
