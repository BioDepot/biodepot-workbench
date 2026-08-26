"""Convert discovered suite recipes into registry module contracts."""

from __future__ import annotations

import re
from typing import Any

from morphic_agent.suites.registry import discover_suite_inventory

SUITE_IDS = ("star", "chromap", "multiomics")

OUTPUT_PARAM_NAMES = {
    "output",
    "out",
    "output_dir",
    "output_root",
    "output_prefix",
    "out_file_name_prefix",
    "out_file_name_prefix_auto",
    "run_id",
    "summary",
}

NON_ARTIFACT_PARAM_NAMES = {
    "dry_run",
    "force",
    "skip_active_check",
    "skip_signac_profile",
    "threads",
    "num_threads",
    "hts_threads",
    "run_thread_n",
    "max_reads",
    "run_mode",
    "batch_mode",
    "preset",
    "bam",
    "sort_bam",
    "write_index",
    "remove_pcr_duplicates",
    "tn5_shift",
    "mapq_threshold",
    "max_insert_size",
}

ARTIFACT_ALIASES = {
    "index": "chromap_index",
    "fragments": "atac_fragments",
    "peaks": "narrow_peak",
    "summits": "narrow_peak",
    "pairs": "hic_pairs",
    "mex": "tenx_mex",
    "html": "html",
    "markdown": "markdown",
    "json": "json",
    "png": "png",
    "tsv": "tsv",
    "text": "text",
    "directory": "directory",
    "file": "file",
    "bam": "bam",
    "bed": "bed",
    "tagalign": "tagalign",
    "h5mu": "h5mu",
    "h5ad": "h5ad",
}


def normalize_module_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return re.sub(r"_+", "_", text)


def _unique_module_id(candidate: str, suite_id: str, used: set[str], reserved: set[str]) -> str:
    module_id = candidate or normalize_module_id(suite_id)
    if module_id in used or module_id in reserved:
        prefixed = normalize_module_id(f"{suite_id}_{module_id}")
        module_id = prefixed
    if module_id not in used and module_id not in reserved:
        return module_id
    index = 2
    while f"{module_id}_{index}" in used or f"{module_id}_{index}" in reserved:
        index += 1
    return f"{module_id}_{index}"


def _normalize_artifact_type(value: Any, *, name: str = "", suite_id: str = "") -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    raw = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    name_text = str(name or "").strip().lower().replace("-", "_")
    if raw and raw != "other":
        return ARTIFACT_ALIASES.get(raw, raw)
    if "chromap_index" in name_text or name_text == "index":
        return "chromap_index"
    if "genome_dir" in name_text:
        return "star_genome_dir"
    if "reference" in name_text or "fasta" in name_text:
        return "fasta"
    if "gtf" in name_text:
        return "gtf"
    if "read" in name_text or "fastq" in name_text or "barcode" in name_text:
        return "fastq"
    if "fragment" in name_text:
        return "atac_fragments"
    if "peak" in name_text or "summit" in name_text:
        return "narrow_peak"
    if "pairs" in name_text:
        return "hic_pairs"
    if "tagalign" in name_text:
        return "tagalign"
    if "bam" in name_text:
        return "bam"
    if "bed" in name_text:
        return "bed"
    if "mudata" in name_text or "h5mu" in name_text:
        return "h5mu"
    if "h5ad" in name_text:
        return "h5ad"
    if "mex" in name_text:
        return "tenx_mex"
    if "metadata" in name_text or "coldata" in name_text:
        return "sample_metadata_table"
    if "evidence" in name_text and suite_id == "chromap":
        return "atac_evidence_table"
    return raw or "file"


def _is_output_like_field(item: dict[str, Any]) -> bool:
    name = str(item.get("name") or "").strip().lower()
    if name in OUTPUT_PARAM_NAMES:
        return True
    if str(item.get("category") or "").strip().lower() == "output":
        return True
    if item.get("is_output_root") is True:
        return True
    return name.startswith("output_")


