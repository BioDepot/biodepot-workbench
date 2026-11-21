"""Repository implementations for Workbench graph persistence and search."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from morphic_agent.content.workspace import safe_workspace_slug


ConnectFactory = Callable[[], sqlite3.Connection]

CONVERSATION_SCHEMA = "morphic.conversation/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{_sha256_json(payload)[:16]}"


class ConversationRepository:
    """Owned, resumable conversation metadata around planner threads."""

    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def create(
        self,
        *,
        owner_user: str,
        title: str = "",
        origin_session_id: str = "",
        metadata: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        parent_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        owner = _required_owner(owner_user)
        identifier = str(conversation_id or f"thread-{uuid.uuid4().hex[:12]}").strip()
        if not identifier:
            raise ValueError("conversation_id is required")
        now = _utc_now()
        normalized_title = _conversation_title(title)
        session_id = safe_workspace_slug(origin_session_id, "")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO agent_threads(thread_id, created_at, updated_at) VALUES (?, ?, ?)",
                (identifier, now, now),
            )
            conn.execute(
                """
                INSERT INTO conversations(
                  conversation_id, thread_id, owner_user, title, status,
                  origin_session_id, last_session_id, parent_conversation_id,
                  metadata_json, created_at, updated_at, archived_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    identifier,
                    identifier,
                    owner,
                    normalized_title,
                    session_id or None,
                    session_id or None,
                    str(parent_conversation_id or "").strip() or None,
                    json.dumps(metadata or {}),
                    now,
                    now,
                ),
            )
        conversation = self.get(identifier, owner_user=owner)
        if conversation is None:
            raise RuntimeError("conversation was not created")
        return conversation

    def ensure_for_thread(
        self,
        thread_id: str | None,
        *,
        owner_user: str,
        session_id: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        owner = _required_owner(owner_user)
        identifier = str(thread_id or "").strip()
        if not identifier:
            return self.create(owner_user=owner, title=title, origin_session_id=session_id)
        existing = self.get(identifier, owner_user=owner)
        if existing is None:
            with self._connect() as conn:
                thread_exists = conn.execute(
                    "SELECT 1 FROM agent_threads WHERE thread_id=?",
                    (identifier,),
                ).fetchone()
            if thread_exists:
                raise PermissionError("conversation is not available to the current user")
            return self.create(
                owner_user=owner,
                title=title,
                origin_session_id=session_id,
                conversation_id=identifier,
            )
        if existing["status"] != "active":
            raise ValueError("conversation is archived; restore or fork it before adding turns")
        updates: dict[str, Any] = {"last_session_id": safe_workspace_slug(session_id, "") or None}
        if existing["title"] == "New conversation" and str(title or "").strip():
            updates["title"] = _conversation_title(title)
        self._update_fields(identifier, owner, updates)
        return self.get(identifier, owner_user=owner) or existing

    def get(self, conversation_id: str, *, owner_user: str) -> dict[str, Any] | None:
        identifier = str(conversation_id or "").strip()
        if not identifier:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT c.*,
                  (SELECT COUNT(*) FROM agent_turns t WHERE t.thread_id=c.thread_id) AS turn_count,
                  (SELECT COUNT(*) FROM conversation_run_links l WHERE l.conversation_id=c.conversation_id) AS run_count
                FROM conversations c
                WHERE c.conversation_id=?
                """,
                (identifier,),
            ).fetchone()
        if row is None:
            return None
        if str(row["owner_user"]) != _required_owner(owner_user):
            raise PermissionError("conversation is not available to the current user")
        return _conversation_record(row)

    def list(
        self,
        *,
        owner_user: str,
        status: str = "active",
        query: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        owner = _required_owner(owner_user)
        normalized_status = str(status or "active").strip().lower()
        if normalized_status not in {"active", "archived", "all"}:
            raise ValueError("conversation status must be active, archived, or all")
        clauses = ["c.owner_user=?"]
        args: list[Any] = [owner]
        if normalized_status != "all":
            clauses.append("c.status=?")
            args.append(normalized_status)
        needle = str(query or "").strip().lower()
        if needle:
            clauses.append("LOWER(c.title) LIKE ?")
            args.append(f"%{needle}%")
        args.append(max(1, min(int(limit or 50), 200)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,
                  (SELECT COUNT(*) FROM agent_turns t WHERE t.thread_id=c.thread_id) AS turn_count,
                  (SELECT COUNT(*) FROM conversation_run_links l WHERE l.conversation_id=c.conversation_id) AS run_count
                FROM conversations c
                WHERE {' AND '.join(clauses)}
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                tuple(args),
            ).fetchall()
        return [_conversation_record(row) for row in rows]

    def update(
        self,
        conversation_id: str,
        *,
        owner_user: str,
        title: str | None = None,
        status: str | None = None,
        session_id: str = "",
    ) -> dict[str, Any] | None:
        current = self.get(conversation_id, owner_user=owner_user)
        if current is None:
            return None
        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = _conversation_title(title)
        if status is not None:
            normalized_status = str(status).strip().lower()
            if normalized_status not in {"active", "archived"}:
                raise ValueError("conversation status must be active or archived")
            updates["status"] = normalized_status
            updates["archived_at"] = _utc_now() if normalized_status == "archived" else None
        if session_id:
            updates["last_session_id"] = safe_workspace_slug(session_id, "")
        if updates:
            self._update_fields(conversation_id, _required_owner(owner_user), updates)
        return self.get(conversation_id, owner_user=owner_user)

    def fork(
        self,
        conversation_id: str,
        *,
        owner_user: str,
        session_id: str = "",
        title: str = "",
        include_history: bool = True,
    ) -> dict[str, Any] | None:
        source = self.get(conversation_id, owner_user=owner_user)
        if source is None:
            return None
        forked = self.create(
            owner_user=owner_user,
            title=title or f"Copy of {source['title']}",
            origin_session_id=session_id,
            metadata={"forked_from": source["conversation_id"]},
            parent_conversation_id=source["conversation_id"],
        )
        if include_history:
            now = _utc_now()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_turns(thread_id, role, goal, payload_json, created_at)
                    SELECT ?, role, goal, payload_json, created_at
                    FROM agent_turns WHERE thread_id=? ORDER BY id
                    """,
                    (forked["thread_id"], source["thread_id"]),
                )
                state = conn.execute(
                    "SELECT state_json FROM planner_states WHERE thread_id=?",
                    (source["thread_id"],),
                ).fetchone()
                if state is not None:
                    state_payload = json.loads(state["state_json"])
                    if isinstance(state_payload, dict):
                        state_payload["thread_id"] = forked["thread_id"]
                    conn.execute(
                        "INSERT OR REPLACE INTO planner_states(thread_id, state_json, updated_at) VALUES (?, ?, ?)",
                        (forked["thread_id"], json.dumps(state_payload), now),
                    )
                conn.execute(
                    "UPDATE agent_threads SET updated_at=? WHERE thread_id=?",
                    (now, forked["thread_id"]),
                )
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE conversation_id=?",
                    (now, forked["conversation_id"]),
                )
        return self.get(forked["conversation_id"], owner_user=owner_user)

    def link_run(
        self,
        conversation_id: str,
        run_id: str,
        *,
        owner_user: str,
        relationship: str = "workflow_run",
    ) -> None:
        identifier = str(conversation_id or "").strip()
        run_key = str(run_id or "").strip()
        if not identifier or not run_key:
            return
        owner = _required_owner(owner_user)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT owner_user, status FROM conversations WHERE conversation_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise ValueError("conversation was not found")
            if str(row["owner_user"]) != owner:
                raise PermissionError("conversation is not available to the current user")
            if str(row["status"]) != "active":
                raise ValueError("conversation is archived; restore or fork it before linking runs")
            conn.execute(
                """
                INSERT INTO conversation_run_links(conversation_id, run_id, relationship, linked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id, run_id) DO UPDATE SET relationship=excluded.relationship
                """,
                (identifier, run_key, str(relationship or "workflow_run"), _utc_now()),
            )
            conn.execute(
                "UPDATE conversations SET updated_at=? WHERE conversation_id=?",
                (_utc_now(), identifier),
            )

    def runs(self, conversation_id: str, *, owner_user: str, limit: int = 25) -> list[dict[str, Any]]:
        if self.get(conversation_id, owner_user=owner_user) is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.state_json
                FROM conversation_run_links l
                JOIN workbench_runs r ON r.run_id=l.run_id
                WHERE l.conversation_id=?
                ORDER BY r.updated_at DESC LIMIT ?
                """,
                (conversation_id, max(1, min(int(limit or 25), 100))),
            ).fetchall()
        return [json.loads(row["state_json"]) for row in rows]

    def _update_fields(self, conversation_id: str, owner_user: str, updates: dict[str, Any]) -> None:
        allowed = {"title", "status", "last_session_id", "archived_at"}
        values = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return
        values["updated_at"] = _utc_now()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE conversations SET {assignments} WHERE conversation_id=? AND owner_user=?",
                (*values.values(), conversation_id, owner_user),
            )


def _required_owner(value: Any) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise ValueError("owner_user is required")
    return safe_workspace_slug(owner, "anonymous")


def _conversation_title(value: Any) -> str:
    title = " ".join(str(value or "").split()).strip()
    return title[:160] or "New conversation"


def _conversation_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema": CONVERSATION_SCHEMA,
        "conversation_id": str(row["conversation_id"]),
        "thread_id": str(row["thread_id"]),
        "owner_user": str(row["owner_user"]),
        "title": str(row["title"]),
        "status": str(row["status"]),
        "origin_session_id": str(row["origin_session_id"] or ""),
        "last_session_id": str(row["last_session_id"] or ""),
        "parent_conversation_id": row["parent_conversation_id"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "turn_count": int(row["turn_count"] or 0),
        "run_count": int(row["run_count"] or 0),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "archived_at": row["archived_at"],
    }


def _run_request_owner(run: dict[str, Any]) -> str:
    context = run.get("request_context") if isinstance(run.get("request_context"), dict) else {}
    return safe_workspace_slug(
        context.get("storage_user")
        or context.get("user_slug")
        or context.get("user")
        or "anonymous",
        "anonymous",
    )


class GraphRepository:
    """Canonical workflow graph storage with normalized search facets."""

    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def upsert_graph(self, graph: dict[str, Any], *, version: str = "v0") -> dict[str, Any]:
        graph_id = str(graph.get("graph_id") or "").strip()
        if not graph_id:
            raise ValueError("graph_id is required")
        canonical_hash = _canonical_graph_hash(graph)
        graph_payload = copy.deepcopy(graph)
        graph_payload["canonical_graph_hash"] = canonical_hash
        version_id = _stable_id("graph", {"graph_id": graph_id, "canonical_graph_hash": canonical_hash})
        now = _utc_now()
        title = str(graph_payload.get("title") or graph_id)
        lifecycle_state = str(graph_payload.get("lifecycle_state") or "candidate")
        materialization_status = str(graph_payload.get("materialization_status") or "")
        confidence_tier = graph_payload.get("confidence_tier")
        suite = _graph_suite(graph_payload)
        recipe_family = _first_text(graph_payload.get("recipe_family"), graph_payload.get("suite_recipe", {}).get("recipe_family") if isinstance(graph_payload.get("suite_recipe"), dict) else None)
        assay_profile = _first_text(graph_payload.get("assay_profile"), graph_payload.get("suite_recipe", {}).get("assay_profile") if isinstance(graph_payload.get("suite_recipe"), dict) else None)
        runnable = _graph_runnable(graph_payload)
        verified = lifecycle_state == "verified" or materialization_status == "verified_recipe"
        runtime = graph_payload.get("runtime") if isinstance(graph_payload.get("runtime"), dict) else {}
        execution = graph_payload.get("execution") if isinstance(graph_payload.get("execution"), dict) else {}
        search_text = _graph_search_text(graph_payload)
        inputs = _path_contracts(graph_payload.get("inputs") or graph_payload.get("required_human_inputs") or [])
        outputs = _path_contracts(graph_payload.get("outputs") or [])
        capabilities = _string_values(graph_payload.get("capabilities") or [])
        modalities = _string_values(graph_payload.get("modalities") or [])
        execution_locations = _execution_locations(graph_payload)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_graph_versions(
                  version_id, graph_id, version, graph_json, canonical_graph_hash, title,
                  suite, recipe_family, assay_profile, lifecycle_state, materialization_status,
                  confidence_tier, runnable, verified, runtime_json, execution_json,
                  search_text, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(graph_id, canonical_graph_hash) DO UPDATE SET
                  graph_json=excluded.graph_json,
                  title=excluded.title,
                  suite=excluded.suite,
                  recipe_family=excluded.recipe_family,
                  assay_profile=excluded.assay_profile,
                  lifecycle_state=excluded.lifecycle_state,
                  materialization_status=excluded.materialization_status,
                  confidence_tier=excluded.confidence_tier,
                  runnable=excluded.runnable,
                  verified=excluded.verified,
                  runtime_json=excluded.runtime_json,
                  execution_json=excluded.execution_json,
                  search_text=excluded.search_text,
                  updated_at=excluded.updated_at
                """,
                (
                    version_id,
                    graph_id,
                    version,
                    json.dumps(graph_payload),
                    canonical_hash,
                    title,
                    suite,
                    recipe_family,
                    assay_profile,
                    lifecycle_state,
                    materialization_status,
                    confidence_tier,
                    int(runnable),
                    int(verified),
                    json.dumps(runtime),
                    json.dumps(execution),
                    search_text,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO workflow_graphs(
                  graph_id, current_version_id, title, suite, recipe_family, assay_profile,
                  lifecycle_state, materialization_status, confidence_tier, runnable, verified, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(graph_id) DO UPDATE SET
                  current_version_id=excluded.current_version_id,
                  title=excluded.title,
                  suite=excluded.suite,
                  recipe_family=excluded.recipe_family,
                  assay_profile=excluded.assay_profile,
                  lifecycle_state=excluded.lifecycle_state,
                  materialization_status=excluded.materialization_status,
                  confidence_tier=excluded.confidence_tier,
                  runnable=excluded.runnable,
                  verified=excluded.verified,
                  updated_at=excluded.updated_at
                """,
                (
                    graph_id,
                    version_id,
                    title,
                    suite,
                    recipe_family,
                    assay_profile,
                    lifecycle_state,
                    materialization_status,
                    confidence_tier,
                    int(runnable),
                    int(verified),
                    now,
                ),
            )
            self._replace_normalized_rows(conn, version_id, graph_payload, inputs, outputs, capabilities, modalities, execution_locations)
            self._upsert_subgraph_compat(conn, graph_payload, version_id=version_id, version=version, canonical_hash=canonical_hash, now=now)
        return {"version_id": version_id, "canonical_graph_hash": canonical_hash, "graph_id": graph_id}

    def list_graphs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT v.*
                FROM workflow_graphs g
                JOIN workflow_graph_versions v ON v.version_id = g.current_version_id
                ORDER BY g.updated_at, g.graph_id
                """
            ).fetchall()
            return [self._record_from_row(conn, row) for row in rows]

    def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT v.*
                FROM workflow_graphs g
                JOIN workflow_graph_versions v ON v.version_id = g.current_version_id
                WHERE g.graph_id=?
                """,
                (str(graph_id or ""),),
            ).fetchone()
            if not row:
                return None
            record = self._record_from_row(conn, row)
        graph = dict(record.get("graph") or {})
        for key in (
            "canonical_graph_hash",
            "validations",
            "latest_validation",
            "validation_statuses",
            "validation_kinds",
            "validation_comparator_kinds",
            "validation_executors",
            "validation_fixtures",
        ):
            if key in record:
                graph[key] = record[key]
        return graph

    def list_subgraphs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT version_id, subgraph_id, version, graph_json, input_signature_json,
                       output_signature_json, capabilities_json, confidence_tier,
                       lifecycle_state, canonical_graph_hash, updated_at
                FROM subgraph_versions
                ORDER BY updated_at, version_id
                """
            ).fetchall()
        by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            by_id[row["subgraph_id"]] = {
                "version_id": row["version_id"],
                "subgraph_id": row["subgraph_id"],
                "version": row["version"],
                "graph": json.loads(row["graph_json"]),
                "inputs": json.loads(row["input_signature_json"]),
                "outputs": json.loads(row["output_signature_json"]),
                "capabilities": json.loads(row["capabilities_json"]),
                "confidence_tier": row["confidence_tier"],
                "lifecycle_state": row["lifecycle_state"],
                "canonical_graph_hash": row["canonical_graph_hash"],
                "updated_at": row["updated_at"],
            }
        return list(by_id.values())

    def _record_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        version_id = row["version_id"]
        validations = _validation_rows(conn, str(row["graph_id"]))
        return {
            "version_id": version_id,
            "graph_id": row["graph_id"],
            "version": row["version"],
            "title": row["title"],
            "suite": row["suite"],
            "recipe_family": row["recipe_family"],
            "assay_profile": row["assay_profile"],
            "lifecycle_state": row["lifecycle_state"],
            "materialization_status": row["materialization_status"],
            "confidence_tier": row["confidence_tier"],
            "canonical_graph_hash": row["canonical_graph_hash"],
            "runnable": bool(row["runnable"]),
            "verified": bool(row["verified"]),
            "search_text": row["search_text"],
            "graph": json.loads(row["graph_json"]),
            "inputs": _facet_rows(conn, "workflow_graph_inputs", version_id, "artifact_type"),
            "outputs": _facet_rows(conn, "workflow_graph_outputs", version_id, "artifact_type"),
            "capabilities": _facet_rows(conn, "workflow_graph_capabilities", version_id, "capability"),
            "modalities": _facet_rows(conn, "workflow_graph_modalities", version_id, "modality"),
            "execution_locations": _facet_rows(conn, "workflow_graph_execution_locations", version_id, "execution_location"),
            "validations": validations,
            "latest_validation": validations[0] if validations else None,
            "validation_statuses": _unique_facet_values(validations, "status"),
            "validation_kinds": _unique_facet_values(validations, "validation_kind"),
            "validation_comparator_kinds": _unique_facet_values(validations, "comparator_kind"),
            "validation_executors": _unique_facet_values(validations, "executor"),
            "validation_fixtures": _unique_facet_values(validations, "fixture_id"),
        }

    def _replace_normalized_rows(
        self,
        conn: sqlite3.Connection,
        version_id: str,
        graph: dict[str, Any],
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        capabilities: list[str],
        modalities: list[str],
        execution_locations: list[str],
    ) -> None:
        for table in (
            "workflow_graph_nodes",
            "workflow_graph_edges",
            "workflow_graph_inputs",
            "workflow_graph_outputs",
            "workflow_graph_capabilities",
            "workflow_graph_modalities",
            "workflow_graph_execution_locations",
        ):
            conn.execute(f"DELETE FROM {table} WHERE version_id=?", (version_id,))
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or node.get("module_id") or _stable_id("node", node))
            conn.execute(
                """
                INSERT INTO workflow_graph_nodes(version_id, node_id, module_id, label, kind, node_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (version_id, node_id, node.get("module_id"), node.get("label"), node.get("kind"), json.dumps(node)),
            )
        for index, edge in enumerate(graph.get("edges") or []):
            if not isinstance(edge, dict):
                continue
            conn.execute(
                """
                INSERT INTO workflow_graph_edges(version_id, edge_index, source, target, edge_type, artifact_type, edge_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    index,
                    edge.get("source"),
                    edge.get("target"),
                    edge.get("edge_type") or edge.get("label"),
                    edge.get("artifact_type"),
                    json.dumps(edge),
                ),
            )
        for item in inputs:
            conn.execute(
                """
                INSERT INTO workflow_graph_inputs(version_id, name, artifact_type, required, input_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (version_id, item["name"], item["artifact_type"], int(bool(item.get("required", True))), json.dumps(item)),
            )
        for item in outputs:
            conn.execute(
                """
                INSERT INTO workflow_graph_outputs(version_id, name, artifact_type, output_json)
                VALUES (?, ?, ?, ?)
                """,
                (version_id, item["name"], item["artifact_type"], json.dumps(item)),
            )
        for capability in capabilities:
            conn.execute("INSERT INTO workflow_graph_capabilities(version_id, capability) VALUES (?, ?)", (version_id, capability))
        for modality in modalities:
            conn.execute("INSERT INTO workflow_graph_modalities(version_id, modality) VALUES (?, ?)", (version_id, modality))
        for location in execution_locations:
            conn.execute(
                "INSERT INTO workflow_graph_execution_locations(version_id, execution_location) VALUES (?, ?)",
                (version_id, location),
            )

    def _upsert_subgraph_compat(
        self,
        conn: sqlite3.Connection,
        graph: dict[str, Any],
        *,
        version_id: str,
        version: str,
        canonical_hash: str,
        now: str,
    ) -> None:
        inputs = graph.get("inputs") or graph.get("required_human_inputs") or []
        outputs = graph.get("outputs") or []
        capabilities = graph.get("capabilities") or []
        conn.execute(
            """
            INSERT INTO subgraph_versions(
              version_id, subgraph_id, version, graph_json, input_signature_json,
              output_signature_json, capabilities_json, confidence_tier,
              lifecycle_state, canonical_graph_hash, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(version_id) DO UPDATE SET
              graph_json=excluded.graph_json,
              lifecycle_state=excluded.lifecycle_state,
              updated_at=excluded.updated_at
            """,
            (
                version_id,
                graph["graph_id"],
                version,
                json.dumps(graph),
                json.dumps(inputs),
                json.dumps(outputs),
                json.dumps(capabilities),
                graph.get("confidence_tier"),
                str(graph.get("lifecycle_state") or "candidate"),
                canonical_hash,
                now,
            ),
        )


class GraphSearchRepository:
    """Relational graph search over canonical graph tables."""

    def __init__(self, graphs: GraphRepository) -> None:
        self.graphs = graphs

    def search_graphs(
        self,
        *,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        filters = filters or {}
        limit = max(1, min(int(limit or 20), 100))
        tokens = _tokens(query)
        results: list[dict[str, Any]] = []
        for record in self.graphs.list_graphs():
            reasons: list[str] = []
            if not _filters_match(record, filters, reasons):
                continue
            text = " ".join(
                [
                    str(record.get("graph_id") or ""),
                    str(record.get("title") or ""),
                    str(record.get("search_text") or ""),
                    " ".join(record.get("inputs") or []),
                    " ".join(record.get("outputs") or []),
                    " ".join(record.get("capabilities") or []),
                    " ".join(record.get("modalities") or []),
                ]
            ).lower()
            token_matches = [token for token in tokens if token in text]
            if tokens and not token_matches:
                continue
            for token in token_matches:
                if token in str(record.get("graph_id") or "").lower():
                    reasons.append(f"query token `{token}` matched graph_id")
                elif token in str(record.get("title") or "").lower():
                    reasons.append(f"query token `{token}` matched title")
                else:
                    reasons.append(f"query token `{token}` matched graph search text")
            score = _score_record(record, tokens, token_matches, reasons)
            results.append(
                {
                    "graph_id": record["graph_id"],
                    "title": record["title"],
                    "score": score,
                    "match_reasons": sorted(set(reasons)),
                    "suite": record.get("suite"),
                    "recipe_family": record.get("recipe_family"),
                    "assay_profile": record.get("assay_profile"),
                    "modalities": record.get("modalities") or [],
                    "input_artifact_types": record.get("inputs") or [],
                    "output_artifact_types": record.get("outputs") or [],
                    "capabilities": record.get("capabilities") or [],
                    "lifecycle_state": record.get("lifecycle_state"),
                    "materialization_status": record.get("materialization_status"),
                    "runnable": bool(record.get("runnable")),
                    "verified": bool(record.get("verified")),
                    "validated": "passed" in {str(item).lower() for item in record.get("validation_statuses") or []},
                    "latest_validation": record.get("latest_validation"),
                    "validation_statuses": record.get("validation_statuses") or [],
                    "validation_kinds": record.get("validation_kinds") or [],
                    "validation_comparator_kinds": record.get("validation_comparator_kinds") or [],
                    "validation_executors": record.get("validation_executors") or [],
                    "validation_fixtures": record.get("validation_fixtures") or [],
                    "canonical_graph_hash": record.get("canonical_graph_hash"),
                    "workflow_graph": record.get("graph"),
                }
            )
        results.sort(key=lambda item: (-item["score"], item["graph_id"]))
        return {
            "schema": "morphic.graph_search_results/v0",
            "status": "ok",
            "query": query,
            "filters": filters,
            "result_count": len(results[:limit]),
            "total_matches": len(results),
            "results": results[:limit],
        }


class ProjectionRepository:
    """Projection adapter backed by local SQLite projection tables."""

    adapter_name = "sqlite"

    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def rebuild_projection(
        self,
        *,
        projection_version: str,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        projection_version = str(projection_version or "morphic-agent-v0")
        started_at = _utc_now()
        with self._connect() as conn:
            conn.execute("DELETE FROM graph_projection_vertices WHERE projection_version=?", (projection_version,))
            conn.execute("DELETE FROM graph_projection_edges WHERE projection_version=?", (projection_version,))
            self._upsert_projection_batch(conn, vertices, edges, projection_version=projection_version)
            completed_at = _utc_now()
            payload = {
                "schema": "morphic.graph_projection_manifest/v0",
                "status": "rebuilt",
                "projection_version": projection_version,
                "canonical_store": "postgres",
                "graph_index": "arcadedb",
                "projection_adapter": self.adapter_name,
                "adapter": self.adapter_name,
                "projected_vertex_count": len(vertices),
                "projected_edge_count": len(edges),
                "started_at": started_at,
                "completed_at": completed_at,
                **(manifest or {}),
            }
            conn.execute(
                """
                INSERT INTO graph_projection_manifests(
                  projection_version, status, adapter, vertex_count, edge_count,
                  manifest_json, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(projection_version) DO UPDATE SET
                  status=excluded.status,
                  adapter=excluded.adapter,
                  vertex_count=excluded.vertex_count,
                  edge_count=excluded.edge_count,
                  manifest_json=excluded.manifest_json,
                  started_at=excluded.started_at,
                  completed_at=excluded.completed_at
                """,
                (
                    projection_version,
                    str(payload["status"]),
                    self.adapter_name,
                    len(vertices),
                    len(edges),
                    json.dumps(payload),
                    started_at,
                    completed_at,
                ),
            )
        return payload

    def upsert_projection_batch(
        self,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        projection_version: str,
    ) -> dict[str, Any]:
        projection_version = str(projection_version or "morphic-agent-v0")
        with self._connect() as conn:
            self._upsert_projection_batch(conn, vertices, edges, projection_version=projection_version)
        return {"projection_version": projection_version, "vertex_count": len(vertices), "edge_count": len(edges)}

    def projection_status(self, projection_version: str) -> dict[str, Any]:
        projection_version = str(projection_version or "morphic-agent-v0")
        with self._connect() as conn:
            vertex_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM graph_projection_vertices WHERE projection_version=?",
                    (projection_version,),
                ).fetchone()["n"]
            )
            edge_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM graph_projection_edges WHERE projection_version=?",
                    (projection_version,),
                ).fetchone()["n"]
            )
            row = conn.execute(
                """
                SELECT status, adapter, vertex_count, edge_count, manifest_json, started_at, completed_at
                FROM graph_projection_manifests
                WHERE projection_version=?
                """,
                (projection_version,),
            ).fetchone()
        if not row:
            return {
                "schema": "morphic.graph_projection_status/v0",
                "status": "missing",
                "projection_version": projection_version,
                "projection_adapter": self.adapter_name,
                "projected_vertex_count": vertex_count,
                "projected_edge_count": edge_count,
                "manifest": None,
            }
        manifest = json.loads(row["manifest_json"])
        return {
            "schema": "morphic.graph_projection_status/v0",
            "status": row["status"],
            "projection_version": projection_version,
            "projection_adapter": row["adapter"],
            "projected_vertex_count": vertex_count,
            "projected_edge_count": edge_count,
            "manifest_vertex_count": int(row["vertex_count"]),
            "manifest_edge_count": int(row["edge_count"]),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "manifest": manifest,
        }

    @staticmethod
    def _upsert_projection_batch(
        conn: sqlite3.Connection,
        vertices: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        projection_version: str,
    ) -> None:
        for vertex in vertices:
            props = vertex.get("properties") if isinstance(vertex.get("properties"), dict) else {}
            conn.execute(
                """
                INSERT INTO graph_projection_vertices(vertex_id, projection_version, label, kind, properties_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(vertex_id, projection_version) DO UPDATE SET
                  label=excluded.label,
                  kind=excluded.kind,
                  properties_json=excluded.properties_json
                """,
                (
                    str(vertex.get("id") or vertex.get("vertex_id")),
                    projection_version,
                    str(vertex.get("label") or vertex.get("id") or ""),
                    str(vertex.get("kind") or "Vertex"),
                    json.dumps(props),
                ),
            )
        for edge in edges:
            props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
            conn.execute(
                """
                INSERT INTO graph_projection_edges(edge_id, projection_version, source, target, label, artifact_type, properties_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_id, projection_version) DO UPDATE SET
                  source=excluded.source,
                  target=excluded.target,
                  label=excluded.label,
                  artifact_type=excluded.artifact_type,
                  properties_json=excluded.properties_json
                """,
                (
                    str(edge.get("id") or edge.get("edge_id")),
                    projection_version,
                    str(edge.get("source") or ""),
                    str(edge.get("target") or ""),
                    str(edge.get("label") or edge.get("edge_type") or "EDGE"),
                    edge.get("artifact_type"),
                    json.dumps(props),
                ),
            )


class BundleRepository:
    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def record_bundle(self, graph_id: str, bundle_path: Any, manifest: dict[str, Any]) -> dict[str, Any]:
        from pathlib import Path

        path = Path(bundle_path)
        payload = {"graph_id": graph_id, "bundle_path": str(path), "manifest": manifest}
        bundle_id = _stable_id("bundle", payload)
        bundle_hash = _sha256_json(payload)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generated_bundles(bundle_id, graph_id, bundle_path, bundle_hash, manifest_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(bundle_id) DO UPDATE SET manifest_json=excluded.manifest_json
                """,
                (bundle_id, graph_id, str(path), bundle_hash, json.dumps(manifest), now),
            )
        return {"bundle_id": bundle_id, "bundle_hash": bundle_hash}

    def get_bundle_by_path(self, bundle_path: Any) -> dict[str, Any] | None:
        from pathlib import Path

        target = Path(bundle_path).expanduser()
        try:
            target_resolved = target.resolve()
        except OSError:
            target_resolved = target.absolute()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT bundle_id, graph_id, bundle_path, bundle_hash, manifest_json, created_at
                FROM generated_bundles
                ORDER BY created_at DESC
                """
            ).fetchall()
        for row in rows:
            recorded = Path(row["bundle_path"]).expanduser()
            try:
                recorded_resolved = recorded.resolve()
            except OSError:
                recorded_resolved = recorded.absolute()
            if recorded_resolved != target_resolved:
                continue
            return {
                "bundle_id": row["bundle_id"],
                "graph_id": row["graph_id"],
                "bundle_path": row["bundle_path"],
                "bundle_hash": row["bundle_hash"],
                "manifest": json.loads(row["manifest_json"]),
                "created_at": row["created_at"],
            }
        return None


class WorkflowValidationRepository:
    """Store validation evidence attached to workflow graphs."""

    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def record_validation(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = _normalize_validation_record(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_validation_records(
                  validation_id, graph_id, canonical_graph_hash, source_manifest_hash,
                  validation_kind, comparator_kind, executor, profile, fixture_id,
                  status, manifest_hash, summary_json, manifest_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(validation_id) DO UPDATE SET
                  graph_id=excluded.graph_id,
                  canonical_graph_hash=excluded.canonical_graph_hash,
                  source_manifest_hash=excluded.source_manifest_hash,
                  validation_kind=excluded.validation_kind,
                  comparator_kind=excluded.comparator_kind,
                  executor=excluded.executor,
                  profile=excluded.profile,
                  fixture_id=excluded.fixture_id,
                  status=excluded.status,
                  manifest_hash=excluded.manifest_hash,
                  summary_json=excluded.summary_json,
                  manifest_json=excluded.manifest_json,
                  updated_at=excluded.updated_at
                """,
                (
                    payload["validation_id"],
                    payload["graph_id"],
                    payload.get("canonical_graph_hash"),
                    payload.get("source_manifest_hash"),
                    payload["validation_kind"],
                    payload["comparator_kind"],
                    payload.get("executor"),
                    payload.get("profile"),
                    payload.get("fixture_id"),
                    payload["status"],
                    payload["manifest_hash"],
                    json.dumps(payload["summary"]),
                    json.dumps(payload["manifest"]),
                    payload["created_at"],
                    payload["updated_at"],
                ),
            )
        return payload

    def list_validations(
        self,
        *,
        graph_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        filters = filters or {}
        limit = max(1, min(int(limit or 100), 500))
        clauses: list[str] = []
        args: list[Any] = []
        if graph_id:
            clauses.append("graph_id=?")
            args.append(str(graph_id))
        for column, filter_key in (
            ("status", "status"),
            ("validation_kind", "validation_kind"),
            ("comparator_kind", "comparator_kind"),
            ("executor", "executor"),
            ("profile", "profile"),
            ("fixture_id", "fixture_id"),
            ("source_manifest_hash", "source_manifest_hash"),
        ):
            values = _filter_values(filters.get(filter_key))
            if not values:
                continue
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"lower({column}) IN ({placeholders})")
            args.extend(sorted(values))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT *
            FROM workflow_validation_records
            {where}
            ORDER BY created_at DESC, validation_id
            LIMIT ?
        """
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        return [_validation_record_from_row(row) for row in rows]

    def get_validation(self, validation_id: str) -> dict[str, Any] | None:
        validation_id = str(validation_id or "").strip()
        if not validation_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_validation_records WHERE validation_id=?",
                (validation_id,),
            ).fetchone()
        return _validation_record_from_row(row) if row else None


class ReviewApprovalRepository:
    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def record_review_approval(self, approval: dict[str, Any]) -> dict[str, Any]:
        token = str(approval.get("token") or "").strip()
        if not token:
            raise ValueError("review approval token is required")
        now = _utc_now()
        payload = {**approval, "created_at": approval.get("created_at") or now}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO execution_review_approvals(token, approval_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET approval_json=excluded.approval_json
                """,
                (token, json.dumps(payload), now),
            )
        return {"token": token}

    def get_review_approval(self, token: str) -> dict[str, Any] | None:
        token = str(token or "").strip()
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT approval_json FROM execution_review_approvals WHERE token=?",
                (token,),
            ).fetchone()
        return json.loads(row["approval_json"]) if row else None


