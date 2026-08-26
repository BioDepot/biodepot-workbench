"""Bundle materializers for Workbench recipe graphs."""

from morphic_agent.bundle.bulk_deg import (
    BULK_DEG_CORE_GRAPH_ID,
    BULK_DEG_PLOTS_GRAPH_ID,
    MATERIALIZABLE_BULK_DEG_GRAPH_IDS,
    assess_bulk_deg_execution_readiness,
    materialize_bulk_deseq_bundle,
    preflight_bulk_deseq_bundle,
)
from morphic_agent.bundle.nfcore_pipeline import (
    is_nfcore_pipeline_graph,
    materialize_nfcore_pipeline_bundle,
    normalize_nfcore_params,
    preflight_nfcore_bundle,
)

__all__ = [
    "BULK_DEG_CORE_GRAPH_ID",
    "BULK_DEG_PLOTS_GRAPH_ID",
    "MATERIALIZABLE_BULK_DEG_GRAPH_IDS",
    "assess_bulk_deg_execution_readiness",
    "is_nfcore_pipeline_graph",
    "materialize_nfcore_pipeline_bundle",
    "materialize_bulk_deseq_bundle",
    "normalize_nfcore_params",
    "preflight_bulk_deseq_bundle",
    "preflight_nfcore_bundle",
]
