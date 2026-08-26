"""Workflow graph drafts derived from module contracts — not workbench route handlers."""

from __future__ import annotations

import copy
from typing import Any

from morphic_agent.graph.params import bulk_deseq_params_schema, trimodal_qc_params_schema, example_perturb_visualization_params_schema
from morphic_agent.registry.catalog import ModuleCatalog


def _graph_evidence(modules: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for module in modules.values():
        for item in module.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("kind") or ""), str(item.get("path") or ""))
            if key in seen:
                continue
            seen.add(key)
            evidence.append(copy.deepcopy(item))
    return evidence


def build_bulk_deseq_graph(catalog: ModuleCatalog, *, include_plots: bool = False) -> dict[str, Any]:
    graph_id = "bulk_pe_deseq2_plots_v0" if include_plots else "bulk_pe_deseq2_v0"
    modules = catalog.modules_by_id(["star_bulk_pe_counts", "deseq2_differential_expression"])
    nodes = [
        {
            "id": "align",
            "kind": "module",
            "module_id": "star_bulk_pe_counts",
            "label": "STAR bulk PE counts",
            "confidence_tier": modules.get("star_bulk_pe_counts", {}).get("confidence_tier", "curated_profile"),
        },
        {
            "id": "de",
            "kind": "module",
            "module_id": "deseq2_differential_expression",
            "label": "DESeq2 differential expression",
            "confidence_tier": modules.get("deseq2_differential_expression", {}).get("confidence_tier", "source_derived"),
        },
    ]
    edges = [
        {
            "source": "align",
            "target": "de",
            "edge_type": "produces_consumed_by",
            "source_output": "counts",
            "target_input": "counts",
            "artifact_type": "gene_count_matrix",
            "contract": {"sample_ids_must_match": "coldata rows and count columns", "preflight_required": True},
        }
    ]
    if include_plots:
        plot_modules = catalog.modules_by_id(["volcano_plot", "heatmap_plot"])
        modules.update(plot_modules)
        nodes.extend(
            [
                {
                    "id": "volcano",
                    "kind": "module",
                    "module_id": "volcano_plot",
                    "label": "Volcano plot",
                    "confidence_tier": plot_modules.get("volcano_plot", {}).get("confidence_tier", "source_derived"),
                },
                {
                    "id": "heatmap",
                    "kind": "module",
                    "module_id": "heatmap_plot",
                    "label": "Heatmap plot",
                    "confidence_tier": plot_modules.get("heatmap_plot", {}).get("confidence_tier", "source_derived"),
                },
            ]
        )
        edges.extend(
            [
                {
                    "source": "de",
                    "target": "volcano",
                    "edge_type": "visualizes",
                    "source_output": "results_table",
                    "target_input": "differential_expression_table",
                    "artifact_type": "differential_expression_table",
                },
                {
                    "source": "de",
                    "target": "heatmap",
                    "edge_type": "visualizes",
                    "source_output": "normalized_counts",
                    "target_input": "expression_matrix",
                    "artifact_type": "gene_count_matrix",
                },
            ]
        )
    params_schema = bulk_deseq_params_schema(graph_id)
    run_blocker = None
    if include_plots:
        run_blocker = (
            "Volcano and heatmap modules are included in the graph draft; "
            "plot helpers are not materialized until a visualization renderer is registered."
        )
    inputs = [
        {"name": "reads", "artifact_type": "paired_fastq", "required": True},
        {"name": "genome_dir", "artifact_type": "star_genome_dir", "required": True},
        {"name": "genome_fasta", "artifact_type": "fasta", "required": True},
        {"name": "gtf", "artifact_type": "gtf", "required": True},
        {"name": "coldata", "artifact_type": "sample_metadata_table", "required": True},
    ]
    outputs = [
        {"name": "counts", "artifact_type": "gene_count_matrix"},
        {"name": "deseq2_results", "artifact_type": "differential_expression_table"},
    ]
    capabilities = ["bulk_rna_seq", "differential_expression", "deg"]
    if include_plots:
        outputs.extend(
            [
                {"name": "volcano_png", "artifact_type": "png"},
                {"name": "volcano_html", "artifact_type": "plotly_html"},
                {"name": "heatmap_png", "artifact_type": "png"},
            ]
        )
        capabilities.extend(["visualization", "volcano_plot", "heatmap"])
    return {
        "schema": "morphic.workflow_graph/v0",
        "graph_id": graph_id,
        "title": "Bulk paired-end RNA-seq with DESeq2" + (" and plots" if include_plots else ""),
        "description": "Compose STAR bulk paired-end count generation with DESeq2 differential expression.",
        "nodes": nodes,
        "edges": edges,
        "inputs": inputs,
        "outputs": outputs,
        "capabilities": capabilities,
        "required_human_inputs": params_schema["required"],
        "params_schema": params_schema,
        "confidence_tier": "curated_profile",
        "materialization_status": "graph_draft_only" if include_plots else "runnable_bundle",
        "run_blocker": run_blocker,
        "evidence": _graph_evidence(modules),
    }


