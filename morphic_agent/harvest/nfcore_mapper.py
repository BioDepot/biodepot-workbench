"""Map parsed nf-core schemas to Workbench module and graph contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from morphic_agent.harvest.nfcore_schema import (
    PARAM_SUPPORTED_KEYS,
    NfCoreParameter,
    NfCoreSchema,
    load_nextflow_schema,
    normalize_identifier,
    parse_nextflow_schema,
)

HARVESTER_VERSION = "morphic.nfcore_schema_mapper/v0"
SOURCE_MANIFEST_SCHEMA = "morphic.harvest.source/nfcore/v0"

KNOWN_PATH_PARAMS = {
    "bed",
    "bwa_index",
    "fasta",
    "gff",
    "gtf",
    "igenomes_base",
    "input",
    "outdir",
    "star_index",
}
OUTPUT_PATH_PARAMS = {"outdir", "out_dir", "output_dir", "output_root", "publish_dir"}
DIRECTORY_PATH_PARAMS = {
    "bwa_index",
    "igenomes_base",
    "out_dir",
    "outdir",
    "output_dir",
    "output_root",
    "publish_dir",
    "star_index",
}
PATH_FORMATS = {"directory-path", "file-path", "path"}
ADVANCED_PARAM_NAMES = {
    "config_profile_contact",
    "config_profile_description",
    "config_profile_name",
    "custom_config_base",
    "custom_config_version",
    "email",
    "help",
    "hook_url",
    "max_cpus",
    "max_memory",
    "max_time",
    "monochrome_logs",
    "multiqc_title",
    "profile",
    "publish_dir_mode",
    "validate_params",
    "version",
}
ARTIFACT_BY_NAME = {
    "bed": "bed",
    "bwa_index": "bwa_index",
    "fasta": "fasta",
    "gff": "gff",
    "gtf": "gtf",
    "igenomes_base": "reference_data_root",
    "outdir": "output_directory",
    "star_index": "star_index",
}


@dataclass(frozen=True)
class NfCoreHarvestResult:
    """Workbench contracts derived from a local nf-core schema."""

    module_contract: dict[str, Any]
    workflow_graph: dict[str, Any]
    params_schema: dict[str, Any]
    path_binding_candidates: list[dict[str, Any]]
    source_manifest: dict[str, Any]
    schema: NfCoreSchema


def map_nextflow_schema_file(
    schema_path: str | Path,
    *,
    modules_json_path: str | Path | None = None,
    provenance: dict[str, Any] | None = None,
) -> NfCoreHarvestResult:
    """Map a local ``nextflow_schema.json`` file into Workbench contracts."""

    schema = load_nextflow_schema(schema_path)
    modules_json = None
    if modules_json_path is not None:
        modules_json = json.loads(Path(modules_json_path).read_text(encoding="utf-8"))
    merged_provenance = {"schema_path": str(schema_path), **(provenance or {})}
    if modules_json_path is not None:
        merged_provenance["modules_json_path"] = str(modules_json_path)
    return map_nextflow_schema(schema, modules_json=modules_json, provenance=merged_provenance)


def map_nextflow_schema(
    schema: NfCoreSchema | dict[str, Any],
    *,
    modules_json: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> NfCoreHarvestResult:
    """Convert a parsed or raw nf-core schema into Workbench-native metadata."""

    parsed = schema if isinstance(schema, NfCoreSchema) else parse_nextflow_schema(schema)
    provenance = provenance or {}
    upstream = _upstream_provenance(parsed.raw, modules_json=modules_json, overrides=provenance)
    pipeline_id = upstream["pipeline_id"]
    module_id = f"nfcore_{normalize_identifier(pipeline_id)}"
    graph_id = _graph_id(module_id, upstream.get("release"))
    params_schema, path_binding_candidates = _params_schema(parsed, graph_id=graph_id)
    source_manifest = _source_manifest(parsed.raw, upstream, modules_json=modules_json, provenance=provenance)
    inputs = _module_inputs(path_binding_candidates)
    outputs = _module_outputs(path_binding_candidates)
    capabilities = _capabilities(upstream["pipeline"], parsed.raw)
    runtime = {
        "kind": "nfcore_pipeline",
        "suite": "nf-core",
        "pipeline": pipeline_id,
        "pipeline_name": upstream["pipeline"],
        "release": upstream.get("release"),
        "git_url": upstream.get("git_url"),
        "git_sha": upstream.get("git_sha"),
        "entrypoint": f"nextflow run {upstream['pipeline']}",
        "params_file": "nf-params.json",
        "schema_hash": source_manifest["schema_hash"],
    }
    execution_policy = {
        "default_engine": "nextflow",
        "supported_execution_locations": [
            "local",
            "server",
            "remote_ssh",
            "scheduler_temporal",
            "scheduler_remote_ssh",
        ],
        "requires_nextflow": True,
        "requires_java": True,
        "bundle_renderer": "pending",
    }
    evidence = _evidence(upstream, source_manifest)
    module_contract = {
        "schema": "morphic.module_contract/v0",
        "module_id": module_id,
        "title": upstream["pipeline"],
        "description": str(parsed.raw.get("description") or ""),
        "capabilities": capabilities,
        "runtime": runtime,
        "inputs": inputs,
        "outputs": outputs,
        "parameters": params_schema["fields"],
        "parameter_groups": params_schema["groups"],
        "params_schema": params_schema,
        "path_binding_candidates": path_binding_candidates,
        "required_human_inputs": params_schema["required"],
        "execution_policy": execution_policy,
        "confidence_tier": "upstream_declared",
        "first_class_workbench_recipe": True,
        "recipe_family": "nf-core",
        "assay_profile": f"nfcore_{normalize_identifier(pipeline_id)}",
        "modalities": _modalities(upstream["pipeline"], parsed.raw),
        "dataset_scope": "external_nfcore_pipeline",
        "evidence": evidence,
        "source_manifest": source_manifest,
        "extras": _contract_extras(parsed, modules_json=modules_json),
    }
    workflow_graph = {
        "schema": "morphic.workflow_graph/v0",
        "graph_id": graph_id,
        "title": upstream["pipeline"],
        "description": str(parsed.raw.get("description") or ""),
        "nodes": [
            {
                "id": "nfcore_pipeline",
                "kind": "module",
                "module_id": module_id,
                "label": upstream["pipeline"],
                "confidence_tier": "upstream_declared",
            }
        ],
        "edges": [],
        "inputs": inputs,
        "outputs": outputs,
        "capabilities": capabilities,
        "required_human_inputs": params_schema["required"],
        "params_schema": params_schema,
        "path_binding_candidates": path_binding_candidates,
        "runtime": runtime,
        "execution_policy": execution_policy,
        "confidence_tier": "upstream_declared",
        "lifecycle_state": "schema_mapped",
        "materialization_status": "runnable_nextflow_bundle",
        "suite": "nf-core",
        "recipe_family": "nf-core",
        "assay_profile": module_contract["assay_profile"],
        "modalities": module_contract["modalities"],
        "dataset_scope": module_contract["dataset_scope"],
        "evidence": evidence,
        "source_manifest": source_manifest,
    }
    return NfCoreHarvestResult(
        module_contract=module_contract,
        workflow_graph=workflow_graph,
        params_schema=params_schema,
        path_binding_candidates=path_binding_candidates,
        source_manifest=source_manifest,
        schema=parsed,
    )


def _params_schema(parsed: NfCoreSchema, *, graph_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fields: list[dict[str, Any]] = []
    path_binding_candidates: list[dict[str, Any]] = []
    for parameter in parsed.parameters:
        path_candidate = _path_binding_candidate(parameter)
        field = _field_for_parameter(parameter, path_candidate)
        fields.append(field)
        if path_candidate:
            path_binding_candidates.append(path_candidate)
    groups = [
        {
            "id": group.group_id,
            "title": group.title,
            "description": group.description,
            "fields": list(group.fields),
            "required": list(group.required),
            "advanced": group.advanced,
            **({"extras": group.extras} if group.extras else {}),
        }
        for group in parsed.groups
    ]
    return (
        {
            "schema": "morphic.graph_params_schema/v0",
            "graph_id": graph_id,
            "fields": fields,
            "groups": groups,
            "required": [field["name"] for field in fields if field.get("required")],
            "path_binding_candidates": path_binding_candidates,
        },
        path_binding_candidates,
    )


def _field_for_parameter(parameter: NfCoreParameter, path_candidate: dict[str, Any] | None) -> dict[str, Any]:
    source = parameter.schema
    field_type = "path" if path_candidate else _workbench_type(source)
    field: dict[str, Any] = {
        "name": parameter.name,
        "label": str(source.get("title") or parameter.name),
        "type": field_type,
        "required": parameter.required,
        "description": str(source.get("description") or ""),
        "group": parameter.group_id,
        "group_title": parameter.group_title,
        "advanced": _is_advanced_parameter(parameter),
        "consumed_by": ["nfcore_pipeline"],
    }
    if source.get("help_text"):
        field["help_text"] = source.get("help_text")
    if source.get("markdownDescription"):
        field["markdown_description"] = source.get("markdownDescription")
    if "default" in source:
        field["default"] = copy.deepcopy(source["default"])
    if isinstance(source.get("enum"), list):
        field["enum"] = copy.deepcopy(source["enum"])
        field["choices"] = copy.deepcopy(source["enum"])
    for key in ("pattern", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
        if key in source:
            field[key] = copy.deepcopy(source[key])
    if path_candidate:
        field["artifact_type"] = path_candidate["artifact_type"]
        field["path_binding"] = path_candidate["binding_id"]
        field["path_role"] = path_candidate["role"]
        if path_candidate.get("structured_artifact"):
            field["structured_artifact"] = copy.deepcopy(path_candidate["structured_artifact"])
    extras = _field_extras(parameter)
    if extras:
        field["extras"] = extras
    return field


def _field_extras(parameter: NfCoreParameter) -> dict[str, Any]:
    source = parameter.schema
    nfcore: dict[str, Any] = {
        "group_id": parameter.group_id,
        "group_title": parameter.group_title,
    }
    for key in ("exists", "format", "mimetype", "schema", "fa_icon", "hidden", "ignore"):
        if key in source:
            nfcore[key] = copy.deepcopy(source[key])
    unsupported = {
        str(key): copy.deepcopy(value)
        for key, value in source.items()
        if str(key) not in PARAM_SUPPORTED_KEYS
    }
    json_schema = {
        str(key): copy.deepcopy(source[key])
        for key in ("items", "properties", "required")
        if key in source
    }
    extras: dict[str, Any] = {"nfcore": nfcore}
    if json_schema:
        extras["json_schema"] = json_schema
    if unsupported:
        extras["unsupported_schema"] = dict(sorted(unsupported.items(), key=lambda item: item[0]))
    return extras


def _workbench_type(source: dict[str, Any]) -> str:
    schema_type = source.get("type")
    if isinstance(schema_type, list):
        non_null = [str(item) for item in schema_type if item != "null"]
        schema_type = non_null[0] if non_null else "string"
    if schema_type in {"array", "boolean", "integer", "number", "object", "string"}:
        return str(schema_type)
    if source.get("enum"):
        return "string"
    return "string"


def _path_binding_candidate(parameter: NfCoreParameter) -> dict[str, Any] | None:
    source = parameter.schema
    name = parameter.name
    normalized_name = normalize_identifier(name)
    source_format = str(source.get("format") or "").strip()
    sources: list[str] = []
    if source_format in PATH_FORMATS:
        sources.append("json_schema_format")
    if source.get("exists") is True:
        sources.append("json_schema_exists")
    if normalized_name in KNOWN_PATH_PARAMS:
        sources.append("known_nfcore_path_param")
    if _is_samplesheet_parameter(parameter):
        sources.append("samplesheet_schema")
    if not sources:
        return None
    role = "output" if normalized_name in OUTPUT_PATH_PARAMS else "input"
    path_kind = _path_kind(normalized_name, source_format)
    candidate: dict[str, Any] = {
        "binding_id": name,
        "param": name,
        "field": name,
        "role": role,
        "path_kind": path_kind,
        "artifact_type": _artifact_type(parameter, role=role, path_kind=path_kind),
        "required": parameter.required,
        "exists": bool(source.get("exists")) if role == "input" else False,
        "label": str(source.get("title") or name),
        "group": parameter.group_id,
        "sources": sorted(set(sources)),
    }
    if "default" in source:
        candidate["default"] = copy.deepcopy(source["default"])
    if _is_samplesheet_parameter(parameter):
        structured = {"kind": "samplesheet"}
        if source.get("schema"):
            structured["schema_path"] = str(source["schema"])
        candidate["structured_artifact"] = structured
    return candidate


def _path_kind(name: str, source_format: str) -> str:
    if source_format == "directory-path" or name in DIRECTORY_PATH_PARAMS:
        return "directory"
    if source_format == "file-path":
        return "file"
    return "path"


def _artifact_type(parameter: NfCoreParameter, *, role: str, path_kind: str) -> str:
    name = normalize_identifier(parameter.name)
    if _is_samplesheet_parameter(parameter):
        return "samplesheet"
    if name in ARTIFACT_BY_NAME:
        return ARTIFACT_BY_NAME[name]
    if role == "output":
        return "output_directory" if path_kind == "directory" else "output_path"
    return "directory" if path_kind == "directory" else "file"


def _is_samplesheet_parameter(parameter: NfCoreParameter) -> bool:
    name = normalize_identifier(parameter.name)
    source = parameter.schema
    if name in {"sample_sheet", "samplesheet"}:
        return True
    if name != "input":
        return False
    text = " ".join(
        str(source.get(key) or "")
        for key in ("title", "description", "help_text", "schema")
    ).lower()
    return bool(source.get("schema")) or "sample" in text or "csv" in text


def _is_advanced_parameter(parameter: NfCoreParameter) -> bool:
    name = normalize_identifier(parameter.name)
    if parameter.group_advanced or name in ADVANCED_PARAM_NAMES:
        return True
    return parameter.schema.get("hidden") is True


def _module_inputs(path_binding_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for candidate in path_binding_candidates:
        if candidate.get("role") != "input":
            continue
        item = {
            "name": candidate["param"],
            "artifact_type": candidate["artifact_type"],
            "required": bool(candidate.get("required")),
            "source_param": candidate["param"],
            "path_binding_id": candidate["binding_id"],
        }
        if candidate.get("structured_artifact"):
            item["structured_artifact"] = copy.deepcopy(candidate["structured_artifact"])
        out.append(item)
    return out


def _module_outputs(path_binding_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for candidate in path_binding_candidates:
        if candidate.get("role") != "output":
            continue
        out.append(
            {
                "name": candidate["param"],
                "artifact_type": candidate["artifact_type"],
                "optional": not bool(candidate.get("required")),
                "source_param": candidate["param"],
                "path_binding_id": candidate["binding_id"],
            }
        )
    return out


def _upstream_provenance(
    raw_schema: dict[str, Any],
    *,
    modules_json: dict[str, Any] | None,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    manifest = raw_schema.get("manifest") if isinstance(raw_schema.get("manifest"), dict) else {}
    modules_json = modules_json if isinstance(modules_json, dict) else {}
    pipeline = _first_text(
        overrides.get("pipeline"),
        raw_schema.get("pipeline"),
        raw_schema.get("pipeline_name"),
        raw_schema.get("name"),
        manifest.get("name"),
        modules_json.get("pipeline"),
        modules_json.get("name"),
        _pipeline_from_title(str(raw_schema.get("title") or "")),
    )
    pipeline = pipeline or "nf-core/unknown"
    if "/" not in pipeline and not pipeline.startswith("nf-core/"):
        pipeline = f"nf-core/{pipeline}"
    pipeline_id = pipeline.split("/", 1)[1] if "/" in pipeline else pipeline
    return {
        "pipeline": pipeline,
        "pipeline_id": pipeline_id,
        "release": _first_text(
            overrides.get("release"),
            raw_schema.get("release"),
            raw_schema.get("version"),
            manifest.get("version"),
            modules_json.get("release"),
            modules_json.get("version"),
        ),
        "git_url": _first_text(
            overrides.get("git_url"),
            raw_schema.get("git_url"),
            raw_schema.get("repository"),
            manifest.get("homePage"),
            modules_json.get("git_url"),
            modules_json.get("repository"),
        ),
        "git_sha": _first_text(
            overrides.get("git_sha"),
            raw_schema.get("git_sha"),
            raw_schema.get("commit"),
            raw_schema.get("revision"),
            modules_json.get("git_sha"),
            modules_json.get("commit"),
            modules_json.get("revision"),
        ),
    }


def _source_manifest(
    raw_schema: dict[str, Any],
    upstream: dict[str, Any],
    *,
    modules_json: dict[str, Any] | None,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    manifest = {
        "schema": SOURCE_MANIFEST_SCHEMA,
        "source": "nf-core",
        "pipeline": upstream["pipeline"],
        "pipeline_id": upstream["pipeline_id"],
        "release": upstream.get("release"),
        "git_url": upstream.get("git_url"),
        "git_sha": upstream.get("git_sha"),
        "git_ref": provenance.get("git_ref"),
        "schema_path": provenance.get("schema_path"),
        "schema_url": provenance.get("schema_url"),
        "schema_hash": _prefixed_sha256(raw_schema),
        "metadata_source": provenance.get("metadata_source"),
        "harvester_version": HARVESTER_VERSION,
    }
    if modules_json is not None:
        manifest["modules_json_path"] = provenance.get("modules_json_path")
        manifest["modules_json_url"] = provenance.get("modules_json_url")
        manifest["modules_json_hash"] = _prefixed_sha256(modules_json)
    if provenance.get("harvested_at"):
        manifest["harvested_at"] = provenance["harvested_at"]
    return {key: value for key, value in manifest.items() if value is not None}


def _evidence(upstream: dict[str, Any], source_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = [
        {
            "kind": "nfcore_pipeline",
            "path": upstream.get("git_url"),
            "pipeline": upstream["pipeline"],
            "release": upstream.get("release"),
            "git_sha": upstream.get("git_sha"),
        },
        {
            "kind": "nfcore_schema",
            "path": source_manifest.get("schema_path") or source_manifest.get("schema_url"),
            "schema_hash": source_manifest.get("schema_hash"),
        },
    ]
    if source_manifest.get("modules_json_hash"):
        evidence.append(
            {
                "kind": "nfcore_modules_json",
                "path": source_manifest.get("modules_json_path") or source_manifest.get("modules_json_url"),
                "modules_json_hash": source_manifest.get("modules_json_hash"),
            }
        )
    return [{key: value for key, value in item.items() if value is not None} for item in evidence]


def _contract_extras(parsed: NfCoreSchema, *, modules_json: dict[str, Any] | None) -> dict[str, Any]:
    extras: dict[str, Any] = {
        "nfcore_schema": parsed.extras,
    }
    if modules_json is not None:
        extras["modules_json"] = {
            "hash": _prefixed_sha256(modules_json),
            "installed_modules": _installed_modules_summary(modules_json),
        }
    return extras


def _installed_modules_summary(modules_json: dict[str, Any]) -> list[dict[str, Any]]:
    direct = modules_json.get("modules")
    if isinstance(direct, list):
        out = []
        for item in direct:
            if isinstance(item, dict) and item.get("name"):
                out.append(
                    {
                        key: item[key]
                        for key in ("name", "git_sha", "repository", "version")
                        if key in item
                    }
                )
        return sorted(out, key=lambda item: str(item.get("name") or ""))

    repos = modules_json.get("repos") if isinstance(modules_json.get("repos"), dict) else {}
    out: list[dict[str, Any]] = []
    for repo_url, repo_payload in sorted(repos.items(), key=lambda item: str(item[0])):
        repo_modules = repo_payload.get("modules") if isinstance(repo_payload, dict) else {}
        if not isinstance(repo_modules, dict):
            continue
        for namespace, namespace_modules in sorted(repo_modules.items(), key=lambda item: str(item[0])):
            if not isinstance(namespace_modules, dict):
                continue
            for module_name, module_payload in sorted(namespace_modules.items(), key=lambda item: str(item[0])):
                item = {
                    "name": f"{namespace}/{module_name}",
                    "repository": repo_url,
                }
                if isinstance(module_payload, dict) and module_payload.get("git_sha"):
                    item["git_sha"] = module_payload["git_sha"]
                out.append(item)
    return out


def _capabilities(pipeline: str, raw_schema: dict[str, Any]) -> list[str]:
    normalized_pipeline = normalize_identifier(pipeline)
    text = " ".join(
        [
            normalized_pipeline,
            str(raw_schema.get("title") or ""),
            str(raw_schema.get("description") or ""),
        ]
    ).lower().replace("-", "_")
    capabilities = {"nf-core", "nfcore", "nfcore_pipeline", "nextflow", normalized_pipeline}
    if "rna" in text:
        capabilities.update({"rna_seq", "transcriptomics"})
    if "atac" in text:
        capabilities.add("atac_seq")
    if "chip" in text:
        capabilities.add("chip_seq")
    if "singlecell" in text or "single_cell" in text:
        capabilities.add("single_cell")
    if "differential" in text or "deseq" in text:
        capabilities.update({"differential_expression", "deg"})
    return sorted(capability for capability in capabilities if capability)


def _modalities(pipeline: str, raw_schema: dict[str, Any]) -> list[str]:
    text = " ".join([pipeline, str(raw_schema.get("title") or ""), str(raw_schema.get("description") or "")]).lower()
    modalities: set[str] = set()
    if "rna" in text:
        modalities.add("rna")
    if "atac" in text:
        modalities.add("atac")
    if "chip" in text:
        modalities.add("chip")
    return sorted(modalities)


def _graph_id(module_id: str, release: str | None) -> str:
    if release:
        release_id = normalize_identifier(f"v{release}")
        return f"{module_id}_{release_id}"
    return f"{module_id}_v0"


def _pipeline_from_title(title: str) -> str:
    match = re.search(r"nf-core/[A-Za-z0-9_.-]+", title)
    return match.group(0) if match else ""


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _prefixed_sha256(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
