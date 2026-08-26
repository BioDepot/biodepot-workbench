#!/usr/bin/env python3
"""Backfill canonical graph/search records from configured Workbench content."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.db.config import resolve_database_config
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.registry.store import AgentStore
from morphic_agent.suites.module_import import suite_recipe_graphs_from_modules, suite_recipe_module_catalog
from morphic_agent.workbench import WorkbenchService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite path or sqlite:/// URL for the Workbench DB.")
    parser.add_argument("--catalog", default=None, help="Optional module catalog JSON path.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned imports without mutating the DB.")
    args = parser.parse_args()

    target = resolve_database_config(args.db).url if args.db else None
    if args.dry_run:
        payload = _dry_run_payload(args.catalog, target)
    else:
        payload = _backfill(args.catalog, args.db)
    print(json.dumps(payload, indent=2, sort_keys=True))


def _dry_run_payload(catalog_path: str | None, target: str | None) -> dict[str, Any]:
    catalog = ModuleCatalog(catalog_path, store=None)
    base_modules = catalog._payload.get("modules") or []
    reserved = {
        str(module.get("module_id") or "")
        for module in base_modules
        if isinstance(module, dict) and module.get("module_id")
    }
    suite_payload = suite_recipe_module_catalog(reserved_module_ids=reserved)
    suite_modules = suite_payload.get("modules") or []
    suite_graphs = suite_recipe_graphs_from_modules(suite_modules)
    return {
        "schema": "morphic.backfill_graph_search_index/v0",
        "status": "dry_run",
        "mutated": False,
        "target_db": target,
        "planned": {
            "module_catalog_modules": len(base_modules),
            "suite_recipe_modules": len(suite_modules),
            "suite_recipe_graphs": len(suite_graphs),
            "compatibility_edges": "computed_on_write",
        },
        "catalog_errors": catalog._payload.get("errors") or [],
    }


def _backfill(catalog_path: str | None, db: str | None) -> dict[str, Any]:
    service = WorkbenchService.create(db_path=db, catalog_path=catalog_path)
    store = service.store
    compatibility = store.rebuild_compatibility_edges()
    return {
        "schema": "morphic.backfill_graph_search_index/v0",
        "status": "backfilled",
        "mutated": True,
        "target_db": str(store.db_path),
        "counts": _counts(store),
        "compatibility": compatibility,
        "catalog_import": service.catalog.import_manifest,
        "suite_import": service.catalog.suite_import_manifest,
        "suite_graph_import": service.catalog.suite_graph_import_manifest,
    }


def _counts(store: AgentStore) -> dict[str, int]:
    tables = (
        "modules",
        "module_versions",
        "workflow_graphs",
        "workflow_graph_versions",
        "workflow_graph_inputs",
        "workflow_graph_outputs",
        "workflow_graph_capabilities",
        "workflow_graph_modalities",
        "workflow_graph_execution_locations",
        "compatibility_edges",
        "verified_recipes",
    )
    return {table: store.count_rows(table) for table in tables}


if __name__ == "__main__":
    main()
