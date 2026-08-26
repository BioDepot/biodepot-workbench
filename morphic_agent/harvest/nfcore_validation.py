"""Validation record helpers for harvested nf-core workflow wrappers."""

from __future__ import annotations

from typing import Any

NFCORE_VALIDATION_RECORD_SCHEMA = "morphic.nfcore_validation_record/v0"
NFCORE_REFERENCE_COMPARISON_KIND = "nfcore_reference_comparison"
NFCORE_REFERENCE_NEXTFLOW_COMPARATOR = "reference_nextflow"


def nfcore_reference_validation_record(
    comparison_manifest: dict[str, Any],
    *,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a registry validation record from a Workbench-vs-Nextflow comparison."""

    comparison_manifest = validate_nfcore_reference_comparison_manifest(comparison_manifest)
    graph_payload = graph if isinstance(graph, dict) else {}
    runtime = graph_payload.get("runtime") if isinstance(graph_payload.get("runtime"), dict) else {}
    source_manifest = graph_payload.get("source_manifest") if isinstance(graph_payload.get("source_manifest"), dict) else {}
    reference = comparison_manifest.get("reference") if isinstance(comparison_manifest.get("reference"), dict) else {}
    candidate = comparison_manifest.get("candidate") if isinstance(comparison_manifest.get("candidate"), dict) else {}
    fixture = comparison_manifest.get("fixture") if isinstance(comparison_manifest.get("fixture"), dict) else {}

    graph_id = _first_text(
        comparison_manifest.get("graph_id"),
        candidate.get("graph_id"),
        graph_payload.get("graph_id"),
    )
    if not graph_id:
        raise ValueError("comparison manifest does not identify a graph_id")

    status = str(comparison_manifest.get("status") or "").strip().lower()
    if status == "passed":
        status = "passed"
    elif status in {"failed", "blocked", "skipped"}:
        status = status
    else:
        status = "unknown"

    comparison_kinds = sorted(
        {
            str(item.get("comparison_kind"))
            for item in comparison_manifest.get("comparisons") or []
            if isinstance(item, dict) and item.get("comparison_kind")
        }
    )
    fixture_id = _first_text(fixture.get("fixture_id"), comparison_manifest.get("fixture_id"))
    summary = {
        "schema": "morphic.nfcore_validation_summary/v0",
        "status": status,
        "graph_id": graph_id,
        "pipeline": _first_text(
            comparison_manifest.get("pipeline"),
            reference.get("pipeline"),
            runtime.get("pipeline_name"),
            runtime.get("pipeline"),
        ),
        "release": _first_text(comparison_manifest.get("release"), reference.get("release"), runtime.get("release")),
        "profile": _first_text(comparison_manifest.get("profile"), reference.get("profile"), candidate.get("profile"), "docker"),
        "executor": _first_text(candidate.get("execution_location_kind"), candidate.get("executor")),
        "run_id": _first_text(comparison_manifest.get("run_id"), candidate.get("run_id")),
        "fixture_id": fixture_id,
        "comparison_count": len(comparison_manifest.get("comparisons") or []),
        "comparison_kinds": comparison_kinds,
        "source_manifest_hash": _first_text(
            comparison_manifest.get("source_manifest_hash"),
            candidate.get("source_manifest_hash"),
            source_manifest.get("schema_hash"),
        ),
        "canonical_graph_hash": _first_text(comparison_manifest.get("canonical_graph_hash"), graph_payload.get("canonical_graph_hash")),
    }
    return {
        "schema": NFCORE_VALIDATION_RECORD_SCHEMA,
        "graph_id": graph_id,
        "canonical_graph_hash": summary.get("canonical_graph_hash"),
        "source_manifest_hash": summary.get("source_manifest_hash"),
        "validation_kind": NFCORE_REFERENCE_COMPARISON_KIND,
        "comparator_kind": NFCORE_REFERENCE_NEXTFLOW_COMPARATOR,
        "executor": summary.get("executor"),
        "profile": summary.get("profile"),
        "fixture_id": fixture_id,
        "status": status,
        "summary": summary,
        "manifest": comparison_manifest,
    }


def validate_nfcore_reference_comparison_manifest(comparison_manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate that a comparison manifest is explicitly anchored to reference Nextflow."""

    if not isinstance(comparison_manifest, dict):
        raise TypeError("comparison manifest must be a JSON object")
    comparator = str(comparison_manifest.get("comparator_kind") or "").strip()
    if comparator and comparator != NFCORE_REFERENCE_NEXTFLOW_COMPARATOR:
        raise ValueError("nf-core validation comparisons must use comparator_kind `reference_nextflow`")
    reference = comparison_manifest.get("reference")
    if not isinstance(reference, dict) or not reference:
        raise ValueError("nf-core reference comparison manifest requires a reference Nextflow section")
    reference_evidence = [
        reference.get("execution_result"),
        reference.get("launch_command"),
        reference.get("bundle_path"),
        reference.get("pipeline"),
        reference.get("outdir"),
    ]
    if not any(str(item or "").strip() for item in reference_evidence):
        raise ValueError("reference Nextflow section must identify the direct Nextflow run or output")
    candidate = comparison_manifest.get("candidate")
    if not isinstance(candidate, dict) or not candidate:
        raise ValueError("nf-core reference comparison manifest requires a Workbench candidate section")
    comparisons = comparison_manifest.get("comparisons")
    if comparisons is not None and not isinstance(comparisons, list):
        raise ValueError("comparison manifest comparisons must be a list")
    return comparison_manifest


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None
