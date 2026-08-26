#!/usr/bin/env python3
"""Rebuild or dry-run the Workbench graph projection."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.db.config import resolve_database_config
from morphic_agent.workbench import WorkbenchService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite path or sqlite:/// URL for the Workbench DB.")
    parser.add_argument("--catalog", default=None, help="Optional module catalog JSON path.")
    parser.add_argument("--projection-version", default="morphic-agent-v0")
    parser.add_argument("--dry-run", action="store_true", help="Build the projection batch without writing projection tables.")
    args = parser.parse_args()

    cleanup_path: Path | None = None
    target_db = str(resolve_database_config(args.db).sqlite_path) if args.db else None
    db_path = args.db
    if args.dry_run:
        handle = tempfile.NamedTemporaryFile(prefix="morphic-projection-dry-run-", suffix=".sqlite3", delete=False)
        cleanup_path = Path(handle.name)
        handle.close()
        if target_db and Path(target_db).exists():
            shutil.copy2(target_db, cleanup_path)
        db_path = str(cleanup_path)
    try:
        service = WorkbenchService.create(db_path=db_path, catalog_path=args.catalog)
        projection_service = service.graph_index.projection_service
        if projection_service is None:
            payload = {
                "schema": "morphic.graph_projection_manifest/v0",
                "status": "unavailable",
                "projection_version": args.projection_version,
                "mutated": False,
                "run_blocker": "No projection service is configured.",
            }
        elif args.dry_run:
            payload = projection_service.rebuild_projection(args.projection_version, dry_run=True)
            payload["target_db"] = target_db
            payload["scratch_db"] = str(service.store.db_path)
        else:
            payload = service.rebuild_graph_projection(args.projection_version)
            payload["target_db"] = str(service.store.db_path)
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