def _input_from_field(item: dict[str, Any], *, suite_id: str) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not item.get("name") or _is_output_like_field(item):
        return None
    name = str(item["name"])
    field_type = str(item.get("type") or "").strip().lower()
    required = bool(item.get("required") or item.get("path_must_exist"))
    artifact_type = item.get("artifact_type")
    if not artifact_type and not required:
        return None
    if not artifact_type and field_type not in {"file", "directory", "path", "string"}:
        return None
    return {
        "name": name,
        "artifact_type": _normalize_artifact_type(artifact_type, name=name, suite_id=suite_id)
        if artifact_type
        else _normalize_artifact_type(None, name=name, suite_id=suite_id),
        "required": required,
        "source_field": item,
    }


def _inputs_for_recipe(recipe: dict[str, Any], *, suite_id: str) -> list[dict[str, Any]]:
    fields = recipe.get("inputs") if isinstance(recipe.get("inputs"), list) else []
    if not fields:
        fields = recipe.get("parameters") if isinstance(recipe.get("parameters"), list) else []
    output_parameter_names = _output_parameter_names(recipe)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip().lower()
        if name in NON_ARTIFACT_PARAM_NAMES or name in output_parameter_names:
            continue
        item = _input_from_field(field, suite_id=suite_id)
        if not item:
            continue
        key = f"{item['name']}:{item['artifact_type']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _output_parameter_names(recipe: dict[str, Any]) -> set[str]:
    names = set(OUTPUT_PARAM_NAMES)
    for output in recipe.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        template = str(output.get("path_template") or "")
        names.update(match.group(1).strip().lower() for match in re.finditer(r"\{([^{}]+)\}", template))
    return names


