"""Remote nf-core metadata discovery for explicit pipeline specs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BytesFetcher = Callable[[str], bytes]

NFCORE_REMOTE_METADATA_SCHEMA = "morphic.harvest.nfcore_remote_metadata/v0"
NFCORE_REMOTE_FETCHER_VERSION = "morphic.nfcore_remote_metadata/v0"
DEFAULT_REF_CANDIDATES = ("master", "main")
DEFAULT_METADATA_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_METADATA_BYTES = 5 * 1024 * 1024

_PIPELINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class NfCoreRemoteError(RuntimeError):
    """Base class for remote nf-core metadata discovery failures."""


class NfCoreRemoteNotFound(NfCoreRemoteError):
    """Raised when an expected remote nf-core metadata file is not found."""


class NfCoreRemoteTooLarge(NfCoreRemoteError):
    """Raised when a remote metadata response exceeds the configured size cap."""


@dataclass(frozen=True)
class NfCorePipelineSpec:
    """Validated explicit nf-core pipeline selector."""

    pipeline: str
    pipeline_id: str
    release: str | None = None


@dataclass(frozen=True)
class NfCoreRemoteMetadata:
    """Small metadata payloads fetched for one nf-core pipeline/ref."""

    pipeline: str
    pipeline_id: str
    requested_release: str | None
    resolved_ref: str
    git_url: str
    git_sha: str | None
    schema_url: str
    schema_bytes: bytes
    schema: dict[str, Any]
    modules_json_url: str | None = None
    modules_json_bytes: bytes | None = None
    modules_json: dict[str, Any] | None = None
    metadata_source: str = "github_raw"

    @property
    def provenance(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "release": self.requested_release,
            "git_url": self.git_url,
            "git_sha": self.git_sha,
            "git_ref": self.resolved_ref,
            "schema_url": self.schema_url,
            "modules_json_url": self.modules_json_url,
            "metadata_source": self.metadata_source,
            "remote_fetcher": NFCORE_REMOTE_FETCHER_VERSION,
        }

    def manifest(self) -> dict[str, Any]:
        payload = {
            "schema": NFCORE_REMOTE_METADATA_SCHEMA,
            "source": "nf-core",
            "pipeline": self.pipeline,
            "pipeline_id": self.pipeline_id,
            "requested_release": self.requested_release,
            "resolved_ref": self.resolved_ref,
            "git_url": self.git_url,
            "git_sha": self.git_sha,
            "schema_url": self.schema_url,
            "schema_bytes": len(self.schema_bytes),
            "modules_json_url": self.modules_json_url,
            "modules_json_bytes": len(self.modules_json_bytes) if self.modules_json_bytes is not None else None,
            "metadata_source": self.metadata_source,
            "fetcher_version": NFCORE_REMOTE_FETCHER_VERSION,
            "notes": [
                "Only small metadata files were fetched.",
                "No pipeline archive, container, reference, or workflow output was downloaded.",
            ],
        }
        return {key: value for key, value in payload.items() if value is not None}


def parse_nfcore_pipeline_spec(spec: str, *, release: str | None = None) -> NfCorePipelineSpec:
    """Parse and validate ``nf-core/<pipeline>`` or ``nf-core/<pipeline>@<release>``."""

    text = str(spec or "").strip()
    if not text:
        raise ValueError("nf-core pipeline spec is required")
    inline_release: str | None = None
    if "@" in text:
        text, inline_release = text.rsplit("@", 1)
    requested_release = release or inline_release
    pipeline_id = text.split("/", 1)[1] if text.startswith("nf-core/") else text
    if not _PIPELINE_RE.fullmatch(pipeline_id):
        raise ValueError(f"invalid nf-core pipeline id: {pipeline_id!r}")
    if requested_release is not None and not _REF_RE.fullmatch(requested_release):
        raise ValueError(f"invalid nf-core release/ref: {requested_release!r}")
    return NfCorePipelineSpec(
        pipeline=f"nf-core/{pipeline_id}",
        pipeline_id=pipeline_id,
        release=requested_release,
    )


def looks_like_nfcore_pipeline_spec(value: str) -> bool:
    """Return True for explicit remote nf-core pipeline selectors."""

    text = str(value or "").strip()
    if not text:
        return False
    try:
        spec = parse_nfcore_pipeline_spec(text)
    except ValueError:
        return False
    return text.startswith("nf-core/") and bool(spec.pipeline_id)


def fetch_nfcore_remote_metadata(
    pipeline: str,
    *,
    release: str | None = None,
    timeout: float = DEFAULT_METADATA_TIMEOUT_SECONDS,
    max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES,
    fetch_bytes: BytesFetcher | None = None,
    resolve_git_sha: bool = True,
) -> NfCoreRemoteMetadata:
    """Fetch small metadata files for one explicit nf-core pipeline.

    This fetches only ``nextflow_schema.json`` and, when present, ``modules.json``.
    It does not download pipeline archives, containers, references, or outputs.
    """

    spec = parse_nfcore_pipeline_spec(pipeline, release=release)
    refs = (spec.release,) if spec.release else DEFAULT_REF_CANDIDATES
    errors: list[str] = []
    for ref in refs:
        assert ref is not None
        schema_url = _raw_url(spec.pipeline_id, ref, "nextflow_schema.json")
        try:
            schema_bytes = _fetch_metadata_bytes(
                schema_url,
                timeout=timeout,
                max_metadata_bytes=max_metadata_bytes,
                fetch_bytes=fetch_bytes,
            )
        except NfCoreRemoteNotFound as exc:
            errors.append(str(exc))
            continue
        schema_payload = _json_payload(schema_bytes, label=schema_url)
        modules_url = _raw_url(spec.pipeline_id, ref, "modules.json")
        modules_bytes = None
        modules_payload = None
        try:
            modules_bytes = _fetch_metadata_bytes(
                modules_url,
                timeout=timeout,
                max_metadata_bytes=max_metadata_bytes,
                fetch_bytes=fetch_bytes,
            )
            modules_payload = _json_payload(modules_bytes, label=modules_url)
        except NfCoreRemoteNotFound:
            modules_url = ""
        git_url = f"https://github.com/nf-core/{spec.pipeline_id}"
        git_sha = (
            _fetch_git_sha(
                spec.pipeline_id,
                ref,
                timeout=timeout,
                max_metadata_bytes=max_metadata_bytes,
                fetch_bytes=fetch_bytes,
            )
            if resolve_git_sha
            else None
        )
        return NfCoreRemoteMetadata(
            pipeline=spec.pipeline,
            pipeline_id=spec.pipeline_id,
            requested_release=spec.release,
            resolved_ref=ref,
            git_url=git_url,
            git_sha=git_sha,
            schema_url=schema_url,
            schema_bytes=schema_bytes,
            schema=schema_payload,
            modules_json_url=modules_url or None,
            modules_json_bytes=modules_bytes,
            modules_json=modules_payload,
        )
    detail = "; ".join(errors) if errors else "no candidate refs were attempted"
    raise NfCoreRemoteNotFound(f"nextflow_schema.json not found for {spec.pipeline}: {detail}")


def _raw_url(pipeline_id: str, ref: str, filename: str) -> str:
    return f"https://raw.githubusercontent.com/nf-core/{pipeline_id}/{ref}/{filename}"


def _commit_url(pipeline_id: str, ref: str) -> str:
    return f"https://api.github.com/repos/nf-core/{pipeline_id}/commits/{ref}"


def _fetch_git_sha(
    pipeline_id: str,
    ref: str,
    *,
    timeout: float,
    max_metadata_bytes: int,
    fetch_bytes: BytesFetcher | None,
) -> str | None:
    url = _commit_url(pipeline_id, ref)
    try:
        payload = _json_payload(
            _fetch_metadata_bytes(
                url,
                timeout=timeout,
                max_metadata_bytes=max_metadata_bytes,
                fetch_bytes=fetch_bytes,
            ),
            label=url,
        )
    except (NfCoreRemoteError, TypeError, ValueError):
        return None
    sha = payload.get("sha")
    return sha.strip() if isinstance(sha, str) and sha.strip() else None


def _fetch_metadata_bytes(
    url: str,
    *,
    timeout: float,
    max_metadata_bytes: int,
    fetch_bytes: BytesFetcher | None,
) -> bytes:
    if fetch_bytes is not None:
        data = fetch_bytes(url)
        if len(data) > max_metadata_bytes:
            raise NfCoreRemoteTooLarge(f"remote nf-core metadata exceeds size cap: {url}")
        return data
    request = Request(url, headers={"User-Agent": "morphic-agent-nfcore-harvester/0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(max_metadata_bytes + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise NfCoreRemoteNotFound(f"not found: {url}") from exc
        raise NfCoreRemoteError(f"failed to fetch {url}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise NfCoreRemoteError(f"failed to fetch {url}: {exc.reason}") from exc
    if len(data) > max_metadata_bytes:
        raise NfCoreRemoteTooLarge(f"remote nf-core metadata exceeds size cap: {url}")
    return data


def _json_payload(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid nf-core JSON metadata in {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"nf-core JSON metadata must decode to an object: {label}")
    return payload
