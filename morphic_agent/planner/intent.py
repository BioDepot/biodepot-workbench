"""Intent normalization extracted from prototype invariants — not route handlers."""

from __future__ import annotations

import re
from typing import Any

from morphic_agent.registry.catalog import ModuleCatalog

DIFFERENTIAL_EXPRESSION_TERMS = (
    "differential expression",
    "differentially expressed",
    "deseq",
    "deseq2",
    "deg analysis",
)

DOWNSTREAM_CATALOG_TERMS = (
    "downstream assays",
    "downstream modules",
    "what can i run after",
    "what downstream",
    "list downstream",
)

ASSAY_TERMS = (
    "assay",
    "assays",
    "data type",
    "data types",
    "experiment type",
    "experiment types",
    "workflow type",
    "workflow types",
)

VISUALIZATION_TERMS = (
    "visualization",
    "visualizations",
    "visualisation",
    "visualisations",
    "plot",
    "plots",
    "plotting",
    "figure",
    "figures",
    "graphics",
)

CATALOG_QUESTION_TERMS = (
    "what",
    "which",
    "list",
    "available",
    "other",
    "options",
    "can i make",
    "can we make",
    "can i run",
    "can we run",
    "show",
)

EXPLAIN_PLAN_TERMS = (
    "what are you composing",
    "what are we composing",
    "what is the current plan",
    "what workflow are you composing",
    "what are you building",
)


def conversation_goal_text(goal: str, session_context: dict[str, Any]) -> str:
    prior_goals = [
        str(turn.get("goal") or "")
        for turn in session_context.get("recent_turns", [])
        if isinstance(turn, dict) and str(turn.get("goal") or "").strip()
    ]
    return "\n".join([*prior_goals[-5:], goal])


def requests_differential_expression(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in DIFFERENTIAL_EXPRESSION_TERMS) or bool(re.search(r"\bdegs?\b", lowered))


def differential_expression_interpretation(text: str) -> str | None:
    if re.search(r"\bdegs?\b", text.lower()):
        return "I interpreted `DEG/DEGs` as differentially expressed genes, so I treated this as a differential-expression request."
    return None


def requests_volcano_plot(text: str) -> bool:
    return "volcano" in text.lower().replace("_", " ")


def requests_explain_plan(text: str) -> bool:
    lowered = text.lower().strip().rstrip("?")
    return any(term in lowered for term in EXPLAIN_PLAN_TERMS)


def requests_downstream_catalog(text: str) -> bool:
    lowered = text.lower()
    if any(term in lowered for term in DOWNSTREAM_CATALOG_TERMS):
        return True
    return "downstream" in lowered and any(term in lowered for term in ("available", "list", "what", "which", "can i run", "can we run"))


def requests_assay_catalog(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ASSAY_TERMS) and any(
        term in lowered for term in CATALOG_QUESTION_TERMS
    )


def requests_visualization_catalog(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in VISUALIZATION_TERMS) and any(
        term in lowered for term in CATALOG_QUESTION_TERMS
    )


def module_matches_for_request(text: str, catalog: ModuleCatalog) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if requests_differential_expression(text):
        matches.append(
            {
                "module_id": "deseq2_differential_expression",
                "capability": "differential_expression",
                "interpretation": differential_expression_interpretation(text),
            }
        )
    if requests_volcano_plot(text):
        matches.append({"module_id": "volcano_plot", "capability": "volcano_plot"})
    if not matches:
        for module in catalog.list_modules(query=text):
            if module["module_id"] in {item["module_id"] for item in matches}:
                continue
            matches.append({"module_id": module["module_id"], "capability": "catalog_match"})
    return matches


def downstream_catalog_modules(catalog: ModuleCatalog) -> list[dict[str, Any]]:
    preferred = [
        "deseq2_differential_expression",
        "volcano_plot",
        "heatmap_plot",
        "mex_to_anndata",
        "mex_to_mudata",
        "cellbender_remove_background",
        "doublet_removal",
        "scanpy_pca_neighbors_leiden",
    ]
    modules = catalog.modules_by_id(preferred)
    return [catalog.summarize(modules[mid]) for mid in preferred if mid in modules]


def visualization_catalog_modules(catalog: ModuleCatalog) -> list[dict[str, Any]]:
    preferred = [
        "volcano_plot",
        "heatmap_plot",
        "embedding_scatter_plot",
        "plotly_report",
        "trimodal_qc_report",
        "example_perturb_technical_qc_report",
        "example_perturb_embedding_clustering_plots",
        "example_perturb_perturbation_qc_plots",
        "example_perturb_de_visualization_suite",
        "example_perturb_cell_composition_dynamics",
        "example_perturb_target_correlation_heatmap",
        "example_perturb_pathway_enrichment_report",
        "png_export",
    ]
    modules = {module["module_id"]: module for module in catalog.list_modules() if module.get("module_id")}
    visual_modules = {
        module["module_id"]: module
        for module in modules.values()
        if "visualization" in {str(capability).lower() for capability in module.get("capabilities") or []}
        or any(
            artifact_type in {"png", "plotly_html", "qc_report"}
            for artifact_type in module.get("output_artifact_types") or []
        )
    }
    ordered = [visual_modules.pop(module_id) for module_id in preferred if module_id in visual_modules]
    ordered.extend(sorted(visual_modules.values(), key=lambda module: str(module.get("module_id") or "")))
    return ordered