def _outputs_for_recipe(recipe: dict[str, Any], *, suite_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in recipe.get("outputs") or []:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        name = str(field["name"])
        artifact_type = _normalize_artifact_type(field.get("artifact_type"), name=name, suite_id=suite_id)
        key = f"{name}:{artifact_type}"
        if key in seen:
            continue
        seen.add(key)
        item = {
            "name": name,
            "artifact_type": artifact_type,
            "optional": bool(field.get("optional") or field.get("required") is False),
            "source_field": field,
        }
        if field.get("path_template"):
            item["path_template"] = field.get("path_template")
        out.append(item)
    return out


def _capabilities(recipe: dict[str, Any], *, suite_id: str) -> list[str]:
    text = " ".join(
        str(recipe.get(key) or "")
        for key in ("id", "recipe_id", "workflow_id", "title", "summary", "kind", "runtime_class")
    ).lower()
    capabilities = {suite_id, "suite_recipe"}
    for token in (
        "chromap",
        "star",
        "multiomics",
        "multiome",
        "trimodal",
        "atac",
        "scatac",
        "chip",
        "hic",
        "rna",
        "slam",
        "perturb",
        "qc",
        "report",
        "visualization",
        "benchmark",
        "smoke",
        "example_atac",
        "dogma",
        "hiv",
        "differential_expression",
        "deg",
    ):
        if token in text.replace("-", "_"):
            capabilities.add(token)
    if "four_factor" in text.replace("-", "_"):
        capabilities.add("four_factor")
    if "protein" in text:
        capabilities.add("protein")
    if "deseq" in text:
        capabilities.update({"differential_expression", "deg"})
    if "peak" in text or "macs3" in text:
        capabilities.add("peaks")
    if "fragment" in text:
        capabilities.add("fragments")
    return sorted(capabilities)


def _evidence(recipe: dict[str, Any], *, suite_id: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {
            "kind": "suite_recipe_registry",
            "suite": suite_id,
            "path": recipe.get("source_path"),
            "source_kind": recipe.get("source_kind"),
        }
    ]
    if recipe.get("schema_file"):
        evidence.append({"kind": "workflow_schema", "suite": suite_id, "path": recipe.get("schema_file")})
    for doc in recipe.get("docs") or []:
        if isinstance(doc, dict) and doc.get("path"):
            evidence.append({"kind": "documentation", "suite": suite_id, **doc})
    smoke = recipe.get("smoke_coverage")
    if isinstance(smoke, dict) and smoke:
        evidence.append({"kind": "smoke_coverage", "suite": suite_id, "coverage": smoke})
    for artifact in recipe.get("handoff_artifacts") or []:
        evidence.append({"kind": "handoff_artifact", "suite": suite_id, "description": str(artifact)})
    return evidence


def _confidence_tier(recipe: dict[str, Any]) -> str:
    if recipe.get("enabled") is False:
        return "source_derived"
    runtime_class = str(recipe.get("runtime_class") or "").lower()
    if runtime_class in {"smoke", "interactive"} and recipe.get("smoke_coverage"):
        return "tested_local_recipe"
    return "source_derived"


def _suite_recipe_metadata(recipe: dict[str, Any], *, suite_id: str) -> dict[str, Any]:
    recipe_id = str(recipe.get("recipe_id") or recipe.get("id") or recipe.get("workflow_id") or "").strip()
    runtime_class = str(recipe.get("runtime_class") or "").strip().lower()
    benchmark_policy = str(recipe.get("benchmark_policy") or "").strip().lower()
    text = " ".join(
        str(recipe.get(key) or "")
        for key in ("id", "recipe_id", "workflow_id", "title", "summary", "purpose", "kind")
    ).lower().replace("-", "_")

    family = suite_id
    assay_profile = f"{suite_id}_recipe"
    modalities: list[str] = []
    dataset_scope = "generic"

    if suite_id == "chromap":
        family = "chromap"
        modalities = ["atac"]
        if "hic" in text:
            assay_profile = "chromap_hic"
            modalities = ["hic"]
        elif "chip" in text or "tagalign" in text:
            assay_profile = "chromap_chip"
            modalities = ["chip"]
        elif "index" in text:
            assay_profile = "chromap_index"
            modalities = ["reference_index"]
        elif "evidence" in text:
            assay_profile = "chromap_atac_evidence"
            modalities = ["atac", "peaks"]
        elif "macs3" in text or "peak" in text:
            assay_profile = "chromap_atac_peaks"
            modalities = ["atac", "peaks"]
        else:
            assay_profile = "chromap_atac"
        dataset_scope = "generic_chromap"
    elif suite_id == "multiomics":
        family = "multiomics"
        if "four_factor" in text:
            family = "four_factor_mudata"
            assay_profile = "four_factor_h5mu"
            modalities = ["rna", "atac", "protein", "identity"]
            dataset_scope = "generic_h5mu"
        elif "trimodal" in text:
            family = "trimodal_mudata"
            assay_profile = "generic_trimodal_h5mu"
            modalities = ["rna", "atac", "crispr_guide"]
            dataset_scope = "generic_h5mu"
        elif "mudata_builder" in text or "mudata_builder" in recipe_id.replace("-", "_"):
            family = "multiome_mudata_builder"
            assay_profile = "multiome_mudata_builder"
            modalities = ["rna", "atac", "optional_protein", "optional_guide", "optional_hash", "optional_state"]
            dataset_scope = "generic_mudata_build"

    materialization = "suite_renderer_required"
    if runtime_class == "interactive":
        safety = "review_required"
        default_run_mode = "review_only"
    elif runtime_class == "smoke":
        safety = "operator_approval_required"
        default_run_mode = "dry_run_default"
    elif runtime_class == "long":
        safety = "operator_approval_required"
        default_run_mode = "blocked_by_default"
    elif runtime_class == "benchmark":
        safety = "operator_only"
        default_run_mode = "blocked_by_default"
    else:
        safety = "review_required"
        default_run_mode = "review_only"

    return {
        "schema": "morphic.suite_recipe_metadata/v0",
        "first_class_workbench_recipe": True,
        "recipe_family": family,
        "assay_profile": assay_profile,
        "modalities": modalities,
        "dataset_scope": dataset_scope,
        "execution_policy": {
            "runtime_class": runtime_class or None,
            "benchmark_policy": benchmark_policy or None,
            "safety": safety,
            "default_run_mode": default_run_mode,
            "materialization": materialization,
            "requires_suite_renderer": True,
            "requires_operator_confirmation": safety in {"operator_approval_required", "operator_only"},
            "serial_required": benchmark_policy == "serial_required",
        },
    }


def _suite_recipe_run_blocker(recipe_id: str, metadata: dict[str, Any]) -> str:
    policy = metadata.get("execution_policy") if isinstance(metadata.get("execution_policy"), dict) else {}
    runtime_class = str(policy.get("runtime_class") or "suite recipe")
    if policy.get("safety") == "operator_only":
        prefix = "Operator-only benchmark recipe"
    elif runtime_class == "smoke" and policy.get("safety") == "operator_approval_required":
        prefix = "Operator-approved smoke recipe"
    elif runtime_class == "long":
        prefix = "Long-running suite recipe"
    else:
        prefix = "Suite recipe"
    return (
        f"{prefix} `{recipe_id}` is imported as a first-class Workbench recipe surface, "
        f"but graph-to-bundle materialization for this {runtime_class} recipe still depends "
        "on a suite renderer binding."
    )


def module_contract_for_suite_recipe(
    recipe: dict[str, Any],
    *,
    suite_id: str,
    module_id: str,
) -> dict[str, Any]:
    recipe_id = str(recipe.get("recipe_id") or recipe.get("id") or module_id)
    parameters = recipe.get("parameters") if isinstance(recipe.get("parameters"), list) else []
    preflight = recipe.get("preflight") if isinstance(recipe.get("preflight"), list) else []
    metadata = _suite_recipe_metadata(recipe, suite_id=suite_id)
    return {
        "module_id": module_id,
        "title": str(recipe.get("title") or recipe_id),
        "description": str(recipe.get("summary") or recipe.get("purpose") or ""),
        "capabilities": _capabilities(recipe, suite_id=suite_id),
        "inputs": _inputs_for_recipe(recipe, suite_id=suite_id),
        "outputs": _outputs_for_recipe(recipe, suite_id=suite_id),
        "parameters": parameters,
        "parameter_groups": recipe.get("parameter_groups") if isinstance(recipe.get("parameter_groups"), list) else [],
        "constraints": recipe.get("constraints") if isinstance(recipe.get("constraints"), list) else [],
        "runtime": {
            "kind": "suite_recipe",
            "suite": suite_id,
            "recipe_id": recipe_id,
            "workflow_id": recipe.get("workflow_id") or recipe_id,
            "runtime_class": recipe.get("runtime_class"),
            "benchmark_policy": recipe.get("benchmark_policy"),
            "enabled": recipe.get("enabled", True),
            "entry_script": recipe.get("entry_script"),
            "schema_file": recipe.get("schema_file"),
            "source_kind": recipe.get("source_kind"),
            "source_path": recipe.get("source_path"),
            "entry_script_exists": recipe.get("entry_script_exists"),
            "source_exists": recipe.get("source_exists"),
            "default_visible": recipe.get("default_visible"),
            "assay_profile": metadata["assay_profile"],
            "recipe_family": metadata["recipe_family"],
            "dataset_scope": metadata["dataset_scope"],
            "execution_policy": metadata["execution_policy"],
        },
        "first_class_workbench_recipe": metadata["first_class_workbench_recipe"],
        "assay_profile": metadata["assay_profile"],
        "recipe_family": metadata["recipe_family"],
        "modalities": metadata["modalities"],
        "dataset_scope": metadata["dataset_scope"],
        "execution_policy": metadata["execution_policy"],
        "preflight": preflight,
        "command_template": recipe.get("command_template") if isinstance(recipe.get("command_template"), list) else [],
        "confidence_tier": _confidence_tier(recipe),
        "evidence": _evidence(recipe, suite_id=suite_id),
        "suite_recipe": {
            "schema": "morphic.suite_recipe_module_source/v0",
            "suite": suite_id,
            "recipe_id": recipe_id,
            "first_class_workbench_recipe": metadata["first_class_workbench_recipe"],
            "assay_profile": metadata["assay_profile"],
            "recipe_family": metadata["recipe_family"],
            "modalities": metadata["modalities"],
            "dataset_scope": metadata["dataset_scope"],
            "execution_policy": metadata["execution_policy"],
            "enabled": recipe.get("enabled", True),
            "notes": recipe.get("notes") if isinstance(recipe.get("notes"), list) else [],
        },
    }


def suite_recipe_module_catalog(
    *,
    reserved_module_ids: set[str] | None = None,
    suite_ids: tuple[str, ...] = SUITE_IDS,
) -> dict[str, Any]:
    reserved = set(reserved_module_ids or set())
    used: set[str] = set()
    modules: list[dict[str, Any]] = []
    inventory = discover_suite_inventory()
    suites = {
        str(suite.get("suite") or ""): suite
        for suite in inventory.get("suites") or []
        if isinstance(suite, dict)
    }
    for suite_id in suite_ids:
        suite = suites.get(suite_id) or {}
        if not suite.get("available"):
            continue
        for recipe in suite.get("recipes") or []:
            if not isinstance(recipe, dict):
                continue
            recipe_id = str(recipe.get("recipe_id") or recipe.get("id") or recipe.get("workflow_id") or "").strip()
            if not recipe_id:
                continue
            candidate = normalize_module_id(recipe_id)
            module_id = _unique_module_id(candidate, suite_id, used, reserved)
            used.add(module_id)
            modules.append(module_contract_for_suite_recipe(recipe, suite_id=suite_id, module_id=module_id))
    return {
        "schema": "morphic.suite_recipe_module_catalog/v0",
        "suite_inventory_schema": inventory.get("schema"),
        "modules": modules,
        "source": {
            "kind": "suite_recipe_discovery",
            "suite_ids": list(suite_ids),
            "available_suite_count": inventory.get("available_suite_count"),
        },
    }


def suite_recipe_graphs_from_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    graphs: list[dict[str, Any]] = []
    for module in modules:
        module_id = str(module.get("module_id") or "").strip()
        if not module_id:
            continue
        runtime = module.get("runtime") if isinstance(module.get("runtime"), dict) else {}
        suite_recipe = module.get("suite_recipe") if isinstance(module.get("suite_recipe"), dict) else {}
        graph_id = f"{module_id}_v0"
        recipe_id = str(runtime.get("recipe_id") or suite_recipe.get("recipe_id") or module_id)
        graphs.append(
            {
                "schema": "morphic.workflow_graph/v0",
                "graph_id": graph_id,
                "title": module.get("title") or module_id,
                "description": module.get("description") or "",
                "nodes": [
                    {
                        "id": "recipe",
                        "kind": "module",
                        "module_id": module_id,
                        "label": module.get("title") or module_id,
                        "confidence_tier": module.get("confidence_tier"),
                    }
                ],
                "edges": [],
                "inputs": module.get("inputs") or [],
                "outputs": module.get("outputs") or [],
                "capabilities": module.get("capabilities") or [],
                "required_human_inputs": [
                    str(item.get("name"))
                    for item in module.get("inputs") or []
                    if isinstance(item, dict) and item.get("required") and item.get("name")
                ],
                "confidence_tier": module.get("confidence_tier") or "source_derived",
                "lifecycle_state": "candidate",
                "materialization_status": "suite_recipe_declared",
                "run_blocker": _suite_recipe_run_blocker(recipe_id, suite_recipe),
                "suite": runtime.get("suite"),
                "suite_recipe_id": recipe_id,
                "suite_recipe": suite_recipe,
                "first_class_workbench_recipe": bool(suite_recipe.get("first_class_workbench_recipe")),
                "recipe_family": suite_recipe.get("recipe_family") or module.get("recipe_family"),
                "assay_profile": suite_recipe.get("assay_profile") or module.get("assay_profile"),
                "modalities": suite_recipe.get("modalities") or module.get("modalities") or [],
                "dataset_scope": suite_recipe.get("dataset_scope") or module.get("dataset_scope"),
                "execution_policy": suite_recipe.get("execution_policy") or module.get("execution_policy") or {},
                "evidence": module.get("evidence") or [],
            }
        )
    return graphs
