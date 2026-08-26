"""Content-addressed local cache for nf-core metadata files."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from morphic_agent.harvest.nfcore_mapper import map_nextflow_schema

NFCORE_CACHE_ENV = "MORPHIC_NFCORE_CACHE_ROOT"
NFCORE_CACHE_MANIFEST_SCHEMA = "morphic.harvest.nfcore_cache_manifest/v0"


class NfCoreCacheConflict(RuntimeError):
    """Raised when a cache path exists with unexpected content."""


def default_nfcore_cache_root() -> Path:
    return Path(os.environ.get(NFCORE_CACHE_ENV) or "/tmp/morphic-nfcore-cache").expanduser()


def cache_nfcore_pipeline_path(
    pipeline_path: str | Path,
    *,
    cache_root: str | Path | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cache metadata from a local nf-core checkout or schema path.

    Only small metadata files are copied. This function does not download
    pipelines, containers, references, or run outputs.
    """

    path = Path(pipeline_path).expanduser()
    schema_path = path / "nextflow_schema.json" if path.is_dir() else path
    if not schema_path.is_file():
        raise FileNotFoundError(f"nf-core schema file not found: {schema_path}")
    modules_path = path / "modules.json" if path.is_dir() else schema_path.parent / "modules.json"
    if not modules_path.is_file():
        modules_path = None
    return cache_nfcore_schema_file(
        schema_path,
        modules_json_path=modules_path,
        cache_root=cache_root,
        provenance=provenance,
    )


def cache_nfcore_schema_file(
    schema_path: str | Path,
    *,
    modules_json_path: str | Path | None = None,
    cache_root: str | Path | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy one local nf-core schema and optional modules.json into the cache."""

    schema_path = Path(schema_path).expanduser()
    modules_path = Path(modules_json_path).expanduser() if modules_json_path is not None else None
    if not schema_path.is_file():
        raise FileNotFoundError(f"nf-core schema file not found: {schema_path}")
    if modules_path is not None and not modules_path.is_file():
        raise FileNotFoundError(f"nf-core modules.json file not found: {modules_path}")

    schema_bytes = schema_path.read_bytes()
    modules_bytes = modules_path.read_bytes() if modules_path is not None else None
    return cache_nfcore_metadata_payload(
        _json_bytes(schema_bytes, label=str(schema_path)),
        schema_bytes=schema_bytes,
        modules_json=_json_bytes(modules_bytes, label=str(modules_path)) if modules_bytes is not None else None,
        modules_bytes=modules_bytes,
        cache_root=cache_root,
        provenance={
            "schema_path": str(schema_path),
            **({"modules_json_path": str(modules_path)} if modules_path is not None else {}),
            **(provenance or {}),
        },
    )


def cache_nfcore_metadata_payload(
    schema_payload: dict[str, Any],
    *,
    schema_bytes: bytes,
    modules_json: dict[str, Any] | None = None,
    modules_bytes: bytes | None = None,
    cache_root: str | Path | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cache nf-core metadata that has already been loaded.

    This is used by remote metadata discovery so downloaded payloads can be
    cached without writing pipeline archives or other large assets.
    """

    if not isinstance(schema_payload, dict):
        raise TypeError("nf-core schema payload must be a JSON object")
    if modules_json is not None and not isinstance(modules_json, dict):
        raise TypeError("nf-core modules.json payload must be a JSON object")
    if modules_json is not None and modules_bytes is None:
        modules_bytes = json.dumps(modules_json, sort_keys=True, separators=(",", ":")).encode("utf-8")

    provenance = provenance or {}
    harvest = map_nextflow_schema(schema_payload, modules_json=modules_json, provenance=provenance)
    source_manifest = harvest.source_manifest
    schema_hash = str(source_manifest["schema_hash"])
    modules_hash = str(source_manifest.get("modules_json_hash") or "")
    schema_file_hash = _prefixed_sha256_bytes(schema_bytes)
    modules_file_hash = _prefixed_sha256_bytes(modules_bytes) if modules_bytes is not None else ""
    root = Path(cache_root).expanduser() if cache_root is not None else default_nfcore_cache_root()
    pipeline_id = _safe_component(source_manifest.get("pipeline_id") or "unknown")
    release = _safe_component(source_manifest.get("release") or "unreleased")
    short_hash = schema_hash.split(":", 1)[-1][:16]
    cache_dir = root / "metadata" / pipeline_id / release / short_hash
    cache_dir.mkdir(parents=True, exist_ok=True)

    cached_schema = cache_dir / "nextflow_schema.json"
    _write_once(cached_schema, schema_bytes, expected_hash=schema_file_hash)
    cached_modules = None
    if modules_bytes is not None:
        cached_modules = cache_dir / "modules.json"
        _write_once(cached_modules, modules_bytes, expected_hash=modules_file_hash)

    manifest = {
        "schema": NFCORE_CACHE_MANIFEST_SCHEMA,
        "source": "nf-core",
        "pipeline": source_manifest.get("pipeline"),
        "pipeline_id": source_manifest.get("pipeline_id"),
        "release": source_manifest.get("release"),
        "git_url": source_manifest.get("git_url"),
        "git_sha": source_manifest.get("git_sha"),
        "schema_hash": schema_hash,
        "schema_file_hash": schema_file_hash,
        "modules_json_hash": modules_hash or None,
        "modules_json_file_hash": modules_file_hash or None,
        "cache_dir": str(cache_dir),
        "cached_schema_path": str(cached_schema),
        "cached_modules_json_path": str(cached_modules) if cached_modules else None,
        "source_schema_path": source_manifest.get("schema_path"),
        "source_schema_url": source_manifest.get("schema_url") or provenance.get("schema_url"),
        "source_modules_json_path": source_manifest.get("modules_json_path"),
        "source_modules_json_url": source_manifest.get("modules_json_url") or provenance.get("modules_json_url"),
        "git_ref": source_manifest.get("git_ref") or provenance.get("git_ref"),
        "metadata_source": source_manifest.get("metadata_source") or provenance.get("metadata_source"),
        "harvester_version": source_manifest.get("harvester_version"),
        "notes": [
            "This cache contains only small nf-core metadata files.",
            "It does not contain pipeline archives, references, containers, or workflow outputs.",
        ],
    }
    manifest = {key: value for key, value in manifest.items() if value is not None}
    _write_json_once(cache_dir / "cache_manifest.json", manifest)
    _write_json_once(cache_dir / "source_manifest.json", source_manifest)
    return manifest


def list_cached_nfcore_metadata(*, cache_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = Path(cache_root).expanduser() if cache_root is not None else default_nfcore_cache_root()
    manifests: list[dict[str, Any]] = []
    if not root.exists():
        return manifests
    for path in sorted(root.glob("metadata/*/*/*/cache_manifest.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            manifests.append(payload)
    return manifests


def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    _write_once(path, data, expected_hash=_prefixed_sha256_bytes(data))


def _write_once(path: Path, data: bytes, *, expected_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing_hash = _prefixed_sha256_bytes(path.read_bytes())
        if existing_hash != expected_hash:
            raise NfCoreCacheConflict(
                f"cache file exists with different content: {path} ({existing_hash} != {expected_hash})"
            )
        return
    path.write_bytes(data)


def _prefixed_sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _json_bytes(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid nf-core JSON metadata in {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"nf-core JSON metadata must decode to an object: {label}")
    return payload


def _safe_component(value: Any) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip().lower()).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or "unknown"