def assay_catalog_modules(catalog: ModuleCatalog) -> list[dict[str, Any]]:
    preferred = [
        "star_bulk_pe_counts",
        "deseq2_differential_expression",
        "mex_to_anndata",
        "mex_to_mudata",
        "cellbender_remove_background",
        "doublet_removal",
        "scanpy_pca_neighbors_leiden",
        "trimodal_qc_report",
        "example_perturb_star_suite_production",
        "example_perturb_downstream_h5ad_cellbender",
        "example_perturb_pseudobulk_deseq2",
    ]
    modules = {module["module_id"]: module for module in catalog.list_modules() if module.get("module_id")}
    ordered = [modules.pop(module_id) for module_id in preferred if module_id in modules]
    ordered.extend(sorted(modules.values(), key=lambda module: str(module.get("module_id") or "")))
    return ordered


def planning_state_for_rnaseq(goal: str, session_context: dict[str, Any]) -> dict[str, Any] | None:
    combined = conversation_goal_text(goal, session_context).lower()
    if not any(
        term in combined
        for term in (
            "rna-seq",
            "rnaseq",
            "rna seq",
            "bulk",
            "single cell",
            "single-cell",
            "scrna",
            "fastq",
            "starsolo",
        )
    ):
        return None

    facts: dict[str, Any] = {}
    pending_downstream: list[dict[str, Any]] = []
    next_question = ""

    if re.search(r"\bbulk\b", combined):
        facts["assay_type"] = "bulk"
    elif any(term in combined for term in ("single cell", "single-cell", "scrna", "starsolo", "10x")):
        facts["assay_type"] = "single_cell"

    if re.search(r"\b(pe|paired[- ]end|paired end)\b", combined):
        facts["read_layout"] = "paired_end"
    elif re.search(r"\b(se|single[- ]end|single end)\b", combined):
        facts["read_layout"] = "single_end"

    if facts.get("assay_type") == "bulk" and re.search(r"paired[- ]end", combined):
        facts["read_layout"] = "paired_end"

    if re.search(r"\bno[- ]bam\b", combined) or "counts only" in combined:
        facts["bam_output"] = "not_required"
    elif re.search(r"\bbam\b", combined):
        facts["bam_output"] = "required"

    if requests_differential_expression(combined):
        pending_downstream.append(
            {
                "capability": "differential_expression",
                "preferred_module": "deseq2_differential_expression",
                "term": "DEGs" if re.search(r"\bdegs?\b", combined) else "differential expression",
            }
        )
    if requests_volcano_plot(combined):
        pending_downstream.append(
            {
                "capability": "volcano_plot",
                "preferred_module": "volcano_plot",
                "term": "volcano plot",
            }
        )

    ready_to_compose = False
    if not facts.get("assay_type"):
        next_question = "Is this bulk RNA-seq or single-cell/single-nucleus data?"
    elif facts.get("assay_type") == "bulk" and not facts.get("read_layout"):
        next_question = "Is the bulk RNA-seq paired-end or single-end?"
    elif (
        facts.get("assay_type") == "bulk"
        and facts.get("read_layout") == "paired_end"
        and not facts.get("bam_output")
        and not (requests_differential_expression(combined) or "deseq" in combined)
    ):
        next_question = "Do you need sorted BAM output, or counts only?"
    else:
        ready_to_compose = bool(
            requests_differential_expression(combined)
            or "deseq" in combined
            or re.search(r"\bdeg\b", combined)
            or (facts.get("assay_type") == "bulk" and facts.get("read_layout") == "paired_end" and "rna" in combined)
        )

    status_message = ""
    if pending_downstream and not ready_to_compose:
        bits = []
        if any(item["capability"] == "differential_expression" for item in pending_downstream):
            bits.append(
                "I noted the DEG/differential-expression request and will keep it pending while we finish the base RNA-seq choices."
            )
        if any(item["capability"] == "volcano_plot" for item in pending_downstream):
            bits.append(
                "I also noted the volcano-plot request. That will need a differential-expression result table before plotting."
            )
        status_message = " ".join(bits)

    return {
        "facts": facts,
        "pending_downstream_requests": pending_downstream,
        "next_question": next_question,
        "status_message": status_message,
        "ready_to_compose": ready_to_compose,
        "workflow_id": "star_bulk_pe_batch" if ready_to_compose and facts.get("assay_type") == "bulk" else None,
    }
