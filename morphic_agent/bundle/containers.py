"""Container image contracts for portable recipe bundles."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTAINER_MANIFEST_SCHEMA = "morphic.container_manifest/v0"

TRIMODAL_QC_IMAGE = "biodepot/morphic-trimodal-qc:0.1.0"
BIOC_DESEQ2_IMAGE = "biodepot/morphic-bioc-deseq2:0.1.0"
BIOC_DESEQ2_DIGEST: str | None = None
CHROMAP_SUITE_IMAGE = "biodepot/morphic-chromap-suite:0.1.0"
CHROMAP_SUITE_DIGEST: str | None = "sha256:245a2575c74340465031372eb6facc3029ce1e770c807f5f520543724a536f06"

BIOC_DESEQ2_STACK: dict[str, Any] = {
    "os": "ubuntu:24.04",
    "r": "4.6.0",
    "bioconductor": "3.23",
    "cran_snapshot": "2026-06-28",
    "python": None,
    "conda_lock": None,
}

BIOC_DESEQ2_PROFILE_KEYS = frozenset({"bulk_pe_deseq2_counts_v0", "example_perturb_pseudobulk_deseq2_v0"})
CHROMAP_SUITE_PROFILE_KEYS = frozenset(
    {
        "chromap_index_v0",
        "chromap_atac_bam_fragments_v0",
        "chromap_atac_bed_v0",
        "chromap_macs3_frag_peaks_v0",
        "chromap_atac_evidence_from_peaks_v0",
        "chromap_chip_tagalign_v0",
        "chromap_hic_pairs_v0",
    }
)

CHROMAP_SUITE_STACK: dict[str, Any] = {
    "os": "ubuntu:24.04",
    "chromap_suite": "1.0.0",
    "chromap_upstream": "0.3.3-r519",
    "python": "3.12",
    "apt_snapshot": "20260509T000000Z",
}


def _chromap_suite_profile(*, module_ids: list[str], assay_profile: str) -> dict[str, Any]:
    return {
        "profile_id": "chromap-suite",
        "status": "validated",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-chromap-suite",
            "tag": "0.1.0",
            "reference": CHROMAP_SUITE_IMAGE,
            "docker_uri": f"docker://{CHROMAP_SUITE_IMAGE}",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-chromap-suite-sif:0.1.0",
            "digest": CHROMAP_SUITE_DIGEST,
        },
        "dockerfile": {
            "path": "dockerfiles/chromap-suite/Dockerfile",
            "context": ".",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
        "requirements": [
            {"name": "bash", "kind": "command"},
            {"name": "chromap", "kind": "command"},
            {"name": "samtools", "kind": "command"},
            {"name": "bedtools", "kind": "command"},
            {"name": "bgzip", "kind": "command"},
            {"name": "tabix", "kind": "command"},
        ],
        "module_ids": list(module_ids),
        "assay_profile": assay_profile,
    }


CONTAINER_PROFILES: dict[str, dict[str, Any]] = {
    "trimodal_qc_report_v0": {
        "profile_id": "trimodal-qc",
        "status": "implemented",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-trimodal-qc",
            "tag": "0.1.0",
            "reference": TRIMODAL_QC_IMAGE,
            "docker_uri": f"docker://{TRIMODAL_QC_IMAGE}",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-trimodal-qc-sif:0.1.0",
            "digest": None,
        },
        "dockerfile": {
            "path": "dockerfiles/trimodal-qc/Dockerfile",
            "context": "dockerfiles/trimodal-qc",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
        "requirements": [
            {"name": "bash", "kind": "command"},
            {"name": "python3", "kind": "command"},
            {"name": "mudata", "kind": "python_package"},
            {"name": "plotly", "kind": "python_package"},
            {"name": "scanpy", "kind": "python_package"},
            {"name": "pandas", "kind": "python_package"},
            {"name": "numpy", "kind": "python_package"},
        ],
    },
    "multiomics_trimodal_qc_report_v0": {
        "profile_id": "trimodal-qc",
        "status": "planned",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-trimodal-qc",
            "tag": "0.1.0",
            "reference": TRIMODAL_QC_IMAGE,
            "docker_uri": f"docker://{TRIMODAL_QC_IMAGE}",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-trimodal-qc-sif:0.1.0",
            "digest": None,
        },
        "dockerfile": {
            "path": "dockerfiles/trimodal-qc/Dockerfile",
            "context": "dockerfiles/trimodal-qc",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
    },
    "bulk_pe_deseq2_v0": {
        "profile_id": "star-bulk-rnaseq",
        "status": "planned",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-star-bulk-rnaseq",
            "tag": "0.1.0",
            "reference": "biodepot/morphic-star-bulk-rnaseq:0.1.0",
            "docker_uri": "docker://biodepot/morphic-star-bulk-rnaseq:0.1.0",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-star-bulk-rnaseq-sif:0.1.0",
            "digest": None,
        },
        "dockerfile": {
            "path": "dockerfiles/star-bulk-rnaseq/Dockerfile",
            "context": "dockerfiles/star-bulk-rnaseq",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
    },
    "bulk_pe_deseq2_counts_v0": {
        "profile_id": "bioc-deseq2",
        "status": "planned",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-bioc-deseq2",
            "tag": "0.1.0",
            "reference": BIOC_DESEQ2_IMAGE,
            "docker_uri": f"docker://{BIOC_DESEQ2_IMAGE}",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-bioc-deseq2-sif:0.1.0",
            "digest": BIOC_DESEQ2_DIGEST,
        },
        "dockerfile": {
            "path": "dockerfiles/bioc-deseq2/Dockerfile",
            "context": "dockerfiles/bioc-deseq2",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
        "requirements": [
            {"name": "bash", "kind": "command"},
            {"name": "Rscript", "kind": "command"},
            {"name": "DESeq2", "kind": "r_package"},
            {"name": "jsonlite", "kind": "r_package"},
        ],
        "module_ids": ["deseq2_differential_expression"],
    },
    "bulk_pe_deseq2_plots_v0": {
        "profile_id": "star-bulk-rnaseq",
        "status": "planned",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-star-bulk-rnaseq",
            "tag": "0.1.0",
            "reference": "biodepot/morphic-star-bulk-rnaseq:0.1.0",
            "docker_uri": "docker://biodepot/morphic-star-bulk-rnaseq:0.1.0",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-star-bulk-rnaseq-sif:0.1.0",
            "digest": None,
        },
        "dockerfile": {
            "path": "dockerfiles/star-bulk-rnaseq/Dockerfile",
            "context": "dockerfiles/star-bulk-rnaseq",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
    },
    "example_perturb_visualization_suite_v0": {
        "profile_id": "example_perturb-star-suite",
        "status": "planned",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-example_perturb-star-suite",
            "tag": "0.1.0",
            "reference": "biodepot/morphic-example_perturb-star-suite:0.1.0",
            "docker_uri": "docker://biodepot/morphic-example_perturb-star-suite:0.1.0",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-example_perturb-star-suite-sif:0.1.0",
            "digest": None,
        },
        "dockerfile": {
            "path": "dockerfiles/example_perturb-star-suite/Dockerfile",
            "context": "dockerfiles/example_perturb-star-suite",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
    },
    "example_perturb_pseudobulk_deseq2_v0": {
        "profile_id": "bioc-deseq2",
        "status": "planned",
        "image": {
            "registry": "docker.io",
            "repository": "biodepot/morphic-bioc-deseq2",
            "tag": "0.1.0",
            "reference": BIOC_DESEQ2_IMAGE,
            "docker_uri": f"docker://{BIOC_DESEQ2_IMAGE}",
            "oras_sif_uri": "oras://docker.io/biodepot/morphic-bioc-deseq2-sif:0.1.0",
            "digest": BIOC_DESEQ2_DIGEST,
        },
        "dockerfile": {
            "path": "dockerfiles/bioc-deseq2/Dockerfile",
            "context": "dockerfiles/bioc-deseq2",
        },
        "supported_runtimes": ["docker", "podman", "apptainer"],
        "container_workdir": "/workspace/bundle",
        "entrypoint": ["bash", "run.sh"],
        "requirements": [
            {"name": "bash", "kind": "command"},
            {"name": "Rscript", "kind": "command"},
            {"name": "DESeq2", "kind": "r_package"},
            {"name": "jsonlite", "kind": "r_package"},
        ],
        "module_ids": ["example_perturb_pseudobulk_deseq2"],
    },
    "chromap_index_v0": _chromap_suite_profile(
        module_ids=["chromap_index"],
        assay_profile="chromap_index",
    ),
    "chromap_atac_bam_fragments_v0": _chromap_suite_profile(
        module_ids=["chromap_atac_bam_fragments"],
        assay_profile="chromap_atac",
    ),
    "chromap_atac_bed_v0": _chromap_suite_profile(
        module_ids=["chromap_atac_bed"],
        assay_profile="chromap_atac",
    ),
    "chromap_macs3_frag_peaks_v0": _chromap_suite_profile(
        module_ids=["chromap_macs3_frag_peaks"],
        assay_profile="chromap_atac_peaks",
    ),
    "chromap_atac_evidence_from_peaks_v0": _chromap_suite_profile(
        module_ids=["chromap_atac_evidence_from_peaks"],
        assay_profile="chromap_atac_evidence",
    ),
    "chromap_chip_tagalign_v0": _chromap_suite_profile(
        module_ids=["chromap_chip_tagalign"],
        assay_profile="chromap_chip",
    ),
    "chromap_hic_pairs_v0": _chromap_suite_profile(
        module_ids=["chromap_hic_pairs"],
        assay_profile="chromap_hic",
    ),
}


def container_profile_for_graph(graph_id: str) -> dict[str, Any] | None:
    profile = CONTAINER_PROFILES.get(str(graph_id or ""))
    return deepcopy(profile) if profile else None


def build_container_manifest(graph_id: str, *, bundle_dir: Path, profile_key: str | None = None) -> dict[str, Any] | None:
    resolved_profile_key = str(profile_key or graph_id or "")
    profile = container_profile_for_graph(resolved_profile_key)
    if profile is None:
        return None
    image = dict(profile.get("image") or {})
    if not image.get("digest"):
        resolved = resolve_docker_image_digest(str(image.get("reference") or ""))
        if resolved:
            image["digest"] = resolved
    manifest: dict[str, Any] = {
        "schema": CONTAINER_MANIFEST_SCHEMA,
        "graph_id": graph_id,
        "created_at": _utc_now(),
        "profile_id": profile["profile_id"],
        "status": profile.get("status") or "planned",
        "image": image,
        "dockerfile": profile.get("dockerfile") or {},
        "supported_runtimes": profile.get("supported_runtimes") or ["docker", "podman", "apptainer"],
        "container_workdir": profile.get("container_workdir") or "/workspace/bundle",
        "entrypoint": profile.get("entrypoint") or ["bash", "run.sh"],
        "mounts": [
            {
                "name": "bundle",
                "source": ".",
                "target": profile.get("container_workdir") or "/workspace/bundle",
                "mode": "rw",
            }
        ],
        "env": {
            "MORPHIC_CONTAINER": "1",
            "WRITE_PNG": "0",
            "HOME": "/tmp",
            "XDG_CACHE_HOME": "/tmp/.cache",
            "MPLCONFIGDIR": "/tmp/matplotlib",
            "NUMBA_CACHE_DIR": "/tmp/numba_cache",
        },
        "requirements": profile.get("requirements") or [],
        "launchers": [
            {"runtime": "docker", "bundle_path": "run.docker.sh", "command": "./run.docker.sh"},
            {"runtime": "apptainer", "bundle_path": "run.apptainer.sh", "command": "./run.apptainer.sh"},
        ],
        "notes": [
            "Container launchers mount this bundle at the container workdir and execute bash run.sh.",
            "Dockerfiles are maintained outside generated bundles under dockerfiles/.",
        ],
    }
    if resolved_profile_key in BIOC_DESEQ2_PROFILE_KEYS or profile.get("profile_id") == "bioc-deseq2":
        manifest["stack"] = dict(BIOC_DESEQ2_STACK)
        module_ids = profile.get("module_ids") or []
        if module_ids:
            manifest["module_ids"] = list(module_ids)
        manifest["profile_key"] = resolved_profile_key
    if resolved_profile_key in CHROMAP_SUITE_PROFILE_KEYS or profile.get("profile_id") == "chromap-suite":
        manifest["stack"] = dict(CHROMAP_SUITE_STACK)
        module_ids = profile.get("module_ids") or []
        if module_ids:
            manifest["module_ids"] = list(module_ids)
        manifest["profile_key"] = resolved_profile_key
        if profile.get("assay_profile"):
            manifest["assay_profile"] = profile["assay_profile"]
    return manifest


def resolve_docker_image_digest(image_reference: str) -> str | None:
    reference = str(image_reference or "").strip()
    if not reference:
        return None
    docker_path = shutil.which("docker")
    if not docker_path:
        return None
    try:
        proc = subprocess.run(
            [docker_path, "image", "inspect", reference, "--format", "{{json .RepoDigests}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        repo_digests = json.loads((proc.stdout or "[]").strip() or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(repo_digests, list):
        return None
    repository = reference.split(":", 1)[0]
    for item in repo_digests:
        text = str(item or "")
        if "@" not in text:
            continue
        repo, digest = text.split("@", 1)
        if repo == repository or repo.endswith(f"/{repository}"):
            return digest
    return None


def resolve_deseq2_execution_route(
    *,
    execution_location_kind: str,
    host_deseq2_available: bool,
    container_diagnostic: dict[str, Any] | None,
    skip_star: bool = False,
) -> dict[str, Any]:
    diagnostic = container_diagnostic or {}
    container_available = bool(diagnostic.get("run_available"))
    preferred_runtime = str(diagnostic.get("preferred_runtime") or "").strip() or None
    container_command = str(diagnostic.get("command") or "").strip() or None
    image_ref = str((diagnostic.get("image") or {}).get("reference") or BIOC_DESEQ2_IMAGE)

    route_by_kind = {
        "server": "host_r",
        "local": "local_docker",
        "remote_ssh": "remote_ssh_docker",
        "scheduler_temporal": "scheduler_local_docker",
        "scheduler_remote_ssh": "scheduler_ssh_docker",
    }
    route_id = route_by_kind.get(execution_location_kind, "host_r")

    labels = {
        "host_r": "host R (Rscript on the Workbench server)",
        "local_docker": "local Docker (caller-managed ./run.docker.sh)",
        "remote_ssh_docker": "remote SSH Docker (Workbench copies bundle and runs ./run.docker.sh)",
        "scheduler_local_docker": "scheduler local Docker (Temporal worker runs the declared container image)",
        "scheduler_ssh_docker": "scheduler SSH Docker (Temporal SSH Docker workflow on the remote host)",
    }
    commands = {
        "host_r": "bash run.sh",
        "local_docker": container_command or "./run.docker.sh",
        "remote_ssh_docker": container_command or "./run.docker.sh",
        "scheduler_local_docker": None,
        "scheduler_ssh_docker": None,
    }

    if route_id == "host_r":
        available = host_deseq2_available
        blocker = None if available else "DESeq2 and jsonlite must both be available via Rscript on this host"
    else:
        available = container_available
        blocker = None
        if not skip_star and image_ref == BIOC_DESEQ2_IMAGE:
            available = False
            blocker = "DESeq2-only container execution requires skip_star=true with a pre-staged counts_matrix; use the full STAR bulk RNA-seq image for FASTQ inputs."
        elif not available:
            blockers = list(diagnostic.get("blockers") or [])
            blocker = "; ".join(blockers) if blockers else f"container route requires a supported runtime and image {image_ref}"

    summary = (
        f"Selected route: {labels[route_id]}."
        + (f" Command: {commands[route_id]}." if commands.get(route_id) else "")
        + (
            " The selected container must include both STAR and DESeq2 for FASTQ inputs."
            if not skip_star and route_id != "host_r"
            else ""
        )
    )
    return {
        "schema": "morphic.deseq2_execution_route/v0",
        "route_id": route_id,
        "label": labels[route_id],
        "available": available,
        "command": commands.get(route_id),
        "image": image_ref,
        "preferred_runtime": preferred_runtime,
        "host_deseq2_available": host_deseq2_available,
        "container_available": container_available,
        "skip_star": skip_star,
        "summary": summary,
        "run_blocker": blocker,
    }


def write_container_manifest(bundle_dir: Path, graph_id: str, *, profile_key: str | None = None) -> dict[str, Any] | None:
    manifest = build_container_manifest(graph_id, bundle_dir=Path(bundle_dir), profile_key=profile_key)
    if manifest is None:
        return None
    manifests_dir = Path(bundle_dir) / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "container.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_container_manifest(bundle_dir: Path) -> dict[str, Any] | None:
    path = Path(bundle_dir) / "manifests" / "container.json"
    if not path.is_file():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def container_manifest_hash(manifest: dict[str, Any]) -> str:
    text = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def container_manifest_response(bundle_dir: Path) -> dict[str, Any]:
    manifest = load_container_manifest(bundle_dir)
    if manifest is None:
        return {"container_manifest_path": None, "container_manifest_hash": None}
    return {
        "container_manifest_path": "manifests/container.json",
        "container_manifest_hash": container_manifest_hash(manifest),
    }


def write_container_launchers(bundle_dir: Path, graph_id: str, *, profile_key: str | None = None) -> list[str]:
    manifest = load_container_manifest(bundle_dir) or write_container_manifest(bundle_dir, graph_id, profile_key=profile_key)
    if manifest is None:
        return []
    bundle = Path(bundle_dir)
    docker_path = bundle / "run.docker.sh"
    apptainer_path = bundle / "run.apptainer.sh"
    docker_path.write_text(_docker_launcher(manifest), encoding="utf-8")
    apptainer_path.write_text(_apptainer_launcher(manifest), encoding="utf-8")
    docker_path.chmod(0o755)
    apptainer_path.chmod(0o755)
    return ["run.docker.sh", "run.apptainer.sh"]


def detect_container_runtimes() -> dict[str, dict[str, Any]]:
    return {
        "docker": _runtime_status("docker", ["--version"]),
        "podman": _runtime_status("podman", ["--version"]),
        "apptainer": _runtime_status("apptainer", ["--version"]),
    }


def diagnose_container_manifest(manifest: dict[str, Any] | None, *, execution_location_kind: str) -> dict[str, Any]:
    if manifest is None:
        return {
            "schema": "morphic.container_diagnostic/v0",
            "status": "missing",
            "run_available": False,
            "checks": [{"check": "container manifest present", "status": "not_run"}],
            "blockers": [],
            "available_runtimes": [],
            "supported_runtimes": [],
            "preferred_runtime": None,
            "command": None,
        }

    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    schema_ok = manifest.get("schema") == CONTAINER_MANIFEST_SCHEMA
    checks.append({"check": "container manifest schema", "status": "pass" if schema_ok else "fail"})
    if not schema_ok:
        blockers.append("container manifest has an unsupported schema")

    image_ref = str((manifest.get("image") or {}).get("reference") or "")
    checks.append({"check": "container image reference declared", "status": "pass" if image_ref else "fail", "image": image_ref})
    if not image_ref:
        blockers.append("container image reference is missing")

    supported = [str(item) for item in manifest.get("supported_runtimes") or []]
    runtime_status = detect_container_runtimes()
    available = [runtime for runtime in supported if runtime_status.get(runtime, {}).get("available")]
    for runtime in supported:
        status = runtime_status.get(runtime, {"available": False, "path": None, "version": None})
        checks.append(
            {
                "check": f"container runtime available: {runtime}",
                "status": "pass" if status.get("available") else "fail",
                "path": status.get("path"),
                "version": status.get("version"),
            }
        )

    preferred = _preferred_runtime(available)
    command = _command_for_runtime(manifest, preferred) if preferred else None
    runtime_checked_here = execution_location_kind == "local"
    if runtime_checked_here and not preferred:
        blockers.append("no supported local container runtime is installed; install Docker, Podman, or Apptainer")
    run_available = bool(schema_ok and image_ref and (preferred or not runtime_checked_here) and not blockers)

    return {
        "schema": "morphic.container_diagnostic/v0",
        "status": "ready" if run_available else ("blocked" if blockers else "declared"),
        "run_available": run_available,
        "image": manifest.get("image") or {},
        "dockerfile": manifest.get("dockerfile") or {},
        "available_runtimes": available,
        "supported_runtimes": supported,
        "runtime_status": runtime_status,
        "preferred_runtime": preferred,
        "command": command,
        "checks": checks,
        "blockers": blockers,
        "launchers": manifest.get("launchers") or [],
    }


def _docker_launcher(manifest: dict[str, Any]) -> str:
    image = str((manifest.get("image") or {}).get("reference") or TRIMODAL_QC_IMAGE)
    workdir = str(manifest.get("container_workdir") or "/workspace/bundle")
    entrypoint = " ".join(_shell_quote(str(item)) for item in manifest.get("entrypoint") or ["bash", "run.sh"])
    return f"""#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
