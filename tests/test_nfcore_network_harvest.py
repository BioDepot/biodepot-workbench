"""Opt-in network smoke test for remote nf-core metadata harvest."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from morphic_agent.harvest.nfcore import harvest_nfcore_remote_pipeline_to_registry
from morphic_agent.registry.store import AgentStore


pytestmark = pytest.mark.skipif(
    os.environ.get("MORPHIC_RUN_NFCORE_NETWORK") != "1",
    reason="set MORPHIC_RUN_NFCORE_NETWORK=1 to fetch small remote nf-core metadata",
)


def test_nfcore_network_metadata_harvest_fetches_only_small_metadata(tmp_path: Path):
    pipeline = os.environ.get("MORPHIC_NFCORE_NETWORK_PIPELINE") or "nf-core/rnaseq"
    release = os.environ.get("MORPHIC_NFCORE_NETWORK_RELEASE") or None
    timeout = float(os.environ.get("MORPHIC_NFCORE_NETWORK_TIMEOUT") or "30")
    store = AgentStore(tmp_path / "nfcore-network.sqlite3")

    result = harvest_nfcore_remote_pipeline_to_registry(
        pipeline,
        store,
        release=release,
        cache_root=tmp_path / "cache",
        timeout=timeout,
    )

    manifest = result.import_manifest
    remote = manifest["remote_metadata"]
    cache_dir = Path(manifest["cache_manifest"]["cache_dir"])
    allowed_files = {
        "cache_manifest.json",
        "modules.json",
        "nextflow_schema.json",
        "source_manifest.json",
    }

    assert manifest["status"] == "ok"
    assert remote["pipeline"].startswith("nf-core/")
    assert remote["schema_bytes"] < 5 * 1024 * 1024
    assert set(path.name for path in cache_dir.iterdir()) <= allowed_files
    assert store.get_module_contract(manifest["module_id"]) is not None
    assert store.get_subgraph(manifest["graph_id"]) is not None
