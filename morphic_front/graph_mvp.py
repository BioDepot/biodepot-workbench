"""STAR recipe graph MVP.

This module is the first executable slice of the Postgres + ArcadeDB plan:

* Postgres remains the future canonical store for recipe sources, contracts,
  runs, bundles, and verification manifests.
* ArcadeDB remains the future graph planning projection for modules, artifact
  contracts, compatibility edges, and subgraph search.

For the MVP tests we use an in-memory GraphIndex implementation with the same
shape the production adapters should expose. That lets us exercise planning,
materialization, local execution, and verification before the databases are
deployed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
import textwrap
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


EXAMPLE_PERTURB_POST_MEX_SMOKE_REL = Path("tests/example_perturbation_smoke")


def _default_star_suite_root() -> Path:
    from morphic_agent.content.paths import star_suite_root

    return star_suite_root()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    return _sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _safe_graph_id(text: str) -> str:
    keep = []
    for ch in text.lower():
        keep.append(ch if ch.isalnum() else "_")
    value = "".join(keep).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "graph"


@dataclass
class GraphVertex:
    id: str
    label: str
    kind: str
    properties: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "properties": self.properties,
        }


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    label: str
    artifact_type: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "label": self.label,
            "artifact_type": self.artifact_type,
            "properties": self.properties,
        }


@dataclass
class RecipeGraph:
    graph_id: str
    title: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    capabilities: list[str]
    evidence: list[dict[str, Any]]
    lifecycle_state: str = "candidate"
    confidence_tier: str = "source_derived"
    materialization_status: str = "runnable_smoke_bundle"
    planner_trace: list[str] = field(default_factory=list)
    projection: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema": "morphic.recipe_graph/v0",
            "graph_id": self.graph_id,
            "title": self.title,
            "nodes": self.nodes,
            "edges": self.edges,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "capabilities": self.capabilities,
            "evidence": self.evidence,
            "lifecycle_state": self.lifecycle_state,
            "confidence_tier": self.confidence_tier,
            "materialization_status": self.materialization_status,
            "planner_trace": self.planner_trace,
            "projection": self.projection,
            "execution": self.execution,
        }
        payload["canonical_graph_hash"] = _sha256_json(
            {
                "graph_id": self.graph_id,
                "nodes": self.nodes,
                "edges": self.edges,
                "inputs": self.inputs,
                "outputs": self.outputs,
            }
        )
        return payload


class InMemoryGraphIndex:
    """ArcadeDB-shaped graph index used by the MVP tests.

    The public methods mirror the GraphIndex API in the runbook. Production code
    should provide an ArcadeDB adapter with the same method names rather than
    leaking Cypher/Gremlin into planner code.
    """

    def __init__(self) -> None:
        self.vertices: dict[str, GraphVertex] = {}
        self.edges: list[GraphEdge] = []
        self.subgraphs: dict[str, RecipeGraph] = {}
        self.projection_manifest = {
            "schema": "morphic.graph_projection_manifest/v0",
            "canonical_store": "postgres",
            "graph_index": "arcadedb",
            "test_backend": "in_memory",
            "projection_version": "star-mvp-v0",
            "created_at": _utc_now(),
        }

    def upsert_vertex(self, vertex: GraphVertex) -> None:
        self.vertices[vertex.id] = vertex

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    def add_subgraph(self, graph: RecipeGraph) -> None:
        self.subgraphs[graph.graph_id] = graph

    def rebuild_graph_index(self) -> dict[str, Any]:
        return {
            **self.projection_manifest,
            "vertex_count": len(self.vertices),
            "edge_count": len(self.edges),
            "subgraph_count": len(self.subgraphs),
        }

    def find_verified_subgraphs(self, problem_signature: dict[str, Any]) -> list[RecipeGraph]:
        requested = set(problem_signature.get("requested_outputs") or [])
        capabilities = set(problem_signature.get("capabilities") or [])
        out: list[RecipeGraph] = []
        for graph in self.subgraphs.values():
            graph_outputs = {str(item.get("artifact_type")) for item in graph.outputs}
            graph_caps = set(graph.capabilities)
            if requested and not requested <= graph_outputs:
                continue
            if capabilities and not capabilities <= graph_caps:
                continue
            if graph.lifecycle_state in {"verified", "published"}:
                out.append(graph)
        return out

    def find_candidate_paths(
        self,
        input_artifacts: list[str],
        requested_outputs: list[str],
        constraints: dict[str, Any] | None = None,
    ) -> list[RecipeGraph]:
        constraints = constraints or {}
        capabilities = set(constraints.get("capabilities") or [])
        inputs = set(input_artifacts)
        requested = set(requested_outputs)
        out: list[RecipeGraph] = []
        for graph in self.subgraphs.values():
            graph_inputs = {str(item.get("artifact_type")) for item in graph.inputs}
            graph_outputs = {str(item.get("artifact_type")) for item in graph.outputs}
            graph_caps = set(graph.capabilities)
            if inputs and not inputs <= graph_inputs:
                continue
            if requested and not requested <= graph_outputs:
                continue
            if capabilities and not capabilities <= graph_caps:
                continue
            out.append(graph)
        return out

    def hydrate_graph(self, graph_id: str) -> RecipeGraph:
        return self.subgraphs[graph_id]

    def store_verified_recipe(self, graph: RecipeGraph, execution_result: dict[str, Any]) -> RecipeGraph:
        if execution_result.get("status") != "verified" or not execution_result.get("verified_recipe"):
            raise ValueError("execution_result is not verified")
        verified = copy.deepcopy(graph)
        verified.lifecycle_state = "verified"
        verified.materialization_status = "verified_recipe"
        verified.execution = {
            **verified.execution,
            "last_execution_result": execution_result,
            "verified_at": _utc_now(),
        }
        self.add_subgraph(verified)
        self.upsert_vertex(
            GraphVertex(
                id=f"subgraph:{verified.graph_id}",
                label=verified.title,
                kind="Subgraph",
                properties={
                    "pg_ref": f"subgraph_versions:{verified.graph_id}:verified",
                    "source_hash": verified.as_dict()["canonical_graph_hash"],
                    "confidence_tier": verified.confidence_tier,
                    "lifecycle_state": verified.lifecycle_state,
                    "materialization_status": verified.materialization_status,
                },
            )
        )
        return verified


def _workflow_source_vertex(star_root: Path, workflow_id: str) -> GraphVertex:
    path = star_root / "mcp_server" / "workflows" / f"{workflow_id}.yaml"
    payload = _load_yaml(path) if path.is_file() else {"id": workflow_id}
    return GraphVertex(
        id=f"recipe:{workflow_id}",
        label=str(payload.get("title") or workflow_id),
        kind="RecipeSource",
        properties={
            "pg_ref": f"recipe_sources:{workflow_id}",
            "source_path": str(path),
            "source_hash": _sha256_json(payload),
            "workflow_id": workflow_id,
            "workflow_kind": payload.get("kind"),
            "entry_script": payload.get("entry_script"),
            "confidence_tier": "tested_local_recipe" if path.is_file() else "source_derived",
        },
    )


def _module_vertex(module_id: str, label: str, *, confidence: str, evidence: list[str]) -> GraphVertex:
    return GraphVertex(
        id=f"module:{module_id}",
        label=label,
        kind="Module",
        properties={
            "pg_ref": f"module_versions:{module_id}:v0",
            "confidence_tier": confidence,
            "evidence": evidence,
            "materialization_status": "smoke_materializable",
        },
    )


def _artifact_vertex(artifact_type: str, label: str) -> GraphVertex:
    return GraphVertex(
        id=f"artifact:{artifact_type}",
        label=label,
        kind="ArtifactContract",
        properties={
            "pg_ref": f"artifact_contracts:{artifact_type}:v0",
            "artifact_type": artifact_type,
            "confidence_tier": "source_derived",
        },
    )


def _edge(source: str, target: str, label: str, artifact_type: str | None = None) -> GraphEdge:
    return GraphEdge(
        id=f"{source}:{label}:{target}:{artifact_type or 'edge'}",
        source=source,
        target=target,
        label=label,
        artifact_type=artifact_type,
        properties={
            "pg_ref": f"compatibility_edges:{_sha256_text(source + label + target + str(artifact_type))[:16]}",
            "confidence_tier": "source_derived",
        },
    )


def build_star_mvp_graph_index(star_root: str | Path | None = None) -> InMemoryGraphIndex:
    star_root = Path(star_root).expanduser().resolve() if star_root else _default_star_suite_root()
    index = InMemoryGraphIndex()

    for workflow_id in (
        "example_perturb_star_suite_production",
        "example_perturb_production_100k_smoke",
        "star_flex_fixed_rna",
    ):
        vertex = _workflow_source_vertex(star_root, workflow_id)
        index.upsert_vertex(vertex)

    for artifact_type, label in (
        ("star_solo_mex_dir", "STARsolo MEX directory"),
        ("h5ad", "AnnData h5ad"),
        ("qc_html", "QC HTML"),
        ("qc_png", "QC PNG"),
        ("crispr_calls_dir", "CRISPR calls directory"),
        ("crispr_summary_table", "CRISPR summary table"),
        ("feature_library_h5ad", "Feature library AnnData"),
        ("star_flex_smoke_output_dir", "STAR-Flex tiny smoke output"),
    ):
        index.upsert_vertex(_artifact_vertex(artifact_type, label))

    modules = [
        _module_vertex(
            "example_perturb_post_mex_h5ad_qc",
            "Example perturbation post-MEX h5ad QC artifacts",
            confidence="tested_local_recipe",
            evidence=[
                str(star_root / EXAMPLE_PERTURB_POST_MEX_SMOKE_REL / "downstream_genefull_velocyto_100k_starcells_featurelibs_v2"),
                str(star_root / "scripts/generate_qc_histogram_mt_adaptive.py"),
            ],
        ),
        _module_vertex(
            "example_perturb_post_mex_crispr_tables",
            "Example perturbation post-MEX CRISPR call tables",
            confidence="tested_local_recipe",
            evidence=[
                str(star_root / EXAMPLE_PERTURB_POST_MEX_SMOKE_REL / "run/outs/crispr_analysis"),
            ],
        ),
        _module_vertex(
            "example_perturb_post_mex_feature_library_h5ad",
            "Example perturbation post-MEX feature library h5ad integration",
            confidence="tested_local_recipe",
            evidence=[
                str(star_root / "scripts/integrate_feature_library.py"),
                str(star_root / EXAMPLE_PERTURB_POST_MEX_SMOKE_REL / "downstream_genefull_velocyto_100k_starcells_featurelibs_v2/feature_libraries"),
            ],
        ),
        _module_vertex(
            "star_flex_tiny_public_e2e",
            "STAR-Flex tiny public smoke",
            confidence="tested_local_recipe",
            evidence=[
                str(star_root / "tests/run_flex_tiny_public_binary_smoke.sh"),
                str(star_root / "mcp_server/workflows/star_flex_fixed_rna.yaml"),
            ],
        ),
    ]
    for module in modules:
        index.upsert_vertex(module)

    compatibility = [
        ("artifact:star_solo_mex_dir", "module:example_perturb_post_mex_h5ad_qc", "CONSUMED_BY", "star_solo_mex_dir"),
        ("module:example_perturb_post_mex_h5ad_qc", "artifact:h5ad", "PRODUCES", "h5ad"),
        ("module:example_perturb_post_mex_h5ad_qc", "artifact:qc_html", "PRODUCES", "qc_html"),
        ("module:example_perturb_post_mex_h5ad_qc", "artifact:qc_png", "PRODUCES", "qc_png"),
        ("artifact:crispr_calls_dir", "module:example_perturb_post_mex_crispr_tables", "CONSUMED_BY", "crispr_calls_dir"),
        ("module:example_perturb_post_mex_crispr_tables", "artifact:crispr_summary_table", "PRODUCES", "crispr_summary_table"),
        ("artifact:h5ad", "module:example_perturb_post_mex_feature_library_h5ad", "CONSUMED_BY", "h5ad"),
        ("artifact:crispr_summary_table", "module:example_perturb_post_mex_feature_library_h5ad", "CONSUMED_BY", "crispr_summary_table"),
        ("module:example_perturb_post_mex_feature_library_h5ad", "artifact:feature_library_h5ad", "PRODUCES", "feature_library_h5ad"),
        ("module:star_flex_tiny_public_e2e", "artifact:star_flex_smoke_output_dir", "PRODUCES", "star_flex_smoke_output_dir"),
    ]
    for source, target, label, artifact_type in compatibility:
        index.add_edge(_edge(source, target, label, artifact_type))

    for graph in _star_mvp_subgraphs(star_root, index.rebuild_graph_index()):
        index.add_subgraph(graph)
    return index


def _star_mvp_subgraphs(star_root: Path, projection_manifest: dict[str, Any]) -> list[RecipeGraph]:
    smoke_root = star_root / EXAMPLE_PERTURB_POST_MEX_SMOKE_REL
    downstream = smoke_root / "downstream_genefull_velocyto_100k_starcells_featurelibs_v2"
    crispr = smoke_root / "run" / "outs" / "crispr_analysis"
    feature_library = downstream / "feature_libraries" / "iPSC2_1_AALG2_CRISPR_Guide_Capture_1"

    post_mex_qc = RecipeGraph(
        graph_id="star_post_mex_h5ad_qc_v0",
        title="STAR post-MEX h5ad QC smoke",
        nodes=[
            {
                "id": "h5ad_qc",
                "kind": "module",
                "module_id": "example_perturb_post_mex_h5ad_qc",
                "label": "Verify h5ad, filtered h5ad, and QC plot artifacts",
                "confidence_tier": "tested_local_recipe",
            }
        ],
        edges=[],
        inputs=[
            {"name": "mex_dir", "artifact_type": "star_solo_mex_dir", "required": True},
            {"name": "downstream_dir", "artifact_type": "directory", "required": True},
        ],
        outputs=[
            {"name": "counts_h5ad", "artifact_type": "h5ad"},
            {"name": "filtered_counts_h5ad", "artifact_type": "h5ad"},
            {"name": "gene_quantile_histogram_html", "artifact_type": "qc_html"},
            {"name": "gene_quantile_histogram_png", "artifact_type": "qc_png"},
        ],
        capabilities=["post_mex", "qc", "h5ad", "example_perturb"],
        evidence=[
            {"kind": "smoke_artifact_root", "path": str(smoke_root)},
            {"kind": "workflow", "path": str(star_root / "mcp_server/workflows/example_perturb_star_suite_production.yaml")},
        ],
        lifecycle_state="published",
        confidence_tier="tested_local_recipe",
        planner_trace=[
            "Matched post-MEX QC request to existing Example perturbation perturb smoke artifacts.",
            "No STAR alignment or CellBender execution is required for this smoke.",
        ],
        projection=projection_manifest,
        execution={
            "mode": "verify_artifacts",
            "required_paths": [
                "mex_dir",
                "counts_h5ad",
                "filtered_counts_h5ad",
                "gene_quantile_histogram_html",
                "gene_quantile_histogram_png",
            ],
            "default_params": {
                "mex_dir": str(smoke_root / "run/outs/filtered_feature_bc_matrix"),
                "downstream_dir": str(downstream),
                "counts_h5ad": str(downstream / "counts.h5ad"),
                "filtered_counts_h5ad": str(downstream / "filtered_counts.h5ad"),
                "gene_quantile_histogram_html": str(downstream / "gene_quantile_histogram.html"),
                "gene_quantile_histogram_png": str(downstream / "gene_quantile_histogram.png"),
            },
        },
    )

    post_mex_feature = RecipeGraph(
        graph_id="star_post_mex_feature_library_crispr_v0",
        title="STAR post-MEX CRISPR and feature-library smoke",
        nodes=[
            {
                "id": "crispr_tables",
                "kind": "module",
                "module_id": "example_perturb_post_mex_crispr_tables",
                "label": "Verify CRISPR call tables",
                "confidence_tier": "tested_local_recipe",
            },
            {
                "id": "feature_library",
                "kind": "module",
                "module_id": "example_perturb_post_mex_feature_library_h5ad",
                "label": "Verify integrated feature-library h5ad artifacts",
                "confidence_tier": "tested_local_recipe",
            },
        ],
        edges=[
            {
                "source": "crispr_tables",
                "target": "feature_library",
                "edge_type": "produces_consumed_by",
                "artifact_type": "crispr_summary_table",
                "source_output": "protospacer_calls_summary",
                "target_input": "crispr_summary_table",
            }
        ],
        inputs=[
            {"name": "crispr_calls_dir", "artifact_type": "crispr_calls_dir", "required": True},
            {"name": "filtered_h5ad", "artifact_type": "h5ad", "required": True},
        ],
        outputs=[
            {"name": "protospacer_calls_summary", "artifact_type": "crispr_summary_table"},
            {"name": "protospacer_calls_per_cell", "artifact_type": "crispr_summary_table"},
            {"name": "filtered_feature_library_h5ad", "artifact_type": "feature_library_h5ad"},
            {"name": "feature_library_manifest", "artifact_type": "json"},
        ],
        capabilities=["post_mex", "crispr", "feature_library", "h5ad", "example_perturb"],
        evidence=[
            {"kind": "smoke_artifact_root", "path": str(smoke_root)},
            {"kind": "helper", "path": str(star_root / "scripts/integrate_feature_library.py")},
        ],
        lifecycle_state="published",
        confidence_tier="tested_local_recipe",
        planner_trace=[
            "Matched post-MEX CRISPR/feature-library request to existing Example perturbation perturb smoke artifacts.",
            "Execution verifies local artifacts and writes a verification manifest.",
        ],
        projection=projection_manifest,
        execution={
            "mode": "verify_artifacts",
            "required_paths": [
                "crispr_calls_dir",
                "filtered_h5ad",
                "protospacer_calls_summary",
                "protospacer_calls_per_cell",
                "filtered_feature_library_h5ad",
                "feature_library_manifest",
            ],
            "default_params": {
                "crispr_calls_dir": str(crispr),
                "filtered_h5ad": str(downstream / "filtered_counts.h5ad"),
                "protospacer_calls_summary": str(crispr / "protospacer_calls_summary.csv"),
                "protospacer_calls_per_cell": str(crispr / "protospacer_calls_per_cell.csv"),
                "filtered_feature_library_h5ad": str(feature_library / "filtered_feature_library.h5ad"),
                "feature_library_manifest": str(feature_library / "manifest.json"),
            },
        },
    )

    flex_e2e = RecipeGraph(
        graph_id="star_flex_tiny_public_e2e_v0",
        title="STAR-Flex tiny public e2e smoke",
        nodes=[
            {
                "id": "flex_tiny",
                "kind": "module",
                "module_id": "star_flex_tiny_public_e2e",
                "label": "Run STAR-Flex tiny public smoke",
                "confidence_tier": "tested_local_recipe",
            }
        ],
        edges=[],
        inputs=[{"name": "public_10x_tiny_fixture", "artifact_type": "public_fixture", "required": False}],
        outputs=[{"name": "outdir", "artifact_type": "star_flex_smoke_output_dir"}],
        capabilities=["star_flex", "e2e", "tiny_smoke"],
        evidence=[
            {"kind": "smoke_script", "path": str(star_root / "tests/run_flex_tiny_public_binary_smoke.sh")},
            {"kind": "workflow", "path": str(star_root / "mcp_server/workflows/star_flex_fixed_rna.yaml")},
        ],
        lifecycle_state="candidate",
        confidence_tier="tested_local_recipe",
        planner_trace=[
            "Selected the public tiny STAR-Flex smoke as the cheap e2e path.",
            "This path is opt-in for automated tests because it invokes STAR and fixture fetch tooling.",
        ],
        projection=projection_manifest,
        execution={
            "mode": "external_script",
            "script": str(star_root / "tests/run_flex_tiny_public_binary_smoke.sh"),
            "default_params": {
                "threads": 2,
                "read_limit": 200,
                "out_samtype": "none",
                "outdir": "",
            },
        },
    )

    return [post_mex_qc, post_mex_feature, flex_e2e]


def plan_star_mvp_composition(
    goal: str,
    *,
    star_root: str | Path | None = None,
    graph_index: InMemoryGraphIndex | None = None,
) -> RecipeGraph:
    index = graph_index or build_star_mvp_graph_index(star_root)
    text = goal.lower()
    if "flex" in text or "e2e" in text or "downsample" in text:
        return index.hydrate_graph("star_flex_tiny_public_e2e_v0")
    if "feature" in text or "crispr" in text or "guide" in text:
        return index.hydrate_graph("star_post_mex_feature_library_crispr_v0")
    candidates = index.find_candidate_paths(
        ["star_solo_mex_dir"],
        ["h5ad", "qc_html", "qc_png"],
        {"capabilities": ["post_mex"]},
    )
    if not candidates:
        raise ValueError("No STAR MVP post-MEX composition matched the request")
    return candidates[0]


def _params_schema_for_graph(graph: RecipeGraph) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    defaults = graph.execution.get("default_params") if isinstance(graph.execution.get("default_params"), dict) else {}
    seen: set[str] = set()
    for item in [*graph.inputs, *graph.outputs]:
        name = str(item.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        fields.append(
            {
                "name": name,
                "type": "path",
                "artifact_type": item.get("artifact_type"),
                "required": bool(item.get("required", True)),
                "default": defaults.get(name),
            }
        )
    if graph.execution.get("mode") == "external_script":
        for name, value, typ in (
            ("threads", defaults.get("threads", 2), "integer"),
            ("read_limit", defaults.get("read_limit", 200), "integer"),
            ("out_samtype", defaults.get("out_samtype", "none"), "enum"),
            ("outdir", defaults.get("outdir", ""), "path"),
        ):
            field = {"name": name, "type": typ, "required": name == "outdir", "default": value}
            if name == "out_samtype":
                field["enum"] = ["none", "bam-unsorted"]
                field["description"] = "STAR --outSAMtype mode for the tiny Flex smoke. Use none for the cheap no-BAM path."
            fields.append(field)
    return {
        "schema": "morphic.graph_params_schema/v0",
        "graph_id": graph.graph_id,
        "fields": fields,
        "required": [field["name"] for field in fields if field.get("required")],
    }


def _verify_helper_source() -> str:
    return textwrap.dedent(
        r'''
        #!/usr/bin/env python3
        import argparse
        import hashlib
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        def sha256_json(payload):
            text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        parser = argparse.ArgumentParser()
        parser.add_argument("--graph", required=True)
        parser.add_argument("--params", required=True)
        parser.add_argument("--out", required=True)
        args = parser.parse_args()

        graph = json.loads(Path(args.graph).read_text())
        params = json.loads(Path(args.params).read_text())["params"]
        required = graph.get("execution", {}).get("required_paths", [])
        checks = []
        ok = True
        for key in required:
            raw = params.get(key)
            path = Path(str(raw or ""))
            exists = path.exists()
            size = path.stat().st_size if exists and path.is_file() else None
            checks.append({"name": key, "path": str(path), "exists": exists, "size_bytes": size})
            ok = ok and exists

        result = {
            "schema": "morphic.local_execution_result/v0",
            "status": "verified" if ok else "failed",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "graph_id": graph["graph_id"],
            "canonical_graph_hash": graph["canonical_graph_hash"],
            "output_contract_checks": checks,
            "verified_recipe": ok,
        }
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        raise SystemExit(0 if ok else 2)
        '''
    ).lstrip()


def _render_verify_run_sh() -> str:
    return textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        BUNDLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
        python3 "$BUNDLE_DIR/helpers/verify_artifacts.py" \\
          --graph "$BUNDLE_DIR/workflow_graph.json" \\
          --params "$BUNDLE_DIR/params.review.json" \\
          --out "$BUNDLE_DIR/execution_result.json"
        """
    )


