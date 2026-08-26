#!/usr/bin/env python3
"""Harvest an explicit JSON index of nf-core pipeline metadata entries."""

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
from morphic_agent.harvest.nfcore_mapper import map_nextflow_schema, map_nextflow_schema_file
from morphic_agent.harvest.nfcore_remote import fetch_nfcore_remote_metadata, looks_like_nfcore_pipeline_spec
from morphic_agent.registry.store import AgentStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index_path", help="JSON file containing nf-core pipeline metadata entries.")
    parser.add_argument("--db", default=None, help="SQLite path or sqlite:/// URL for the Workbench DB.")
    parser.add_argument("--cache-root", default=None, help="Optional local metadata cache root to populate.")
    parser.add_argument("--allow-network", action="store_true", help="Allow remote nf-core metadata fetches for nf-core/<pipeline> entries.")
    parser.add_argument("--dry-run", action="store_true", help="Map entries without mutating the DB or metadata cache.")
    args = parser.parse_args()

    payload = harvest_index(
        args.index_path,
        db=args.db,
        cache_root=args.cache_root,
        allow_network=args.allow_network,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def harvest_index(
    index_path: str | Path,
    *,
    db: str | None = None,
    cache_root: str | Path | None = None,
    allow_network: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    entries = _load_entries(index_path)
    store = None if dry_run else AgentStore(str(resolve_database_config(db).sqlite_path) if db else None)
    results = []
    for position, entry in enumerate(entries):
        results.append(
            _harvest_entry(
                entry,
                position=position,
                store=store,
                cache_root=cache_root,
                allow_network=allow_network,
                dry_run=dry_run,
            )
        )
    ok_count = sum(1 for item in results if item.get("status") in {"ok", "dry_run"})
    blocked_count = sum(1 for item in results if item.get("status") == "blocked")
    error_count = sum(1 for item in results if item.get("status") == "error")
    return {
        "schema": "morphic.harvest.nfcore_index_cli/v0",
        "status": "ok" if ok_count == len(results) else ("blocked" if blocked_count and not error_count else "partial"),
        "mutated": not dry_run,
        "index_path": str(Path(index_path).expanduser()),
        "target_db": str(resolve_database_config(db).sqlite_path) if db else None,
        "cache_root": str(Path(cache_root).expanduser()) if cache_root else None,
        "allow_network": bool(allow_network),
        "entry_count": len(results),
        "ok_count": ok_count,
        "blocked_count": blocked_count,
        "error_count": error_count,
        "results": results,
    }


def _harvest_entry(
    entry: dict[str, Any],
    *,
    position: int,
    store: AgentStore | None,
    cache_root: str | Path | None,
    allow_network: bool,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        if dry_run:
            return _dry_run_entry(entry, position=position, allow_network=allow_network)
        assert store is not None
        result = _mutate_entry(entry, store=store, cache_root=cache_root, allow_network=allow_network)
        return {
            "status": "ok",
            "position": position,
            "entry_id": _entry_id(entry, position),
            "source_kind": _entry_source_kind(entry, allow_network=allow_network),
            "module_id": result.import_manifest["module_id"],
            "graph_id": result.import_manifest["graph_id"],
            "source_manifest": result.import_manifest["source_manifest"],
            "cache_manifest": result.import_manifest.get("cache_manifest"),
            "remote_metadata": result.import_manifest.get("remote_metadata"),
        }
    except _BlockedEntry as exc:
        return {
            "status": "blocked",
            "position": position,
            "entry_id": _entry_id(entry, position),
            "run_blocker": str(exc),
        }
    except Exception as exc:
        return {
            "status": "error",
            "position": position,
            "entry_id": _entry_id(entry, position),
            "error": str(exc),
        }


def _dry_run_entry(entry: dict[str, Any], *, position: int, allow_network: bool) -> dict[str, Any]:
    schema_path = _optional_text(entry, "schema_path", "schema")
    modules_json_path = _optional_text(entry, "modules_json_path", "modules_json")
    pipeline_path = _optional_text(entry, "pipeline_path", "pipeline")
    release = _optional_text(entry, "release")
    if schema_path:
        schema, modules_json = _resolve_local_inputs(pipeline_path, schema_path=schema_path, modules_json_path=modules_json_path)
        harvest = map_nextflow_schema_file(
            schema,
            modules_json_path=modules_json,
            provenance={"schema_path": str(schema), **({"modules_json_path": str(modules_json)} if modules_json else {})},
        )
        source_kind = "local_schema"
    elif looks_like_nfcore_pipeline_spec(pipeline_path):
        if not allow_network:
            raise _BlockedEntry("Remote nf-core metadata harvest requires --allow-network.")
        metadata = fetch_nfcore_remote_metadata(pipeline_path, release=release)
        harvest = map_nextflow_schema(metadata.schema, modules_json=metadata.modules_json, provenance=metadata.provenance)
        source_kind = "remote_metadata"
    else:
        schema, modules_json = _resolve_local_inputs(pipeline_path, schema_path=schema_path, modules_json_path=modules_json_path)
        harvest = map_nextflow_schema_file(
            schema,
            modules_json_path=modules_json,
            provenance={"schema_path": str(schema), **({"modules_json_path": str(modules_json)} if modules_json else {})},
        )
        source_kind = "local_pipeline_path"
    return {
        "status": "dry_run",
        "position": position,
        "entry_id": _entry_id(entry, position),
        "source_kind": source_kind,
        "module_id": harvest.module_contract["module_id"],
        "graph_id": harvest.workflow_graph["graph_id"],
        "source_manifest": harvest.source_manifest,
    }


def _mutate_entry(
    entry: dict[str, Any],
    *,
    store: AgentStore,
    cache_root: str | Path | None,
    allow_network: bool,
):
    schema_path = _optional_text(entry, "schema_path", "schema")
    modules_json_path = _optional_text(entry, "modules_json_path", "modules_json")
    pipeline_path = _optional_text(entry, "pipeline_path", "pipeline")
    release = _optional_text(entry, "release")
    if schema_path:
        return harvest_nfcore_schema_file_to_registry(
            schema_path,
            store,
            modules_json_path=modules_json_path or None,
            provenance={"harvested_by": "scripts/harvest_nfcore_index.py"},
            cache_root=cache_root,
        )
    if looks_like_nfcore_pipeline_spec(pipeline_path):
        if not allow_network:
            raise _BlockedEntry("Remote nf-core metadata harvest requires --allow-network.")
        return harvest_nfcore_remote_pipeline_to_registry(
            pipeline_path,
            store,
            release=release or None,
            provenance={"harvested_by": "scripts/harvest_nfcore_index.py"},
            cache_root=cache_root,
        )
    if not pipeline_path:
        raise ValueError("pipeline_path or schema_path is required")
    return harvest_nfcore_pipeline_path_to_registry(
        pipeline_path,
        store,
        provenance={"harvested_by": "scripts/harvest_nfcore_index.py"},
        cache_root=cache_root,
    )


def _load_entries(index_path: str | Path) -> list[dict[str, Any]]:
    path = Path(index_path).expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = payload.get("pipelines") or payload.get("entries") or []
    else:
        raise TypeError("nf-core index must be a JSON object or array")
    if not isinstance(entries, list):
        raise TypeError("nf-core index entries must be a list")
    out: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise TypeError("each nf-core index entry must be a JSON object")
        out.append(item)
    return out


def _resolve_local_inputs(
    pipeline_path: str,
    *,
    schema_path: str | None,
    modules_json_path: str | None,
) -> tuple[Path, Path | None]:
    if schema_path:
        schema = Path(schema_path).expanduser()
    else:
        if not pipeline_path:
            raise ValueError("pipeline_path or schema_path is required")
        candidate = Path(pipeline_path).expanduser()
        schema = candidate / "nextflow_schema.json" if candidate.is_dir() else candidate
    if not schema.is_file():
        raise FileNotFoundError(f"nextflow_schema.json not found: {schema}")
    if modules_json_path:
        modules_json = Path(modules_json_path).expanduser()
    else:
        modules_json = schema.parent / "modules.json"
    if modules_json is not None and not modules_json.is_file():
        modules_json = None
    return schema, modules_json


def _entry_source_kind(entry: dict[str, Any], *, allow_network: bool) -> str:
    if _optional_text(entry, "schema_path", "schema"):
        return "local_schema"
    pipeline_path = _optional_text(entry, "pipeline_path", "pipeline")
    if allow_network and looks_like_nfcore_pipeline_spec(pipeline_path):
        return "remote_metadata"
    return "local_pipeline_path"


def _entry_id(entry: dict[str, Any], position: int) -> str:
    return _optional_text(entry, "id", "pipeline", "pipeline_path", "schema_path") or f"entry_{position}"


def _optional_text(entry: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class _BlockedEntry(RuntimeError):
    pass


if __name__ == "__main__":
    main()
