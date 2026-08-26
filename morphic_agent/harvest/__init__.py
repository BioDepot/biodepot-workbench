"""Local harvesters for external workflow metadata."""

from morphic_agent.harvest.nfcore import (
    NfCoreRegistryImportResult,
    harvest_nfcore_pipeline_path_to_registry,
    harvest_nfcore_remote_pipeline_to_registry,
    harvest_nfcore_schema_file_to_registry,
    register_nfcore_harvest_result,
)
from morphic_agent.harvest.nfcore_cache import (
    NfCoreCacheConflict,
    cache_nfcore_metadata_payload,
    cache_nfcore_pipeline_path,
    cache_nfcore_schema_file,
    default_nfcore_cache_root,
    list_cached_nfcore_metadata,
)
from morphic_agent.harvest.nfcore_decomposition import (
    NFCORE_DECOMPOSER_VERSION,
    NFCORE_DECOMPOSITION_SCHEMA,
    attach_nfcore_decomposition,
    decompose_nfcore_pipeline,
)
from morphic_agent.harvest.nfcore_mapper import NfCoreHarvestResult, map_nextflow_schema, map_nextflow_schema_file
from morphic_agent.harvest.nfcore_remote import (
    NfCorePipelineSpec,
    NfCoreRemoteError,
    NfCoreRemoteMetadata,
    NfCoreRemoteNotFound,
    NfCoreRemoteTooLarge,
    fetch_nfcore_remote_metadata,
    looks_like_nfcore_pipeline_spec,
    parse_nfcore_pipeline_spec,
)
from morphic_agent.harvest.nfcore_schema import NfCoreParameter, NfCoreParameterGroup, NfCoreSchema, load_nextflow_schema, parse_nextflow_schema
from morphic_agent.harvest.nfcore_validation import (
    NFCORE_REFERENCE_COMPARISON_KIND,
    NFCORE_REFERENCE_NEXTFLOW_COMPARATOR,
    NFCORE_VALIDATION_RECORD_SCHEMA,
    nfcore_reference_validation_record,
    validate_nfcore_reference_comparison_manifest,
)
from morphic_agent.harvest.nfcore_validation_matrix import NFCORE_VALIDATION_MATRIX_SCHEMA, build_nfcore_validation_matrix

__all__ = [
    "NfCoreHarvestResult",
    "NfCoreParameter",
    "NfCoreParameterGroup",
    "NfCoreSchema",
    "NfCorePipelineSpec",
    "NfCoreRegistryImportResult",
    "NfCoreRemoteError",
    "NfCoreRemoteMetadata",
    "NfCoreRemoteNotFound",
    "NfCoreRemoteTooLarge",
    "NfCoreCacheConflict",
    "NFCORE_REFERENCE_COMPARISON_KIND",
    "NFCORE_REFERENCE_NEXTFLOW_COMPARATOR",
    "NFCORE_VALIDATION_MATRIX_SCHEMA",
    "NFCORE_VALIDATION_RECORD_SCHEMA",
    "NFCORE_DECOMPOSER_VERSION",
    "NFCORE_DECOMPOSITION_SCHEMA",
    "cache_nfcore_metadata_payload",
    "attach_nfcore_decomposition",
    "build_nfcore_validation_matrix",
    "cache_nfcore_pipeline_path",
    "cache_nfcore_schema_file",
    "default_nfcore_cache_root",
    "decompose_nfcore_pipeline",
    "fetch_nfcore_remote_metadata",
    "harvest_nfcore_pipeline_path_to_registry",
    "harvest_nfcore_remote_pipeline_to_registry",
    "harvest_nfcore_schema_file_to_registry",
    "list_cached_nfcore_metadata",
    "looks_like_nfcore_pipeline_spec",
    "load_nextflow_schema",
    "map_nextflow_schema",
    "map_nextflow_schema_file",
    "parse_nfcore_pipeline_spec",
    "parse_nextflow_schema",
    "nfcore_reference_validation_record",
    "register_nfcore_harvest_result",
    "validate_nfcore_reference_comparison_manifest",
]