def build_trimodal_qc_graph(catalog: ModuleCatalog) -> dict[str, Any]:
    graph_id = "trimodal_qc_report_v0"
    modules = catalog.modules_by_id(["trimodal_qc_report"])
    params_schema = trimodal_qc_params_schema(graph_id)
    return {
        "schema": "morphic.workflow_graph/v0",
        "graph_id": graph_id,
        "title": "Trimodal MuData QC report",
        "description": "Render the existing demo MuData QC smoke surface as a reviewable script bundle.",
        "nodes": [
            {
                "id": "qc",
                "kind": "module",
                "module_id": "trimodal_qc_report",
                "label": "Trimodal MuData QC report",
                "confidence_tier": modules.get("trimodal_qc_report", {}).get("confidence_tier", "tested_local_recipe"),
            }
        ],
        "edges": [],
        "inputs": [{"name": "mudata", "artifact_type": "h5mu", "required": True}],
        "outputs": [
            {"name": "qc_report", "artifact_type": "qc_report"},
            {"name": "qc_report_html", "artifact_type": "html"},
            {"name": "qc_report_json", "artifact_type": "json"},
        ],
        "capabilities": ["qc", "mudata", "trimodal"],
        "required_human_inputs": params_schema["required"],
        "params_schema": params_schema,
        "confidence_tier": "tested_local_recipe",
        "materialization_status": "runnable_bundle",
        "run_blocker": None,
        "evidence": _graph_evidence(modules),
    }


