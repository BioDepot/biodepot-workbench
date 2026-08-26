"""Graph-level parameter schemas and validation."""

from __future__ import annotations

from typing import Any

from morphic_agent.content.paths import star_plot_contracts_dir


def bulk_deseq_params_schema(graph_id: str) -> dict[str, Any]:
    fields = [
        {
            "name": "reads",
            "label": "Paired FASTQ reads",
            "type": "array",
            "artifact_type": "paired_fastq",
            "required": True,
            "consumed_by": ["align"],
            "template": [{"sample": "", "r1": "", "r2": ""}],
        },
        {
            "name": "genome_dir",
            "label": "STAR genome index directory",
            "type": "path",
            "artifact_type": "star_genome_dir",
            "required": True,
            "consumed_by": ["align"],
        },
        {"name": "genome_fasta", "label": "Genome FASTA", "type": "path", "artifact_type": "fasta", "required": True, "consumed_by": ["align"]},
        {"name": "gtf", "label": "Gene annotation GTF", "type": "path", "artifact_type": "gtf", "required": True, "consumed_by": ["align"]},
        {
            "name": "coldata",
            "label": "DESeq2 sample metadata",
            "type": "path",
            "artifact_type": "sample_metadata_table",
            "required": True,
            "consumed_by": ["de"],
        },
        {
            "name": "design",
            "label": "DESeq2 design formula",
            "type": "string",
            "artifact_type": "design_formula",
            "required": True,
            "default": "~ condition",
            "consumed_by": ["de"],
        },
        {"name": "reference", "label": "Reference condition", "type": "string", "required": False, "consumed_by": ["de"]},
        {"name": "threads", "label": "Threads", "type": "integer", "required": False, "default": 16, "consumed_by": ["align"]},
        {
            "name": "bam_sort",
            "label": "BAM output sort",
            "type": "string",
            "required": False,
            "default": "sorted",
            "choices": ["none", "sorted", "unsorted"],
            "consumed_by": ["align"],
        },
        {
            "name": "counts_matrix",
            "label": "Pre-staged STAR count matrix",
            "type": "path",
            "artifact_type": "gene_count_matrix",
            "required": False,
            "consumed_by": ["de"],
        },
        {
            "name": "skip_star",
            "label": "Skip STAR alignment and use counts_matrix",
            "type": "string",
            "required": False,
            "default": "false",
            "consumed_by": ["align"],
        },
    ]
    return {
        "schema": "morphic.graph_params_schema/v0",
        "graph_id": graph_id,
        "fields": fields,
        "required": [field["name"] for field in fields if field.get("required")],
    }


def trimodal_qc_params_schema(graph_id: str) -> dict[str, Any]:
    fields = [
        {"name": "mudata", "label": "MuData input", "type": "path", "artifact_type": "h5mu", "required": True, "consumed_by": ["qc"]},
        {"name": "output_prefix", "label": "Output prefix", "type": "path", "required": True, "consumed_by": ["qc"]},
        {"name": "title", "label": "Report title", "type": "string", "required": False, "default": "Trimodal QC report", "consumed_by": ["qc"]},
    ]
    return {
        "schema": "morphic.graph_params_schema/v0",
        "graph_id": graph_id,
        "fields": fields,
        "required": [field["name"] for field in fields if field.get("required")],
    }


