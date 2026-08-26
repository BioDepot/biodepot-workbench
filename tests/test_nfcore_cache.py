"""Local nf-core metadata cache tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from morphic_agent.harvest.nfcore import harvest_nfcore_schema_file_to_registry
from morphic_agent.harvest.nfcore_cache import (
    NfCoreCacheConflict,
    cache_nfcore_pipeline_path,
    cache_nfcore_schema_file,
    list_cached_nfcore_metadata,
)
from morphic_agent.registry.store import AgentStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"
SCHEMA_FIXTURE = FIXTURE_ROOT / "minimal_nextflow_schema.json"
MODULES_FIXTURE = FIXTURE_ROOT / "minimal_modules.json"


def test_nfcore_metadata_cache_writes_only_small_metadata_files(tmp_path: Path):
    cache_root = tmp_path / "cache"

    manifest = cache_nfcore_schema_file(
        SCHEMA_FIXTURE,
        modules_json_path=MODULES_FIXTURE,
        cache_root=cache_root,
    )

    cache_dir = Path(manifest["cache_dir"])
    assert cache_dir.is_dir()
    assert manifest["schema"] == "morphic.harvest.nfcore_cache_manifest/v0"
    assert manifest["pipeline"] == "nf-core/demo"
    assert manifest["release"] == "1.2.3"
    assert manifest["schema_hash"].startswith("sha256:")
    assert manifest["schema_file_hash"].startswith("sha256:")
    assert manifest["modules_json_hash"].startswith("sha256:")
    assert manifest["modules_json_file_hash"].startswith("sha256:")
    assert (cache_dir / "nextflow_schema.json").is_file()
    assert (cache_dir / "modules.json").is_file()
    assert (cache_dir / "cache_manifest.json").is_file()
    assert (cache_dir / "source_manifest.json").is_file()
    assert sorted(path.name for path in cache_dir.iterdir()) == [
        "cache_manifest.json",
        "modules.json",
        "nextflow_schema.json",
        "source_manifest.json",
    ]

    cached = list_cached_nfcore_metadata(cache_root=cache_root)
    assert [item["cache_dir"] for item in cached] == [manifest["cache_dir"]]


def test_nfcore_metadata_cache_is_idempotent_for_identical_content(tmp_path: Path):
    cache_root = tmp_path / "cache"

    first = cache_nfcore_schema_file(SCHEMA_FIXTURE, modules_json_path=MODULES_FIXTURE, cache_root=cache_root)
    second = cache_nfcore_schema_file(SCHEMA_FIXTURE, modules_json_path=MODULES_FIXTURE, cache_root=cache_root)

    assert second == first


def test_nfcore_metadata_cache_refuses_to_overwrite_manual_edits(tmp_path: Path):
    cache_root = tmp_path / "cache"
    manifest = cache_nfcore_schema_file(SCHEMA_FIXTURE, modules_json_path=MODULES_FIXTURE, cache_root=cache_root)
    cached_schema = Path(manifest["cached_schema_path"])
    cached_schema.write_text('{"manual_edit": true}\n', encoding="utf-8")

    with pytest.raises(NfCoreCacheConflict):
        cache_nfcore_schema_file(SCHEMA_FIXTURE, modules_json_path=MODULES_FIXTURE, cache_root=cache_root)


def test_nfcore_pipeline_path_cache_detects_checkout_shape(tmp_path: Path):
    pipeline_dir = tmp_path / "nfcore-demo"
    pipeline_dir.mkdir()
    (pipeline_dir / "nextflow_schema.json").write_text(SCHEMA_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (pipeline_dir / "modules.json").write_text(MODULES_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    manifest = cache_nfcore_pipeline_path(pipeline_dir, cache_root=tmp_path / "cache")

    assert manifest["source_schema_path"] == str(pipeline_dir / "nextflow_schema.json")
    assert manifest["source_modules_json_path"] == str(pipeline_dir / "modules.json")


def test_registry_harvest_can_populate_cache_when_requested(tmp_path: Path):
    store = AgentStore(tmp_path / "nfcore.sqlite3")

    result = harvest_nfcore_schema_file_to_registry(
        SCHEMA_FIXTURE,
        store,
        modules_json_path=MODULES_FIXTURE,
        cache_root=tmp_path / "cache",
    )

    cache_manifest = result.import_manifest["cache_manifest"]
    assert cache_manifest["pipeline"] == "nf-core/demo"
    assert Path(cache_manifest["cached_schema_path"]).is_file()
    assert store.get_module_contract("nfcore_demo") is not None