def build_example_perturb_visualization_graph(catalog: ModuleCatalog) -> dict[str, Any]:
    graph_id = "example_perturb_visualization_suite_v0"
    module_ids = [
        "example_perturb_star_suite_production",
        "example_perturb_downstream_h5ad_cellbender",
        "example_perturb_technical_qc_report",
        "example_perturb_embedding_clustering_plots",
        "example_perturb_perturbation_qc_plots",
        "example_perturb_pseudobulk_deseq2",
        "example_perturb_de_visualization_suite",
        "example_perturb_cell_composition_dynamics",
        "example_perturb_target_correlation_heatmap",
        "example_perturb_pathway_enrichment_report",
    ]
    modules = catalog.modules_by_id(module_ids)
    params_schema = example_perturb_visualization_params_schema(graph_id)

    def node(node_id: str, module_id: str, label: str) -> dict[str, Any]:
        return {
            "id": node_id,
            "kind": "module",
            "module_id": module_id,
            "label": label,
            "confidence_tier": modules.get(module_id, {}).get("confidence_tier", "source_derived"),
        }

    nodes = [
        node("production", "example_perturb_star_suite_production", "Example perturbation STAR-suite production wrapper"),
        node("downstream", "example_perturb_downstream_h5ad_cellbender", "Downstream h5ad + CellBender integration"),
        node("technical_qc", "example_perturb_technical_qc_report", "Technical QC report"),
        node("embedding_clustering", "example_perturb_embedding_clustering_plots", "Embedding and clustering plots"),
        node("perturb_qc", "example_perturb_perturbation_qc_plots", "Perturbation QC plots"),
        node("pseudobulk_de", "example_perturb_pseudobulk_deseq2", "Pseudobulk DESeq2"),
        node("de_visualization", "example_perturb_de_visualization_suite", "DE visualization suite"),
        node("composition_dynamics", "example_perturb_cell_composition_dynamics", "Cell composition and dynamics plots"),
        node("target_correlation", "example_perturb_target_correlation_heatmap", "Target correlation heatmap"),
        node("pathway_enrichment", "example_perturb_pathway_enrichment_report", "Pathway enrichment report"),
    ]
    edges = [
        {"source": "production", "target": "downstream", "edge_type": "produces_consumed_by", "source_output": "star_solo_outputs", "target_input": "star_solo_outputs", "artifact_type": "star_solo_output_dir"},
        {"source": "downstream", "target": "technical_qc", "edge_type": "produces_consumed_by", "source_output": "qc_report", "target_input": "qc_report", "artifact_type": "qc_report"},
        {"source": "downstream", "target": "embedding_clustering", "edge_type": "produces_consumed_by", "source_output": "h5ad", "target_input": "h5ad", "artifact_type": "h5ad"},
        {"source": "downstream", "target": "perturb_qc", "edge_type": "produces_consumed_by", "source_output": "h5ad", "target_input": "h5ad", "artifact_type": "h5ad"},
        {"source": "production", "target": "perturb_qc", "edge_type": "produces_consumed_by", "source_output": "crispr_calls_dir", "target_input": "crispr_calls_dir", "artifact_type": "crispr_calls_dir"},
        {"source": "downstream", "target": "pseudobulk_de", "edge_type": "produces_consumed_by", "source_output": "h5ad", "target_input": "h5ad", "artifact_type": "h5ad"},
        {"source": "pseudobulk_de", "target": "de_visualization", "edge_type": "produces_consumed_by", "source_output": "differential_expression_table", "target_input": "differential_expression_table", "artifact_type": "differential_expression_table"},
        {"source": "embedding_clustering", "target": "composition_dynamics", "edge_type": "produces_consumed_by", "source_output": "clustered_object", "target_input": "clustered_object", "artifact_type": "single_cell_object"},
        {"source": "perturb_qc", "target": "target_correlation", "edge_type": "produces_consumed_by", "source_output": "target_effect_table", "target_input": "target_effect_table", "artifact_type": "target_effect_table"},
        {"source": "pseudobulk_de", "target": "target_correlation", "edge_type": "produces_consumed_by", "source_output": "differential_expression_table", "target_input": "differential_expression_table", "artifact_type": "differential_expression_table"},
        {"source": "pseudobulk_de", "target": "pathway_enrichment", "edge_type": "produces_consumed_by", "source_output": "ranked_gene_lists", "target_input": "ranked_gene_lists", "artifact_type": "gene_list"},
    ]
    return {
        "schema": "morphic.workflow_graph/v0",
        "graph_id": graph_id,
        "title": "Example perturbation perturb-seq visualization suite",
        "description": "Draft graph for Example perturbation perturb-seq visualization over STAR production and downstream artifacts.",
        "nodes": nodes,
        "edges": edges,
        "inputs": [
            {"name": "release_root", "artifact_type": "star_perturb_release_dir", "required": True},
            {"name": "filtered_h5ad", "artifact_type": "h5ad", "required": True},
            {"name": "crispr_calls_dir", "artifact_type": "crispr_calls_dir", "required": True},
            {"name": "sample_metadata", "artifact_type": "sample_metadata_table", "required": True},
        ],
        "outputs": [
            {"name": "technical_qc", "artifact_type": "qc_report"},
            {"name": "embedding_plots", "artifact_type": "plotly_html"},
            {"name": "differential_expression", "artifact_type": "differential_expression_table"},
            {"name": "volcano_heatmap_outputs", "artifact_type": "png"},
        ],
        "capabilities": ["example_perturb", "perturb_seq", "visualization", "differential_expression", "qc", "embedding"],
        "required_human_inputs": params_schema["required"],
        "params_schema": params_schema,
        "confidence_tier": "mixed_recipe_and_source_derived",
        "materialization_status": "graph_draft_only",
        "run_blocker": (
            "Example perturbation STAR production is recipe-backed, but the graph-to-bundle renderer for the visualization "
            "suite is not connected; visualization modules are currently derived from runbooks and plot contracts."
        ),
        "source_classification": {
            "production_workflow": {
                "workflow_id": "example_perturb_star_suite_production",
                "workflow_kind": "shell_workflow",
                "recipe_shape": "single_top_level_workflow",
                "entry_script": "scripts/paper/run_example_perturb_corrected_production_workflow.sh",
            },
            "visualization_layer": {
                "recipe_shape": "runbook_and_plot_contract_family",
                "launchpad_workflow_status": "not_split_into_individual_visualization_recipes",
                "confidence_tier": "source_derived_until_materializers_are_registered",
            },
        },
        "evidence": _graph_evidence(modules),
    }