def _render_external_script_run_sh(graph: RecipeGraph) -> str:
    script = graph.execution.get("script")
    if not script:
        raise ValueError("external_script graph is missing execution.script")
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        BUNDLE_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
        PARAMS="$BUNDLE_DIR/params.review.json"
        THREADS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["params"].get("threads", 2))' "$PARAMS")"
        READ_LIMIT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["params"].get("read_limit", 200))' "$PARAMS")"
        OUT_SAMTYPE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["params"].get("out_samtype", "none"))' "$PARAMS")"
        OUTDIR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["params"].get("outdir", ""))' "$PARAMS")"
        if [[ -z "$OUTDIR" ]]; then
          OUTDIR="$BUNDLE_DIR/flex_tiny_output"
        fi
        bash {json.dumps(str(script))} --threads "$THREADS" --read-limit "$READ_LIMIT" --out-samtype "$OUT_SAMTYPE" --outdir "$OUTDIR"
        python3 - "$BUNDLE_DIR/workflow_graph.json" "$BUNDLE_DIR/execution_result.json" "$OUTDIR" <<'PY'
        import json, sys
        from datetime import datetime, timezone
        graph = json.load(open(sys.argv[1]))
        out = sys.argv[3]
        result = {{
          "schema": "morphic.local_execution_result/v0",
          "status": "verified",
          "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
          "graph_id": graph["graph_id"],
          "canonical_graph_hash": graph["canonical_graph_hash"],
          "output_root": out,
          "verified_recipe": True,
        }}
        json.dump(result, open(sys.argv[2], "w"), indent=2, sort_keys=True)
        open(sys.argv[2], "a").write("\\n")
        PY
        """
    )


def materialize_star_mvp_bundle(
    graph: RecipeGraph,
    out_root: str | Path,
    *,
    params: dict[str, Any] | None = None,
) -> Path:
    out_root = Path(out_root)
    bundle = out_root / _safe_graph_id(graph.graph_id)
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "helpers").mkdir(parents=True)
    (bundle / "manifests").mkdir(parents=True)

    defaults = graph.execution.get("default_params") if isinstance(graph.execution.get("default_params"), dict) else {}
    merged_params = {**defaults, **(params or {})}
    graph_payload = graph.as_dict()

    (bundle / "workflow_graph.json").write_text(json.dumps(graph_payload, indent=2, sort_keys=True) + "\n")
    (bundle / "recipe.json").write_text(
        json.dumps(
            {
                "schema": "morphic.materialized_recipe/v0",
                "graph_id": graph.graph_id,
                "title": graph.title,
                "lifecycle_state": graph.lifecycle_state,
                "canonical_graph_hash": graph_payload["canonical_graph_hash"],
                "nodes": graph.nodes,
                "edges": graph.edges,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (bundle / "params.schema.json").write_text(json.dumps(_params_schema_for_graph(graph), indent=2, sort_keys=True) + "\n")
    (bundle / "params.review.json").write_text(json.dumps({"params": merged_params}, indent=2, sort_keys=True) + "\n")
    (bundle / "manifests" / "projection_manifest.json").write_text(
        json.dumps(graph.projection, indent=2, sort_keys=True) + "\n"
    )

    if graph.execution.get("mode") == "external_script":
        run_sh = _render_external_script_run_sh(graph)
    else:
        helper = bundle / "helpers" / "verify_artifacts.py"
        helper.write_text(_verify_helper_source())
        helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
        run_sh = _render_verify_run_sh()

    (bundle / "run.sh").write_text(run_sh)
    (bundle / "run.sh").chmod(0o755)
    (bundle / "README.md").write_text(
        "\n".join(
            [
                f"# {graph.title}",
                "",
                "Generated by the STAR graph MVP planner.",
                "",
                "Flow:",
                "1. Review workflow_graph.json and params.review.json.",
                "2. Run ./run.sh locally.",
                "3. Inspect execution_result.json.",
                "",
                "The default post-MEX smoke bundles verify existing STAR-suite smoke artifacts.",
                "The Flex tiny e2e bundle invokes the STAR-suite smoke script and is opt-in for automated tests.",
                "",
            ]
        )
    )
    return bundle


def run_materialized_bundle(bundle: str | Path, *, timeout: int = 120) -> dict[str, Any]:
    bundle = Path(bundle)
    subprocess.run(["bash", str(bundle / "run.sh")], cwd=str(bundle), check=True, timeout=timeout)
    result_path = bundle / "execution_result.json"
    return json.loads(result_path.read_text(encoding="utf-8"))
