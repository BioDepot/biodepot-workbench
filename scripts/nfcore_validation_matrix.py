#!/usr/bin/env python3
"""Report default-safe validation status for harvested nf-core recipes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.db.config import resolve_database_config
from morphic_agent.harvest.nfcore_validation_matrix import build_nfcore_validation_matrix
from morphic_agent.registry.store import AgentStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite path or sqlite:/// URL for the Workbench DB.")
    parser.add_argument("--out-root", default=None, help="Optional bundle output root for render/preflight checks.")
    parser.add_argument("--execution-location", default="server", help="Execution location for preflight checks.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--no-render", action="store_true", help="Skip bundle rendering checks.")
    parser.add_argument("--no-preflight", action="store_true", help="Skip preflight checks.")
    args = parser.parse_args()

    store = AgentStore(str(resolve_database_config(args.db).sqlite_path) if args.db else None)
    payload = build_nfcore_validation_matrix(
        store,
        out_root=args.out_root,
        execution_location=args.execution_location,
        render=not args.no_render,
        preflight=not args.no_preflight,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