def example_perturb_visualization_params_schema(graph_id: str) -> dict[str, Any]:
    fields = [
        {"name": "release_root", "label": "Example perturbation STAR release root", "type": "path", "artifact_type": "star_perturb_release_dir", "required": True, "consumed_by": ["production", "downstream", "technical_qc"]},
        {"name": "filtered_h5ad", "label": "Filtered AnnData", "type": "path", "artifact_type": "h5ad", "required": True, "consumed_by": ["embedding_clustering", "perturb_qc", "pseudobulk_de", "composition_dynamics"]},
        {"name": "unfiltered_h5ad", "label": "Unfiltered AnnData", "type": "path", "artifact_type": "h5ad", "required": False, "consumed_by": ["technical_qc"]},
        {"name": "crispr_calls_dir", "label": "CRISPR call directory", "type": "path", "artifact_type": "crispr_calls_dir", "required": True, "consumed_by": ["perturb_qc", "target_correlation"]},
        {"name": "sample_metadata", "label": "Sample metadata", "type": "path", "artifact_type": "sample_metadata_table", "required": True, "consumed_by": ["pseudobulk_de", "composition_dynamics", "embedding_clustering"]},
        {"name": "contrast_table", "label": "DE contrast table", "type": "path", "artifact_type": "contrast_table", "required": True, "consumed_by": ["pseudobulk_de", "de_visualization"]},
        {"name": "target_gene_map", "label": "Guide/target gene map", "type": "path", "artifact_type": "target_gene_map", "required": True, "consumed_by": ["perturb_qc", "target_correlation", "pathway_enrichment"]},
        {
            "name": "plot_contract_dir",
            "label": "Plot contract examples",
            "type": "path",
            "artifact_type": "plot_contract_dir",
            "required": False,
            "default": str(star_plot_contracts_dir()),
            "consumed_by": ["technical_qc", "embedding_clustering", "perturb_qc", "de_visualization", "target_correlation"],
        },
        {"name": "output_root", "label": "Visualization output root", "type": "path", "required": True, "consumed_by": ["technical_qc", "embedding_clustering", "perturb_qc", "de_visualization", "composition_dynamics", "target_correlation", "pathway_enrichment"]},
        {"name": "sample_column", "label": "Sample column", "type": "string", "required": False, "default": "sample", "consumed_by": ["pseudobulk_de", "composition_dynamics"]},
        {"name": "condition_column", "label": "Condition column", "type": "string", "required": False, "default": "condition", "consumed_by": ["pseudobulk_de", "composition_dynamics"]},
        {"name": "guide_column", "label": "Guide column", "type": "string", "required": False, "default": "guide_id", "consumed_by": ["perturb_qc", "target_correlation"]},
        {"name": "cell_type_column", "label": "Cell type column", "type": "string", "required": False, "default": "cell_type", "consumed_by": ["composition_dynamics"]},
    ]
    return {
        "schema": "morphic.graph_params_schema/v0",
        "graph_id": graph_id,
        "fields": fields,
        "required": [field["name"] for field in fields if field.get("required")],
    }


def validate_paired_reads(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list) or not value:
        errors.append("reads must be a non-empty list of paired-end samples")
        return errors
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"reads[{index}] must be an object with sample, r1, and r2")
            continue
        if not str(item.get("sample") or "").strip():
            errors.append(f"reads[{index}].sample is required")
        if not str(item.get("r1") or "").strip():
            errors.append(f"reads[{index}].r1 is required")
        if not str(item.get("r2") or "").strip():
            errors.append(f"reads[{index}].r2 is required for paired-end RNA-seq")
    return errors


def _value_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def validate_graph_params(graph: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    schema = graph.get("params_schema") if isinstance(graph.get("params_schema"), dict) else {}
    fields = schema.get("fields") if isinstance(schema.get("fields"), list) else []
    field_errors: dict[str, str] = {}
    missing: list[str] = []
    normalized: dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        name = str(field["name"])
        value = params.get(name, field.get("default"))
        if field.get("required") and _value_missing(value):
            missing.append(name)
            field_errors[name] = "required value is missing"
            continue
        normalized[name] = value
        if name == "reads":
            read_errors = validate_paired_reads(value)
            if read_errors:
                for message in read_errors:
                    field_errors[f"reads"] = message
                if "reads" not in missing:
                    missing.append("reads")
    return {
        "valid": not missing and not field_errors,
        "normalized_params": normalized,
        "missing_required_inputs": missing,
        "field_errors": field_errors,
    }