class RunRepository:
    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def create_run(
        self,
        graph_id: str,
        params: dict[str, Any] | None,
        *,
        execution_location: dict[str, Any] | None = None,
        request_context: dict[str, Any] | None = None,
        status: str = "created",
        current_step: str = "created",
    ) -> dict[str, Any]:
        import uuid

        graph_id = str(graph_id or "").strip()
        if not graph_id:
            raise ValueError("graph_id is required")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        params_payload = dict(params or {})
        params_hash = f"sha256:{_sha256_json(params_payload)}"
        state = {
            "schema": "morphic.workbench_run/v0",
            "run_id": run_id,
            "graph_id": graph_id,
            "status": str(status or "created"),
            "current_step": str(current_step or "created"),
            "params": params_payload,
            "params_hash": params_hash,
            "execution_location": execution_location or None,
            "request_context": dict(request_context or {}),
            "review": None,
            "bundle": None,
            "preflight": None,
            "diagnostic": None,
            "execution": None,
            "artifact_manifest": None,
            "events": [
                {
                    "event": "run_created",
                    "status": str(status or "created"),
                    "current_step": str(current_step or "created"),
                    "created_at": now,
                }
            ],
            "created_at": now,
            "updated_at": now,
        }
        self.write_run(state)
        return state

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run_id = str(run_id or "").strip()
        if not run_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT state_json FROM workbench_runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row["state_json"]) if row else None

    def list_runs(
        self,
        *,
        graph_id: str | None = None,
        limit: int = 25,
        owner_user: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 25), 100))
        query = "SELECT state_json FROM workbench_runs"
        args: list[Any] = []
        if graph_id:
            query += " WHERE graph_id=?"
            args.append(str(graph_id))
        query += " ORDER BY updated_at DESC"
        if owner_user is None:
            query += " LIMIT ?"
            args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(args)).fetchall()
        runs = [json.loads(row["state_json"]) for row in rows]
        if owner_user is not None:
            requested_owner = safe_workspace_slug(owner_user, "anonymous")
            runs = [run for run in runs if _run_request_owner(run) == requested_owner]
        return runs[:limit]

    def update_run(
        self,
        run_id: str,
        updates: dict[str, Any],
        *,
        event: str,
        event_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        run_id = str(run_id or "").strip()
        if not run_id:
            return None
        with self._connect() as conn:
            # Hold the write lock across read, merge and write so concurrent
            # updates to one run cannot overwrite each other.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state_json FROM workbench_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            state = json.loads(row["state_json"])
            now = _utc_now()
            for key, value in updates.items():
                state[key] = value
            if "params" in updates and "params_hash" not in updates:
                state["params_hash"] = f"sha256:{_sha256_json(state.get('params') or {})}"
            state["updated_at"] = now
            events = state.get("events") if isinstance(state.get("events"), list) else []
            events.append(
                {
                    "event": str(event or "run_updated"),
                    "status": state.get("status"),
                    "current_step": state.get("current_step"),
                    "created_at": now,
                    **(event_payload or {}),
                }
            )
            state["events"] = events
            self._write_run_row(conn, state)
        return state

    def write_run(self, state: dict[str, Any]) -> None:
        with self._connect() as conn:
            self._write_run_row(conn, state)

    def _write_run_row(self, conn: sqlite3.Connection, state: dict[str, Any]) -> None:
        run_id = str(state.get("run_id") or "").strip()
        graph_id = str(state.get("graph_id") or "").strip()
        if not run_id or not graph_id:
            raise ValueError("run_id and graph_id are required")
        params_hash = str(state.get("params_hash") or f"sha256:{_sha256_json(state.get('params') or {})}")
        execution_location = state.get("execution_location") if isinstance(state.get("execution_location"), dict) else {}
        location_id = str(execution_location.get("location_id") or execution_location.get("kind") or "")
        bundle = state.get("bundle") if isinstance(state.get("bundle"), dict) else {}
        preflight = state.get("preflight") if isinstance(state.get("preflight"), dict) else {}
        execution = state.get("execution") if isinstance(state.get("execution"), dict) else {}
        now = _utc_now()
        created_at = str(state.get("created_at") or now)
        updated_at = str(state.get("updated_at") or now)
        conn.execute(
            """
            INSERT INTO workbench_runs(
              run_id, graph_id, params_hash, status, current_step,
              execution_location, bundle_id, bundle_path, preflight_id,
              execution_id, state_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              graph_id=excluded.graph_id,
              params_hash=excluded.params_hash,
              status=excluded.status,
              current_step=excluded.current_step,
              execution_location=excluded.execution_location,
              bundle_id=excluded.bundle_id,
              bundle_path=excluded.bundle_path,
              preflight_id=excluded.preflight_id,
              execution_id=excluded.execution_id,
              state_json=excluded.state_json,
              updated_at=excluded.updated_at
            """,
            (
                run_id,
                graph_id,
                params_hash,
                str(state.get("status") or ""),
                str(state.get("current_step") or ""),
                location_id,
                bundle.get("bundle_id"),
                bundle.get("bundle_path"),
                preflight.get("preflight_id"),
                execution.get("execution_id"),
                json.dumps(state),
                created_at,
                updated_at,
            ),
        )


class PreflightRepository:
    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def record_preflight(self, graph_id: str, params: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        params_hash = _sha256_json(params)
        preflight_id = _stable_id("preflight", {"graph_id": graph_id, "params_hash": params_hash, "result": result})
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preflight_runs(preflight_id, graph_id, params_hash, result_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(preflight_id) DO UPDATE SET result_json=excluded.result_json
                """,
                (preflight_id, graph_id, params_hash, json.dumps(result), str(result.get("status") or ""), now),
            )
        return {"preflight_id": preflight_id, "params_hash": params_hash}


class ExecutionRepository:
    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    def record_execution(self, graph_id: str, result: dict[str, Any], *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params_hash = _sha256_json(params or {})
        execution_id = _stable_id("execution", {"graph_id": graph_id, "params_hash": params_hash, "result": result})
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO execution_runs(execution_id, graph_id, params_hash, result_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET result_json=excluded.result_json
                """,
                (execution_id, graph_id, params_hash, json.dumps(result), str(result.get("status") or ""), now),
            )
        return {"execution_id": execution_id, "params_hash": params_hash}

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT execution_id, graph_id, params_hash, result_json, status, created_at
                FROM execution_runs
                WHERE execution_id=?
                """,
                (execution_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "execution_id": row["execution_id"],
            "graph_id": row["graph_id"],
            "params_hash": row["params_hash"],
            "result": json.loads(row["result_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
        }


def _canonical_graph_hash(graph: dict[str, Any]) -> str:
    if graph.get("canonical_graph_hash"):
        return str(graph["canonical_graph_hash"])
    return _sha256_json(
        {
            "graph_id": graph.get("graph_id"),
            "nodes": graph.get("nodes") or [],
            "edges": graph.get("edges") or [],
            "inputs": graph.get("inputs") or graph.get("required_human_inputs") or [],
            "outputs": graph.get("outputs") or [],
        }
    )


def _graph_suite(graph: dict[str, Any]) -> str | None:
    suite_recipe = graph.get("suite_recipe") if isinstance(graph.get("suite_recipe"), dict) else {}
    return _first_text(graph.get("suite"), suite_recipe.get("suite"), graph.get("runtime", {}).get("suite") if isinstance(graph.get("runtime"), dict) else None)


def _graph_runnable(graph: dict[str, Any]) -> bool:
    if graph.get("lifecycle_state") == "verified":
        return True
    materialization = str(graph.get("materialization_status") or "")
    if materialization == "runnable_nextflow_bundle":
        policy = graph.get("execution_policy") if isinstance(graph.get("execution_policy"), dict) else {}
        renderer = str(policy.get("bundle_renderer") or "").strip().lower()
        return renderer in {"available", "ready", "registered"}
    return materialization in {"runnable_bundle", "runnable_smoke_bundle", "verified_recipe"}


def _graph_search_text(graph: dict[str, Any]) -> str:
    parts = [
        graph.get("graph_id"),
        graph.get("title"),
        graph.get("description"),
        graph.get("suite"),
        graph.get("recipe_family"),
        graph.get("assay_profile"),
        graph.get("dataset_scope"),
        " ".join(_string_values(graph.get("capabilities") or [])),
        " ".join(_string_values(graph.get("modalities") or [])),
        json.dumps(graph.get("runtime") or {}, sort_keys=True),
        json.dumps(graph.get("source_manifest") or {}, sort_keys=True),
        json.dumps(graph.get("suite_recipe") or {}, sort_keys=True),
        json.dumps(graph.get("execution_policy") or {}, sort_keys=True),
    ]
    for item in [*(graph.get("inputs") or []), *(graph.get("outputs") or [])]:
        if isinstance(item, dict):
            parts.extend([item.get("name"), item.get("artifact_type")])
    return " ".join(str(part) for part in parts if part)


def _path_contracts(items: Any) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return contracts
    for index, item in enumerate(items):
        if isinstance(item, dict):
            artifact_type = str(item.get("artifact_type") or item.get("type") or "").strip()
            if not artifact_type:
                continue
            contracts.append(
                {
                    **item,
                    "name": str(item.get("name") or f"path_{index}"),
                    "artifact_type": artifact_type,
                    "required": bool(item.get("required", True)),
                }
            )
        elif str(item or "").strip():
            contracts.append({"name": str(item), "artifact_type": str(item), "required": True})
    return contracts


def _string_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out = []
    for value in values:
        text = str(value or "").strip().lower()
        if text and text not in out:
            out.append(text)
    return out


def _execution_locations(graph: dict[str, Any]) -> list[str]:
    policy = graph.get("execution_policy") if isinstance(graph.get("execution_policy"), dict) else {}
    explicit = _string_values(policy.get("supported_execution_locations") or [])
    if explicit:
        return explicit
    if _graph_runnable(graph):
        return ["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"]
    return []


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _facet_rows(conn: sqlite3.Connection, table: str, version_id: str, column: str) -> list[str]:
    rows = conn.execute(
        f"SELECT {column} FROM {table} WHERE version_id=? ORDER BY {column}",
        (version_id,),
    ).fetchall()
    return [str(row[column]) for row in rows]


def _validation_rows(conn: sqlite3.Connection, graph_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM workflow_validation_records
        WHERE graph_id=?
        ORDER BY created_at DESC, validation_id
        """,
        (graph_id,),
    ).fetchall()
    return [_validation_record_from_row(row) for row in rows]


def _validation_record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema": "morphic.workflow_validation_record/v0",
        "validation_id": row["validation_id"],
        "graph_id": row["graph_id"],
        "canonical_graph_hash": row["canonical_graph_hash"],
        "source_manifest_hash": row["source_manifest_hash"],
        "validation_kind": row["validation_kind"],
        "comparator_kind": row["comparator_kind"],
        "executor": row["executor"],
        "profile": row["profile"],
        "fixture_id": row["fixture_id"],
        "status": row["status"],
        "manifest_hash": row["manifest_hash"],
        "summary": json.loads(row["summary_json"]),
        "manifest": json.loads(row["manifest_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _normalize_validation_record(record: dict[str, Any]) -> dict[str, Any]:
    graph_id = str(record.get("graph_id") or "").strip()
    if not graph_id:
        raise ValueError("validation record graph_id is required")
    validation_kind = str(record.get("validation_kind") or "workflow_validation").strip()
    comparator_kind = str(record.get("comparator_kind") or "unknown").strip()
    status = str(record.get("status") or "").strip().lower()
    if not status:
        raise ValueError("validation record status is required")
    manifest = record.get("manifest") if isinstance(record.get("manifest"), dict) else dict(record)
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else _validation_summary(manifest)
    manifest_hash = str(record.get("manifest_hash") or f"sha256:{_sha256_json(manifest)}")
    now = _utc_now()
    created_at = str(record.get("created_at") or manifest.get("created_at") or now)
    payload = {
        "schema": "morphic.workflow_validation_record/v0",
        "validation_id": str(
            record.get("validation_id")
            or _stable_id(
                "validation",
                {
                    "graph_id": graph_id,
                    "validation_kind": validation_kind,
                    "comparator_kind": comparator_kind,
                    "fixture_id": record.get("fixture_id") or summary.get("fixture_id"),
                    "manifest_hash": manifest_hash,
                },
            )
        ),
        "graph_id": graph_id,
        "canonical_graph_hash": _none_if_empty(record.get("canonical_graph_hash") or summary.get("canonical_graph_hash")),
        "source_manifest_hash": _none_if_empty(record.get("source_manifest_hash") or summary.get("source_manifest_hash")),
        "validation_kind": validation_kind,
        "comparator_kind": comparator_kind,
        "executor": _none_if_empty(record.get("executor") or summary.get("executor")),
        "profile": _none_if_empty(record.get("profile") or summary.get("profile")),
        "fixture_id": _none_if_empty(record.get("fixture_id") or summary.get("fixture_id")),
        "status": status,
        "manifest_hash": manifest_hash,
        "summary": summary,
        "manifest": manifest,
        "created_at": created_at,
        "updated_at": str(record.get("updated_at") or now),
    }
    return payload


def _validation_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    reference = manifest.get("reference") if isinstance(manifest.get("reference"), dict) else {}
    candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
    fixture = manifest.get("fixture") if isinstance(manifest.get("fixture"), dict) else {}
    comparisons = manifest.get("comparisons") if isinstance(manifest.get("comparisons"), list) else []
    return {
        "schema": "morphic.workflow_validation_summary/v0",
        "status": manifest.get("status"),
        "graph_id": manifest.get("graph_id") or candidate.get("graph_id"),
        "canonical_graph_hash": manifest.get("canonical_graph_hash") or candidate.get("canonical_graph_hash"),
        "source_manifest_hash": manifest.get("source_manifest_hash") or candidate.get("source_manifest_hash"),
        "executor": candidate.get("execution_location_kind") or candidate.get("executor"),
        "profile": manifest.get("profile") or reference.get("profile") or candidate.get("profile"),
        "fixture_id": fixture.get("fixture_id") or manifest.get("fixture_id"),
        "comparison_count": len(comparisons),
        "comparison_kinds": sorted(
            {
                str(item.get("comparison_kind"))
                for item in comparisons
                if isinstance(item, dict) and item.get("comparison_kind")
            }
        ),
    }


def _unique_facet_values(items: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for item in items:
        value = str(item.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _none_if_empty(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _tokens(query: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(query or ""))
    return [token for token in cleaned.split() if token]


def _filters_match(record: dict[str, Any], filters: dict[str, Any], reasons: list[str]) -> bool:
    checks = [
        ("suite", "suite", False),
        ("recipe_family", "recipe_family", False),
        ("assay_profile", "assay_profile", False),
        ("lifecycle_state", "lifecycle_state", False),
        ("materialization_status", "materialization_status", False),
        ("input_artifact_types", "inputs", True),
        ("output_artifact_types", "outputs", True),
        ("capabilities", "capabilities", True),
        ("modalities", "modalities", True),
        ("execution_locations", "execution_locations", True),
        ("validation_status", "validation_statuses", True),
        ("validation_kind", "validation_kinds", True),
        ("validation_comparator_kind", "validation_comparator_kinds", True),
        ("validation_executor", "validation_executors", True),
        ("validation_fixture", "validation_fixtures", True),
    ]
    for filter_key, record_key, plural in checks:
        requested = _filter_values(filters.get(filter_key))
        if not requested:
            continue
        if plural:
            actual = {str(value).lower() for value in record.get(record_key) or []}
            if not requested <= actual:
                return False
        else:
            actual = {str(record.get(record_key) or "").lower()}
            if not requested & actual:
                return False
        reasons.append(f"filter `{filter_key}` matched")
    if bool(filters.get("verified_only")) and not record.get("verified"):
        return False
    if bool(filters.get("verified_only")):
        reasons.append("filter `verified_only` matched")
    if bool(filters.get("runnable_only")) and not record.get("runnable"):
        return False
    if bool(filters.get("runnable_only")):
        reasons.append("filter `runnable_only` matched")
    if bool(filters.get("validated_only")) and "passed" not in {str(value).lower() for value in record.get("validation_statuses") or []}:
        return False
    if bool(filters.get("validated_only")):
        reasons.append("filter `validated_only` matched")
    return True


def _filter_values(value: Any) -> set[str]:
    if value is None or value == "":
        return set()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    return {str(item).strip().lower() for item in values if str(item).strip()}


def _score_record(record: dict[str, Any], tokens: list[str], token_matches: list[str], reasons: list[str]) -> int:
    score = 10 * len(token_matches)
    graph_id = str(record.get("graph_id") or "").lower()
    title = str(record.get("title") or "").lower()
    for token in tokens:
        if token and token == graph_id:
            score += 100
        elif token and token in graph_id:
            score += 30
        if token and token in title:
            score += 20
    if record.get("verified"):
        score += 15
    if "passed" in {str(value).lower() for value in record.get("validation_statuses") or []}:
        score += 12
    if record.get("runnable"):
        score += 10
    score += len(reasons)
    return score
