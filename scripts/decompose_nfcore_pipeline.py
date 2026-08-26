#!/usr/bin/env python3
"""Create an editable source decomposition for a local nf-core checkout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morphic_agent.harvest.nfcore_decomposition import decompose_nfcore_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pipeline_path", help="Local nf-core checkout containing main.nf.")
    parser.add_argument("-o", "--output", default=None, help="Write the complete decomposition JSON to this path.")
    parser.add_argument(
        "--graph-output",
        default=None,
        help="Also write a compact component graph containing nodes and edges.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only status, provenance, summary, unresolved references, and warnings.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when a local include cannot be resolved.",
    )
    args = parser.parse_args()

    decomposition = decompose_nfcore_pipeline(args.pipeline_path, strict=args.strict)
    if args.output:
        _write_json(Path(args.output), decomposition)
    if args.graph_output:
        _write_json(Path(args.graph_output), _component_graph(decomposition))

    payload = _summary(decomposition) if args.summary else decomposition
    print(json.dumps(payload, indent=2, sort_keys=True))


def _component_graph(decomposition: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "morphic.nfcore_component_graph/v0",
        "pipeline_path": decomposition["pipeline_path"],
        "entrypoint": decomposition["entrypoint"],
        "execution_boundary": decomposition["execution_boundary"],
        "source_manifest": decomposition["source_manifest"],
        "summary": decomposition["summary"],
        "nodes": decomposition["nodes"],
        "edges": decomposition["edges"],
    }


def _summary(decomposition: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": decomposition["schema"],
        "status": decomposition["status"],
        "pipeline_path": decomposition["pipeline_path"],
        "entrypoint": decomposition["entrypoint"],
        "execution_boundary": decomposition["execution_boundary"],
        "source_manifest": decomposition["source_manifest"],
        "summary": decomposition["summary"],
        "unresolved": decomposition["unresolved"],
        "warnings": decomposition["warnings"],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
