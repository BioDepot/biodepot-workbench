"""Local nf-core harvest entrypoints for Workbench registry integration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from morphic_agent.harvest.nfcore_cache import cache_nfcore_metadata_payload, cache_nfcore_pipeline_path, cache_nfcore_schema_file
from morphic_agent.harvest.nfcore_decomposition import attach_nfcore_decomposition, decompose_nfcore_pipeline
from morphic_agent.harvest.nfcore_mapper import NfCoreHarvestResult, map_nextflow_schema, map_nextflow_schema_file
from morphic_agent.harvest.nfcore_remote import BytesFetcher, fetch_nfcore_remote_metadata
from morphic_agent.registry.store import AgentStore

NFCORE_REGISTRY_IMPORT_SCHEMA = "morphic.harvest.nfcore_registry_import/v0"


@dataclass(frozen=True)
class NfCoreRegistryImportResult:
    """Result of importing one mapped nf-core pipeline into Workbench storage."""

    import_manifest: dict[str, Any]
    harvest_result: NfCoreHarvestResult


def harvest_nfcore_schema_file_to_registry(
    schema_path: str | Path,
    store: AgentStore,
    *,
    modules_json_path: str | Path | None = None,
    provenance: dict[str, Any] | None = None,
    cache_root: str | Path | None = None,
    version: str = "nfcore-schema-mapped",
) -> NfCoreRegistryImportResult:
    """Map one local nf-core schema file and upsert it into Workbench storage."""

    schema_path = Path(schema_path)
    modules_path = Path(modules_json_path) if modules_json_path is not None else None
    harvest = map_nextflow_schema_file(
        schema_path,
        modules_json_path=modules_path,
        provenance={
            "schema_path": str(schema_path),
            **({"modules_json_path": str(modules_path)} if modules_path is not None else {}),
            **(provenance or {}),
        },
    )
    cache_manifest = (
        cache_nfcore_schema_file(
            schema_path,
            modules_json_path=modules_path,
            cache_root=cache_root,
            provenance=provenance,
        )
        if cache_root is not None
        else None
    )
    return register_nfcore_harvest_result(harvest, store, version=version, cache_manifest=cache_manifest)


def harvest_nfcore_pipeline_path_to_registry(
    pipeline_path: str | Path,
    store: AgentStore,
    *,
    decompose_source: bool = True,
    strict_decomposition: bool = False,
    provenance: dict[str, Any] | None = None,
    cache_root: str | Path | None = None,
    version: str = "nfcore-schema-mapped",
) -> NfCoreRegistryImportResult:
    """Map a local nf-core checkout directory and upsert it into Workbench storage.

    This is intentionally local-only. It looks for ``nextflow_schema.json`` and
    an optional ``modules.json`` under the supplied directory.
    """

    pipeline_path = Path(pipeline_path)
    pipeline_root = pipeline_path if pipeline_path.is_dir() else pipeline_path.parent
    schema_path = pipeline_root / "nextflow_schema.json" if pipeline_path.is_dir() else pipeline_path
    if not schema_path.is_file():
        raise FileNotFoundError(f"nf-core schema file not found: {schema_path}")
    modules_path = pipeline_root / "modules.json"
    if modules_path is not None and not modules_path.is_file():
        modules_path = None
    cache_manifest = (
        cache_nfcore_pipeline_path(pipeline_path, cache_root=cache_root, provenance=provenance)
        if cache_root is not None
        else None
    )
    harvest = map_nextflow_schema_file(
        schema_path,
        modules_json_path=modules_path,
        provenance={
            "schema_path": str(schema_path),
            **({"modules_json_path": str(modules_path)} if modules_path is not None else {}),
            **(provenance or {}),
        },
    )
    decomposition = None
    if decompose_source and (pipeline_root / "main.nf").is_file():
        decomposition = decompose_nfcore_pipeline(pipeline_root, strict=strict_decomposition)
        harvest = attach_nfcore_decomposition(harvest, decomposition)
    result = register_nfcore_harvest_result(harvest, store, version=version, cache_manifest=cache_manifest)
    if cache_manifest is not None:
        result.import_manifest["cache_manifest"] = cache_manifest
    if decomposition is not None:
        result.import_manifest["decomposition"] = {
            "schema": decomposition["schema"],
            "status": decomposition["status"],
            "summary": decomposition["summary"],
            "source_index_hash": decomposition["source_manifest"]["source_index_hash"],
        }
    return result


def harvest_nfcore_remote_pipeline_to_registry(
    pipeline: str,
    store: AgentStore,
    *,
    release: str | None = None,
    provenance: dict[str, Any] | None = None,
    cache_root: str | Path | None = None,
    timeout: float = 20.0,
    fetch_bytes: BytesFetcher | None = None,
    version: str = "nfcore-remote-schema-mapped",
) -> NfCoreRegistryImportResult:
    """Fetch small remote nf-core metadata and register the mapped recipe.

    Only ``nextflow_schema.json`` and optional ``modules.json`` are requested.
    This does not download pipeline archives, containers, references, or run
    outputs.
    """

    metadata = fetch_nfcore_remote_metadata(
        pipeline,
        release=release,
        timeout=timeout,
        fetch_bytes=fetch_bytes,
    )
    merged_provenance = {
        **metadata.provenance,
        **(provenance or {}),
    }
    harvest = map_nextflow_schema(
        metadata.schema,
        modules_json=metadata.modules_json,
        provenance=merged_provenance,
    )
    cache_manifest = (
        cache_nfcore_metadata_payload(
            metadata.schema,
            schema_bytes=metadata.schema_bytes,
            modules_json=metadata.modules_json,
            modules_bytes=metadata.modules_json_bytes,
            cache_root=cache_root,
            provenance=merged_provenance,
        )
        if cache_root is not None
        else None
    )
    result = register_nfcore_harvest_result(harvest, store, version=version, cache_manifest=cache_manifest)
    result.import_manifest["remote_metadata"] = metadata.manifest()
    return result


def register_nfcore_harvest_result(
    harvest: NfCoreHarvestResult,
    store: AgentStore,
    *,
    version: str = "nfcore-schema-mapped",
    cache_manifest: dict[str, Any] | None = None,
) -> NfCoreRegistryImportResult:
    """Persist mapped nf-core module and graph records in Workbench repositories."""

    module = harvest.module_contract
    graph = harvest.workflow_graph
    source_manifest = harvest.source_manifest
    catalog_payload = {
        "schema": "morphic.module_catalog/v0",
        "source": source_manifest,
        "modules": [module],
    }
    module_import = store.import_module_catalog(
        catalog_payload,
        source_path=_source_path(source_manifest),
    )
    graph_import = store.record_subgraph(graph, version=version)
    import_manifest = {
        "schema": NFCORE_REGISTRY_IMPORT_SCHEMA,
        "status": "ok",
        "module_id": module["module_id"],
        "graph_id": graph["graph_id"],
        "source_manifest": source_manifest,
        "module_import": module_import,
        "graph_import": graph_import,
        "cache_manifest": cache_manifest,
        "search_facets": {
            "suite": graph.get("suite"),
            "recipe_family": graph.get("recipe_family"),
            "assay_profile": graph.get("assay_profile"),
            "modalities": graph.get("modalities") or [],
            "input_artifact_types": [
                item.get("artifact_type")
                for item in graph.get("inputs") or []
                if isinstance(item, dict) and item.get("artifact_type")
            ],
            "output_artifact_types": [
                item.get("artifact_type")
                for item in graph.get("outputs") or []
                if isinstance(item, dict) and item.get("artifact_type")
            ],
            "capabilities": graph.get("capabilities") or [],
            "materialization_status": graph.get("materialization_status"),
            "lifecycle_state": graph.get("lifecycle_state"),
        },
    }
    if cache_manifest is None:
        import_manifest.pop("cache_manifest", None)
    return NfCoreRegistryImportResult(import_manifest=import_manifest, harvest_result=harvest)


def _source_path(source_manifest: dict[str, Any]) -> str:
    schema_path = str(source_manifest.get("schema_path") or "").strip()
    if schema_path:
        return schema_path
    pipeline = str(source_manifest.get("pipeline") or source_manifest.get("pipeline_id") or "unknown")
    release = str(source_manifest.get("release") or "unreleased")
    return f"nfcore://{pipeline}@{release}"