_GRAPH_CACHE: dict[str, dict[str, Any]] = {}


def get_workflow_graph(graph_id: str, catalog: ModuleCatalog | None = None) -> dict[str, Any] | None:
    catalog = catalog or ModuleCatalog()
    if graph_id in _GRAPH_CACHE:
        return copy.deepcopy(_GRAPH_CACHE[graph_id])
    if graph_id == "bulk_pe_deseq2_v0":
        return build_bulk_deseq_graph(catalog, include_plots=False)
    if graph_id == "bulk_pe_deseq2_plots_v0":
        return build_bulk_deseq_graph(catalog, include_plots=True)
    if graph_id == "trimodal_qc_report_v0":
        return build_trimodal_qc_graph(catalog)
    if graph_id == "example_perturb_visualization_suite_v0":
        return build_example_perturb_visualization_graph(catalog)
    return None


def cache_workflow_graph(graph: dict[str, Any]) -> None:
    _GRAPH_CACHE[str(graph["graph_id"])] = copy.deepcopy(graph)


def _requests_example_perturb_visualization(text: str) -> bool:
    lowered = text.lower()
    return (
        any(term in lowered for term in ("example_perturb", "perturb", "crispr", "guide"))
        and any(term in lowered for term in ("visualization", "visualisation", "plot", "plots", "qc", "smoke", "release", "volcano", "heatmap"))
    )


def _requests_differential_expression(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ("deseq", "differential expression", "deg", "degs")) or "deg analysis" in lowered


def graph_intent_supported(goal: str) -> bool:
    text = goal.lower()
    return (
        _requests_example_perturb_visualization(text)
        or _requests_differential_expression(text)
        or ("qc" in text and any(term in text for term in ("mudata", "h5mu", "trimodal")))
    )


def draft_workflow_graph(goal: str, catalog: ModuleCatalog | None = None, *, include_launchpad: bool = True) -> dict[str, Any]:
    catalog = catalog or ModuleCatalog()
    text = goal.lower()
    if "qc" in text and any(term in text for term in ("mudata", "h5mu", "trimodal")):
        graph = build_trimodal_qc_graph(catalog)
    elif _requests_example_perturb_visualization(text):
        graph = build_example_perturb_visualization_graph(catalog)
    else:
        include_plots = any(term in text for term in ("volcano", "heatmap", "plot", "plots", "visualization", "visualisation"))
        graph = build_bulk_deseq_graph(catalog, include_plots=include_plots)
    cache_workflow_graph(graph)
    return graph


def graph_draft_message(graph: dict[str, Any]) -> str:
    nodes = ", ".join(str(node.get("label") or node.get("module_id")) for node in graph.get("nodes") or [])
    graph_id = str(graph.get("graph_id") or "")
    if graph_id == "trimodal_qc_report_v0":
        return (
            f"Created Review Plan: {graph.get('title') or 'Trimodal MuData QC report'} "
            f"(`{graph_id}`) with {len(graph.get('nodes') or [])} module: {nodes}. "
            "It uses the existing trimodal MuData demo artifact. "
            "Next, review the plan, then open Fill + Approve to check `mudata`, `output_prefix`, and `title`."
        )
    if graph_id == "example_perturb_visualization_suite_v0":
        return (
            f"Created Review Plan: {graph.get('title') or graph_id} (`{graph_id}`) "
            f"with {len(graph.get('nodes') or [])} module(s): {nodes}. "
            "This represents the Example perturbation perturb-seq visualization suite from existing smoke artifacts "
            "and source-derived module contracts. Review blockers before expecting a runnable bundle."
        )
    return (
        f"Created Review Plan: {graph.get('title') or graph_id} (`{graph_id}`) "
        f"with {len(graph.get('nodes') or [])} module(s): {nodes}. "
        "This is the MVP DEG composability path: STAR produces a gene count matrix, "
        "DESeq2 consumes counts plus coldata/design, and downstream plots require a DE results table. "
        "Review the graph, parameters, and blockers before approving bundle generation."
    )
