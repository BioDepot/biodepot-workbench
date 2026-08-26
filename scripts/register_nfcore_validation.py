#!/usr/bin/env python3
"""Register an nf-core reference-comparison manifest as Workbench validation evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.db.config import resolve_database_config
from morphic_agent.harvest.nfcore_validation import nfcore_reference_validation_record
from morphic_agent.registry.store import AgentStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison_manifest", help="Path to nfcore_chr22_reference_comparison.json or an equivalent manifest.")
    parser.add_argument("--graph-id", default="", help="Graph id to attach the validation record to.")
    parser.add_argument("--run-id", default="", help="Optional Workbench run id to attach the validation evidence to.")
    parser.add_argument("--db", default=None, help="SQLite path or sqlite:/// URL for the Workbench DB.")
    parser.add_argument("--dry-run", action="store_true", help="Build the validation record without mutating the DB.")
    args = parser.parse_args()

    payload = register_validation_manifest(
        args.comparison_manifest,
        graph_id=args.graph_id,
        run_id=args.run_id,
        db=args.db,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def register_validation_manifest(
    comparison_manifest: str | Path,
    *,
    graph_id: str = "",
    run_id: str = "",
    db: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(comparison_manifest).expanduser()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("comparison manifest must be a JSON object")
    effective_graph_id = str(graph_id or manifest.get("graph_id") or "").strip()
    if effective_graph_id:
        manifest = {**manifest, "graph_id": effective_graph_id}
    effective_run_id = str(run_id or manifest.get("run_id") or "").strip()
    if effective_run_id:
        candidate = manifest.get("candidate") if isinstance(manifest.get("candidate"), dict) else {}
        manifest = {**manifest, "run_id": effective_run_id, "candidate": {**candidate, "run_id": effective_run_id}}

    target_db = str(resolve_database_config(db).sqlite_path) if db else None
    graph = None
    if not dry_run:
        store = AgentStore(target_db)
        graph = store.get_subgraph(effective_graph_id) if effective_graph_id else None
        if graph is None:
            raise SystemExit(f"graph not found in Workbench DB: {effective_graph_id or '<missing>'}")
        run = store.get_workbench_run(effective_run_id) if effective_run_id else None
        if effective_run_id and run is None:
            raise SystemExit(f"run not found in Workbench DB: {effective_run_id}")
        if run is not None and str(run.get("graph_id") or "") != str(graph.get("graph_id") or ""):
            raise SystemExit(
                f"run `{effective_run_id}` belongs to graph `{run.get('graph_id')}`, not `{graph.get('graph_id')}`"
            )
        record = nfcore_reference_validation_record(manifest, graph=graph)
        stored = store.record_workflow_validation(record)
        attached_run = store.attach_workflow_validation_to_run(effective_run_id, stored["validation_id"]) if effective_run_id else None
        return {
            "schema": "morphic.harvest.nfcore_validation_cli/v0",
            "status": "registered",
            "mutated": True,
            "target_db": str(store.db_path),
            "comparison_manifest": str(manifest_path),
            "validation_record": stored,
            "run_id": effective_run_id or None,
            "run": attached_run,
        }

    record = nfcore_reference_validation_record(manifest, graph=None)
    return {
        "schema": "morphic.harvest.nfcore_validation_cli/v0",
        "status": "dry_run",
        "mutated": False,
        "target_db": target_db,
        "comparison_manifest": str(manifest_path),
        "validation_record": record,
        "run_id": effective_run_id or None,
    }


if __name__ == "__main__":
    main()