IMAGE="${{MORPHIC_CONTAINER_IMAGE:-{image}}}"
RUNTIME="${{CONTAINER_RUNTIME:-docker}}"

if ! command -v "$RUNTIME" >/dev/null 2>&1; then
  echo "Container runtime '$RUNTIME' was not found. Install Docker or set CONTAINER_RUNTIME=podman." >&2
  exit 127
fi

mount_args=(-v "$BUNDLE_DIR:{workdir}:rw")
if command -v python3 >/dev/null 2>&1 && [[ -f "$BUNDLE_DIR/manifests/path_bindings.json" ]]; then
  while IFS=$'\\t' read -r raw_path role path_kind mount_mode; do
    [[ "$path_kind" =~ ^(caller_visible|server_visible|remote_visible)$ && "$raw_path" == /* ]] || continue
    [[ -e "$raw_path" ]] || continue
    if [[ -d "$raw_path" ]]; then
      mount_src="$raw_path"
    else
      mount_src="$(dirname -- "$raw_path")"
    fi
    mount_args+=(-v "$mount_src:$mount_src:$mount_mode")
  done < <(python3 - "$BUNDLE_DIR/manifests/path_bindings.json" <<'PY'
import json
import sys
from pathlib import Path

OUTPUT_MARKERS = ("output", "out_", "outdir", "out_dir", "prefix", "report", "result")
manifest = json.loads(Path(sys.argv[1]).read_text())
for binding in manifest.get("bindings") or []:
    if not isinstance(binding, dict):
        continue
    role = str(binding.get("role") or "")
    mode = "rw" if any(marker in role.lower() for marker in OUTPUT_MARKERS) else "ro"
    print("\\t".join([
        str(binding.get("path") or ""),
        role,
        str(binding.get("path_kind") or ""),
        mode,
    ]))
PY
  )
fi

exec "$RUNTIME" run --rm -t \\
  -u "$(id -u):$(id -g)" \\
  "${{mount_args[@]}}" \\
  -w "{workdir}" \\
  -e MORPHIC_CONTAINER=1 \\
  -e WRITE_PNG="${{WRITE_PNG:-0}}" \\
  -e HOME=/tmp \\
  -e XDG_CACHE_HOME=/tmp/.cache \\
  -e MPLCONFIGDIR=/tmp/matplotlib \\
  -e NUMBA_CACHE_DIR=/tmp/numba_cache \\
  -e MUDATA="${{MUDATA:-}}" \\
  -e OUTPUT_PREFIX="${{OUTPUT_PREFIX:-}}" \\
  -e TITLE="${{TITLE:-}}" \\
  "$IMAGE" {entrypoint}
"""


def _apptainer_launcher(manifest: dict[str, Any]) -> str:
    image = str((manifest.get("image") or {}).get("docker_uri") or f"docker://{TRIMODAL_QC_IMAGE}")
    workdir = str(manifest.get("container_workdir") or "/workspace/bundle")
    entrypoint = " ".join(_shell_quote(str(item)) for item in manifest.get("entrypoint") or ["bash", "run.sh"])
    return f"""#!/usr/bin/env bash
set -euo pipefail
BUNDLE_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
IMAGE="${{MORPHIC_APPTAINER_IMAGE:-{image}}}"

if ! command -v apptainer >/dev/null 2>&1; then
  echo "Apptainer was not found. Install Apptainer, or use run.docker.sh with Docker/Podman." >&2
  exit 127
fi

bind_args=(--bind "$BUNDLE_DIR:{workdir}")
if command -v python3 >/dev/null 2>&1 && [[ -f "$BUNDLE_DIR/manifests/path_bindings.json" ]]; then
  while IFS=$'\\t' read -r raw_path role path_kind mount_mode; do
    [[ "$path_kind" =~ ^(caller_visible|server_visible|remote_visible)$ && "$raw_path" == /* ]] || continue
    [[ -e "$raw_path" ]] || continue
    if [[ -d "$raw_path" ]]; then
      bind_src="$raw_path"
    else
      bind_src="$(dirname -- "$raw_path")"
    fi
    bind_args+=(--bind "$bind_src:$bind_src:$mount_mode")
  done < <(python3 - "$BUNDLE_DIR/manifests/path_bindings.json" <<'PY'
import json
import sys
from pathlib import Path

OUTPUT_MARKERS = ("output", "out_", "outdir", "out_dir", "prefix", "report", "result")
manifest = json.loads(Path(sys.argv[1]).read_text())
for binding in manifest.get("bindings") or []:
    if not isinstance(binding, dict):
        continue
    role = str(binding.get("role") or "")
    mode = "rw" if any(marker in role.lower() for marker in OUTPUT_MARKERS) else "ro"
    print("\\t".join([
        str(binding.get("path") or ""),
        role,
        str(binding.get("path_kind") or ""),
        mode,
    ]))
PY
  )
fi

export APPTAINERENV_MORPHIC_CONTAINER=1
export APPTAINERENV_WRITE_PNG="${{WRITE_PNG:-0}}"
export APPTAINERENV_HOME=/tmp
export APPTAINERENV_XDG_CACHE_HOME=/tmp/.cache
export APPTAINERENV_MPLCONFIGDIR=/tmp/matplotlib
export APPTAINERENV_NUMBA_CACHE_DIR=/tmp/numba_cache
export APPTAINERENV_MUDATA="${{MUDATA:-}}"
export APPTAINERENV_OUTPUT_PREFIX="${{OUTPUT_PREFIX:-}}"
export APPTAINERENV_TITLE="${{TITLE:-}}"
exec apptainer exec --cleanenv \\
  "${{bind_args[@]}}" \\
  --pwd "{workdir}" \\
  "$IMAGE" {entrypoint}
"""


def _runtime_status(executable: str, version_args: list[str]) -> dict[str, Any]:
    path = shutil.which(executable)
    if not path:
        return {"available": False, "path": None, "version": None}
    version = None
    try:
        proc = subprocess.run([path, *version_args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc is not None and proc.returncode == 0:
        version = (proc.stdout or proc.stderr or "").strip()
    return {"available": True, "path": path, "version": version}


def _preferred_runtime(available: list[str]) -> str | None:
    for runtime in ("docker", "podman", "apptainer"):
        if runtime in available:
            return runtime
    return available[0] if available else None


def _command_for_runtime(manifest: dict[str, Any], runtime: str | None) -> str | None:
    if not runtime:
        return None
    for launcher in manifest.get("launchers") or []:
        if isinstance(launcher, dict) and str(launcher.get("runtime") or "") == runtime:
            return str(launcher.get("command") or "")
    if runtime in {"docker", "podman"}:
        return "./run.docker.sh"
    if runtime == "apptainer":
        return "./run.apptainer.sh"
    return None


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    if all(ch.isalnum() or ch in "-_./:" for ch in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
