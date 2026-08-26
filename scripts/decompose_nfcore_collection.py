#!/usr/bin/env python3
"""Discover and decompose local nf-core checkouts below a directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.harvest.nfcore_decomposition import decompose_nfcore_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection_root", help="Directory containing one or more local nf-core checkouts.")
    parser.add_argument("--out-root", required=True, help="Directory for decomposition artifacts and manifest.json.")
    parser.add_argument("--strict", action="store_true", help="Fail a pipeline when a local include cannot be resolved.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed pipeline.")
    args = parser.parse_args()

    collection_root = Path(args.collection_root).expanduser().resolve()
    out_root = Path(args.out_root).expanduser().resolve()
    if not collection_root.is_dir():
        raise SystemExit(f"collection root not found: {collection_root}")
    out_root.mkdir(parents=True, exist_ok=True)

    pipelines = sorted(
        {
            schema.parent
            for schema in collection_root.rglob("nextflow_schema.json")
            if (schema.parent / "main.nf").is_file() and not _is_generated_path(schema, collection_root)
        },
        key=lambda path: path.relative_to(collection_root).as_posix(),
    )
    results: list[dict[str, Any]] = []
    for pipeline in pipelines:
        relative = pipeline.relative_to(collection_root).as_posix() or pipeline.name
        artifact_dir = out_root / _slug(relative)
        try:
            decomposition = decompose_nfcore_pipeline(pipeline, strict=args.strict)
            _write_json(artifact_dir / "decomposition.json", decomposition)
            _write_json(
                artifact_dir / "component_graph.json",
                {
                    "schema": "morphic.nfcore_component_graph/v0",
                    "pipeline_path": decomposition["pipeline_path"],
                    "entrypoint": decomposition["entrypoint"],
                    "execution_boundary": decomposition["execution_boundary"],
                    "source_manifest": decomposition["source_manifest"],
                    "summary": decomposition["summary"],
                    "nodes": decomposition["nodes"],
                    "edges": decomposition["edges"],
                },
            )
            results.append(
                {
                    "pipeline": relative,
                    "status": decomposition["status"],
                    "artifact_dir": str(artifact_dir),
                    "source_index_hash": decomposition["source_manifest"]["source_index_hash"],
                    "summary": decomposition["summary"],
                }
            )
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            results.append({"pipeline": relative, "status": "error", "error": str(exc)})
            if args.fail_fast:
                break

    manifest = {
        "schema": "morphic.nfcore_decomposition_collection/v0",
        "collection_root": str(collection_root),
        "pipeline_count": len(pipelines),
        "processed_count": len(results),
        "error_count": sum(1 for item in results if item["status"] == "error"),
        "results": results,
    }
    _write_json(out_root / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if manifest["error_count"]:
        raise SystemExit(1)


def _is_generated_path(path: Path, root: Path) -> bool:
    return bool({".git", ".nextflow", "work", "results", "bwb_output"} & set(path.relative_to(root).parts))


def _slug(value: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "__", value).strip("._-") or "pipeline"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
