"""Remote nf-core metadata harvest tests with mocked fetchers."""

from __future__ import annotations

from pathlib import Path

import pytest

from morphic_agent.harvest.nfcore import harvest_nfcore_remote_pipeline_to_registry
from morphic_agent.harvest.nfcore_cache import cache_nfcore_metadata_payload
from morphic_agent.harvest.nfcore_mapper import map_nextflow_schema
from morphic_agent.harvest.nfcore_remote import (
    NfCoreRemoteNotFound,
    NfCoreRemoteTooLarge,
    fetch_nfcore_remote_metadata,
    looks_like_nfcore_pipeline_spec,
    parse_nfcore_pipeline_spec,
)
from morphic_agent.registry.store import AgentStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nfcore"
SCHEMA_BYTES = (FIXTURE_ROOT / "minimal_nextflow_schema.json").read_bytes()
MODULES_BYTES = (FIXTURE_ROOT / "minimal_modules.json").read_bytes()
COMMIT_BYTES = b'{"sha":"0123456789abcdef0123456789abcdef01234567"}\n'


def test_nfcore_remote_metadata_fetch_uses_explicit_release_and_maps_contract():
    urls = {
        "https://raw.githubusercontent.com/nf-core/demo/1.2.3/nextflow_schema.json": SCHEMA_BYTES,
        "https://raw.githubusercontent.com/nf-core/demo/1.2.3/modules.json": MODULES_BYTES,
        "https://api.github.com/repos/nf-core/demo/commits/1.2.3": COMMIT_BYTES,
    }

    metadata = fetch_nfcore_remote_metadata("nf-core/demo@1.2.3", fetch_bytes=_fake_fetch(urls))
    result = map_nextflow_schema(metadata.schema, modules_json=metadata.modules_json, provenance=metadata.provenance)

    assert metadata.pipeline == "nf-core/demo"
    assert metadata.requested_release == "1.2.3"
    assert metadata.resolved_ref == "1.2.3"
    assert metadata.git_url == "https://github.com/nf-core/demo"
    assert metadata.git_sha == "0123456789abcdef0123456789abcdef01234567"
    assert metadata.schema_url.endswith("/nextflow_schema.json")
    assert metadata.modules_json_url.endswith("/modules.json")
    assert result.module_contract["module_id"] == "nfcore_demo"
    assert result.workflow_graph["graph_id"] == "nfcore_demo_v1_2_3"
    assert result.source_manifest["schema_url"] == metadata.schema_url
    assert result.source_manifest["modules_json_url"] == metadata.modules_json_url
    assert result.source_manifest["git_ref"] == "1.2.3"
    assert result.source_manifest["git_sha"] == metadata.git_sha
    assert result.source_manifest["metadata_source"] == "github_raw"


def test_nfcore_remote_metadata_falls_back_to_main_when_unreleased():
    urls = {
        "https://raw.githubusercontent.com/nf-core/demo/main/nextflow_schema.json": SCHEMA_BYTES,
    }

    metadata = fetch_nfcore_remote_metadata("nf-core/demo", fetch_bytes=_fake_fetch(urls))

    assert metadata.requested_release is None
    assert metadata.resolved_ref == "main"
    assert metadata.modules_json is None
    assert metadata.modules_json_url is None


def test_nfcore_remote_metadata_cache_preserves_source_urls(tmp_path: Path):
    urls = {
        "https://raw.githubusercontent.com/nf-core/demo/1.2.3/nextflow_schema.json": SCHEMA_BYTES,
        "https://raw.githubusercontent.com/nf-core/demo/1.2.3/modules.json": MODULES_BYTES,
        "https://api.github.com/repos/nf-core/demo/commits/1.2.3": COMMIT_BYTES,
    }
    metadata = fetch_nfcore_remote_metadata("nf-core/demo", release="1.2.3", fetch_bytes=_fake_fetch(urls))

    manifest = cache_nfcore_metadata_payload(
        metadata.schema,
        schema_bytes=metadata.schema_bytes,
        modules_json=metadata.modules_json,
        modules_bytes=metadata.modules_json_bytes,
        cache_root=tmp_path / "cache",
        provenance=metadata.provenance,
    )

    assert manifest["pipeline"] == "nf-core/demo"
    assert manifest["source_schema_url"] == metadata.schema_url
    assert manifest["source_modules_json_url"] == metadata.modules_json_url
    assert manifest["git_ref"] == "1.2.3"
    assert Path(manifest["cached_schema_path"]).is_file()
    assert Path(manifest["cached_modules_json_path"]).is_file()


def test_nfcore_remote_registry_import_indexes_remote_metadata(tmp_path: Path):
    urls = {
        "https://raw.githubusercontent.com/nf-core/demo/1.2.3/nextflow_schema.json": SCHEMA_BYTES,
        "https://raw.githubusercontent.com/nf-core/demo/1.2.3/modules.json": MODULES_BYTES,
        "https://api.github.com/repos/nf-core/demo/commits/1.2.3": COMMIT_BYTES,
    }
    store = AgentStore(tmp_path / "nfcore-remote.sqlite3")

    result = harvest_nfcore_remote_pipeline_to_registry(
        "nf-core/demo",
        store,
        release="1.2.3",
        cache_root=tmp_path / "cache",
        fetch_bytes=_fake_fetch(urls),
    )

    assert result.import_manifest["status"] == "ok"
    assert result.import_manifest["remote_metadata"]["resolved_ref"] == "1.2.3"
    assert result.import_manifest["remote_metadata"]["git_sha"] == "0123456789abcdef0123456789abcdef01234567"
    assert result.import_manifest["cache_manifest"]["source_schema_url"].endswith("/nextflow_schema.json")
    assert store.get_module_contract("nfcore_demo") is not None
    assert store.get_subgraph("nfcore_demo_v1_2_3") is not None
    search = store.search_graphs(query="github_raw nf-core demo", filters={"suite": "nf-core"})
    assert [item["graph_id"] for item in search["results"]] == ["nfcore_demo_v1_2_3"]


def test_nfcore_remote_validates_specs_and_size_limits():
    spec = parse_nfcore_pipeline_spec("nf-core/demo@1.2.3")
    assert spec.pipeline == "nf-core/demo"
    assert looks_like_nfcore_pipeline_spec("nf-core/demo@1.2.3")
    assert looks_like_nfcore_pipeline_spec("/tmp/nf-core/demo") is False

    with pytest.raises(ValueError):
        parse_nfcore_pipeline_spec("nf-core/../demo")
    with pytest.raises(ValueError):
        parse_nfcore_pipeline_spec("nf-core/demo@feature/branch")
    with pytest.raises(NfCoreRemoteTooLarge):
        fetch_nfcore_remote_metadata("nf-core/demo", release="1.2.3", max_metadata_bytes=8, fetch_bytes=lambda _url: SCHEMA_BYTES)


def _fake_fetch(urls: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        if url not in urls:
            raise NfCoreRemoteNotFound(f"not found: {url}")
        return urls[url]

    return fetch
