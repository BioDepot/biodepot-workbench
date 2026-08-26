#!/usr/bin/env python3
"""Harvest a local nf-core schema or checkout into the Workbench registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.db.config import resolve_database_config
from morphic_agent.harvest.nfcore import (
    harvest_nfcore_pipeline_path_to_registry,
    harvest_nfcore_remote_pipeline_to_registry,
    harvest_nfcore_schema_file_to_registry,
)
from morphic_agent.harvest.nfcore_decomposition import attach_nfcore_decomposition, decompose_nfcore_pipeline
from morphic_agent.harvest.nfcore_mapper import map_nextflow_schema, map_nextflow_schema_file
from morphic_agent.harvest.nfcore_remote import fetch_nfcore_remote_metadata, looks_like_nfcore_pipeline_spec
from morphic_agent.registry.store import AgentStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pipeline_path",
        nargs="?",
        default="",
        help="Local nf-core checkout path, nextflow_schema.json path, or nf-core/<pipeline> when --allow-network is set.",
    )
    parser.add_argument("--schema", default=None, help="Explicit nextflow_schema.json path.")
    parser.add_argument("--modules-json", default=None, help="Optional modules.json path.")
    parser.add_argument("--release", default=None, help="nf-core release/tag/ref for remote metadata harvest.")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Allow fetching small remote nf-core metadata files for nf-core/<pipeline> specs.",
    )
    parser.add_argument("--db", default=None, help="SQLite path or sqlite:/// URL for the Workbench DB.")
    parser.add_argument("--cache-root", default=None, help="Optional local metadata cache root to populate.")
    parser.add_argument(
        "--no-decompose",
        action="store_true",
        help="Keep local checkout harvest schema-only even when main.nf is present.",
    )
    parser.add_argument(
        "--strict-decomposition",
        action="store_true",
        help="Fail local checkout decomposition when a local include cannot be resolved.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Map the schema without mutating the DB.")
    args = parser.parse_args()

    if args.dry_run:
        payload = _dry_run(
            args.pipeline_path,
            schema_path=args.schema,
            modules_json_path=args.modules_json,
            release=args.release,
            allow_network=args.allow_network,
            db=args.db,
            cache_root=args.cache_root,
            decompose_source=not args.no_decompose,
            strict_decomposition=args.strict_decomposition,
        )
    else:
        payload = _harvest(
            args.pipeline_path,
            schema_path=args.schema,
            modules_json_path=args.modules_json,
            release=args.release,
            allow_network=args.allow_network,
            db=args.db,
            cache_root=args.cache_root,
            decompose_source=not args.no_decompose,
            strict_decomposition=args.strict_decomposition,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))


def _dry_run(
    pipeline_path: str,
    *,
    schema_path: str | None,
    modules_json_path: str | None,
    release: str | None,
    allow_network: bool,
    db: str | None,
    cache_root: str | None,
    decompose_source: bool,
    strict_decomposition: bool,
) -> dict[str, Any]:
    remote_metadata = None
    decomposition = None
    if _remote_requested(pipeline_path, schema_path=schema_path):
        if not allow_network:
            raise SystemExit("remote nf-core metadata harvest requires --allow-network")
        remote_metadata = fetch_nfcore_remote_metadata(pipeline_path, release=release)
        result = map_nextflow_schema(
            remote_metadata.schema,
            modules_json=remote_metadata.modules_json,
            provenance=remote_metadata.provenance,
        )
        source_kind = "remote_metadata"
    else:
        schema, modules_json = _resolve_inputs(pipeline_path, schema_path=schema_path, modules_json_path=modules_json_path)
        result = map_nextflow_schema_file(
            schema,
            modules_json_path=modules_json,
            provenance={"schema_path": str(schema), **({"modules_json_path": str(modules_json)} if modules_json else {})},
        )
        pipeline_root = Path(pipeline_path).expanduser() if pipeline_path else schema.parent
        if pipeline_root.is_file():
            pipeline_root = pipeline_root.parent
        if decompose_source and (pipeline_root / "main.nf").is_file():
            decomposition = decompose_nfcore_pipeline(pipeline_root, strict=strict_decomposition)
            result = attach_nfcore_decomposition(result, decomposition)
        source_kind = "local_metadata"
    return {
        "schema": "morphic.harvest.nfcore_pipeline_cli/v0",
        "status": "dry_run",
        "mutated": False,
        "source_kind": source_kind,
        "target_db": str(resolve_database_config(db).sqlite_path) if db else None,
        "cache_root": str(Path(cache_root).expanduser()) if cache_root else None,
        "would_cache_metadata": bool(cache_root),
        "would_fetch_metadata": remote_metadata is not None,
        "module_id": result.module_contract["module_id"],
        "graph_id": result.workflow_graph["graph_id"],
        "source_manifest": result.source_manifest,
        "remote_metadata": remote_metadata.manifest() if remote_metadata is not None else None,
        "decomposition": (
            {
                "status": decomposition["status"],
                "summary": decomposition["summary"],
                "source_index_hash": decomposition["source_manifest"]["source_index_hash"],
            }
            if decomposition is not None
            else None
        ),
        "search_facets": {
            "suite": result.workflow_graph.get("suite"),
            "recipe_family": result.workflow_graph.get("recipe_family"),
            "capabilities": result.workflow_graph.get("capabilities") or [],
            "input_artifact_types": [
                item.get("artifact_type")
                for item in result.workflow_graph.get("inputs") or []
                if isinstance(item, dict) and item.get("artifact_type")
            ],
            "output_artifact_types": [
                item.get("artifact_type")
                for item in result.workflow_graph.get("outputs") or []
                if isinstance(item, dict) and item.get("artifact_type")
            ],
        },
    }


def _harvest(
    pipeline_path: str,
    *,
    schema_path: str | None,
    modules_json_path: str | None,
    release: str | None,
    allow_network: bool,
    db: str | None,
    cache_root: str | None,
    decompose_source: bool,
    strict_decomposition: bool,
) -> dict[str, Any]:
    db_path = str(resolve_database_config(db).sqlite_path) if db else None
    store = AgentStore(db_path)
    if schema_path:
        result = harvest_nfcore_schema_file_to_registry(
            schema_path,
            store,
            modules_json_path=modules_json_path,
            provenance={"harvested_by": "scripts/harvest_nfcore_pipeline.py"},
            cache_root=cache_root,
        )
    elif _remote_requested(pipeline_path, schema_path=schema_path):
        if not allow_network:
            raise SystemExit("remote nf-core metadata harvest requires --allow-network")
        result = harvest_nfcore_remote_pipeline_to_registry(
            pipeline_path,
            store,
            release=release,
            provenance={"harvested_by": "scripts/harvest_nfcore_pipeline.py"},
            cache_root=cache_root,
        )
    else:
        if not pipeline_path:
            raise SystemExit("pipeline_path or --schema is required")
        result = harvest_nfcore_pipeline_path_to_registry(
            pipeline_path,
            store,
            decompose_source=decompose_source,
            strict_decomposition=strict_decomposition,
            provenance={"harvested_by": "scripts/harvest_nfcore_pipeline.py"},
            cache_root=cache_root,
        )
    return {
        "schema": "morphic.harvest.nfcore_pipeline_cli/v0",
        **result.import_manifest,
        "status": "harvested",
        "import_status": result.import_manifest.get("status"),
        "mutated": True,
        "target_db": str(store.db_path),
    }


def _resolve_inputs(
    pipeline_path: str,
    *,
    schema_path: str | None,
    modules_json_path: str | None,
) -> tuple[Path, Path | None]:
    if schema_path:
        schema = Path(schema_path).expanduser()
    else:
        if not pipeline_path:
            raise SystemExit("pipeline_path or --schema is required")
        candidate = Path(pipeline_path).expanduser()
        schema = candidate / "nextflow_schema.json" if candidate.is_dir() else candidate
    if not schema.is_file():
        raise SystemExit(f"nextflow_schema.json not found: {schema}")
    if modules_json_path:
        modules = Path(modules_json_path).expanduser()
    else:
        modules = schema.parent / "modules.json"
    if modules is not None and not modules.is_file():
        modules = None
    return schema, modules


def _remote_requested(pipeline_path: str, *, schema_path: str | None) -> bool:
    return schema_path is None and looks_like_nfcore_pipeline_spec(pipeline_path)


if __name__ == "__main__":
    main()
