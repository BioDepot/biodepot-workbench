"""Nextflow runtime diagnostics used by workflow bundle preflight checks."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shlex
import shutil
import socket
import subprocess
import textwrap
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NEXTFLOW_PREFLIGHT_SCHEMA = "morphic.nextflow_preflight/v0"
NEXTFLOW_EXECUTION_RESULT_SCHEMA = "morphic.nextflow_execution_result/v0"
NEXTFLOW_SCHEDULER_COMMAND_SCHEMA = "morphic.nextflow_scheduler_command/v0"
NEXTFLOW_ARTIFACT_MANIFEST_SCHEMA = "morphic.execution_artifact_manifest/v0"
NEXTFLOW_TEMPORAL_CONFIG_SCHEMA = "morphic.nextflow_temporal_config/v0"
DEFAULT_NEXTFLOW_SOURCE_ROOT = Path(__file__).resolve().parents[2] / ".cache" / "nextflow"
DEFAULT_NEXTFLOW_TEMPORAL_TARGET = "127.0.0.1:7233"
DEFAULT_NEXTFLOW_TEMPORAL_NAMESPACE = "default"
DEFAULT_NEXTFLOW_TEMPORAL_TASK_QUEUE = "nextflow"

NEXTFLOW_CONTAINER_PROFILES = {
    "apptainer": "apptainer",
    "conda": "conda",
    "docker": "docker",
    "podman": "podman",
    "singularity": "singularity",
}

REMOTE_EXECUTION_KINDS = {"remote_ssh", "scheduler_remote_ssh"}
SCHEDULER_EXECUTION_KINDS = {"scheduler_temporal", "scheduler_remote_ssh"}


def nextflow_launch_command(
    *,
    pipeline: str,
    release: str | None = None,
    profile: str | None = None,
    params_file: str = "nf-params.json",
) -> str:
    """Return the reviewable Nextflow command string for a rendered params file."""

    parts = ["nextflow", "run", str(pipeline or "")]
    if release and not _local_pipeline_reference(pipeline):
        parts.extend(["-r", str(release)])
    if profile:
        parts.extend(["-profile", str(profile)])
    parts.extend(["-params-file", params_file])
    return " ".join(shlex.quote(part) for part in parts if str(part).strip())


def nextflow_runtime_preflight(
    *,
    pipeline: str,
    release: str | None,
    profile: str,
    execution_location_kind: str = "server",
) -> dict[str, Any]:
    """Check the Nextflow launcher, profile runtime, and workflow source state."""

    location = str(execution_location_kind or "server")
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    workflow_check = workflow_source_check(pipeline)
    checks.append(workflow_check)
    if workflow_check.get("status") == "fail":
        blockers.append(str(workflow_check.get("blocker")))

    check = command_available_check("nextflow", execution_location_kind=location)
    checks.append(check)
    if check.get("status") == "fail":
        blockers.append(str(check.get("blocker") or "nextflow is not available on PATH"))

    profile_check = profile_runtime_check(profile, execution_location_kind=location)
    checks.append(profile_check)
    if profile_check.get("status") == "fail":
        blockers.append(str(profile_check.get("blocker") or f"selected profile `{profile}` is not available"))

    temporal_preflight = None
    if location == "scheduler_temporal":
        temporal_preflight = nextflow_temporal_preflight()
        checks.extend(temporal_preflight.get("checks") or [])
        blockers.extend(temporal_preflight.get("blockers") or [])

    return {
        "schema": NEXTFLOW_PREFLIGHT_SCHEMA,
        "status": "ready" if not blockers else "blocked",
        "pipeline": pipeline,
        "release": release,
        "profile": profile,
        "execution_location_kind": location,
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(dict.fromkeys(blockers)) if blockers else None,
        "temporal_preflight": temporal_preflight,
        "launch_command": nextflow_launch_command(
            pipeline=pipeline,
            release=release,
            profile=profile,
            params_file="nf-params.json",
        ),
    }


def nextflow_source_root(source_root: str | Path | None = None) -> Path:
    """Return the local Nextflow checkout used for nf-temporal development mode."""

    if source_root is not None:
        return Path(source_root).expanduser()
    return Path(os.environ.get("MORPHIC_NEXTFLOW_SOURCE_ROOT") or DEFAULT_NEXTFLOW_SOURCE_ROOT).expanduser()


def local_nextflow_binary(source_root: str | Path | None = None) -> str:
    """Return a local Nextflow launcher when the source checkout is available."""

    override = str(os.environ.get("MORPHIC_NEXTFLOW_BIN") or "").strip()
    if override:
        return override
    candidate = nextflow_source_root(source_root) / "nextflow"
    return str(candidate) if candidate.is_file() else "nextflow"


def install_local_nf_temporal_plugin(
    nxf_home: str | Path,
    source_root: str | Path | None = None,
) -> Path | None:
    """Install the locally built nf-temporal plugin into a concrete NXF_HOME."""

    root = nextflow_source_root(source_root)
    version = _nf_temporal_version(root)
    if not version:
        return None
    plugin_dir = Path(nxf_home).expanduser() / "plugins" / f"nf-temporal-{version}"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    cached = _cached_nf_temporal_plugin(root, version)
    if cached is not None:
        shutil.copytree(cached, plugin_dir, dirs_exist_ok=True)
        return plugin_dir

    jar = root / "plugins" / "nf-temporal" / "build" / "libs" / f"nf-temporal-{version}.jar"
    libs = root / "plugins" / "nf-temporal" / "build" / "target" / "libs"
    if not jar.is_file() or not libs.is_dir():
        return None

    classes_dir = plugin_dir / "classes"
    lib_dir = plugin_dir / "lib"
    classes_dir.mkdir(exist_ok=True)
    lib_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(jar) as archive:
        archive.extractall(classes_dir)
    for dep in libs.glob("*.jar"):
        shutil.copy2(dep, lib_dir / dep.name)
    return plugin_dir


def nextflow_temporal_env(
    *,
    nxf_home: str | Path,
    temporal_config_path: str | Path | None = None,
    source_root: str | Path | None = None,
    temporal_target: str = DEFAULT_NEXTFLOW_TEMPORAL_TARGET,
    namespace: str = DEFAULT_NEXTFLOW_TEMPORAL_NAMESPACE,
    task_queue: str = DEFAULT_NEXTFLOW_TEMPORAL_TASK_QUEUE,
) -> dict[str, str]:
    """Return environment values for launching Nextflow with nf-temporal."""

    nxf_home_path = Path(nxf_home).expanduser()
    payload = {
        "NXF_HOME": str(nxf_home_path),
        "NXF_PLUGINS_DIR": str(nxf_home_path / "plugins"),
        "NEXTFLOW_BIN": local_nextflow_binary(source_root),
        "MORPHIC_NEXTFLOW_TEMPORAL_TARGET": temporal_target,
        "MORPHIC_NEXTFLOW_TEMPORAL_NAMESPACE": namespace,
        "MORPHIC_NEXTFLOW_TEMPORAL_TASK_QUEUE": task_queue,
    }
    if temporal_config_path is not None:
        payload["NEXTFLOW_CONFIG_FILE"] = str(temporal_config_path)
    return payload


def write_nextflow_temporal_config(
    path: str | Path,
    *,
    source_root: str | Path | None = None,
    temporal_target: str = DEFAULT_NEXTFLOW_TEMPORAL_TARGET,
    namespace: str = DEFAULT_NEXTFLOW_TEMPORAL_NAMESPACE,
    task_queue: str = DEFAULT_NEXTFLOW_TEMPORAL_TASK_QUEUE,
) -> dict[str, Any]:
    """Write a deterministic Nextflow config for the nf-temporal executor."""

    root = nextflow_source_root(source_root)
    version = _nf_temporal_version(root) or "0.1.0"
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        textwrap.dedent(
            f"""\
            /*
             * Generated by Workbench for Nextflow Temporal executor smoke runs.
             */

            plugins {{
                id 'nf-temporal@{version}'
            }}

            process {{
                executor = 'temporal'
            }}

            temporal {{
                target = System.getenv('MORPHIC_NEXTFLOW_TEMPORAL_TARGET') ?: '{temporal_target}'
                namespace = System.getenv('MORPHIC_NEXTFLOW_TEMPORAL_NAMESPACE') ?: '{namespace}'
                taskQueue = System.getenv('MORPHIC_NEXTFLOW_TEMPORAL_TASK_QUEUE') ?: '{task_queue}'
                backend = 'local'
                pollInterval = '5s'
                monitorCapacity = 128
            }}

            report {{
                overwrite = true
            }}

            timeline {{
                overwrite = true
            }}

            trace {{
                overwrite = true
            }}
            """
        ),
        encoding="utf-8",
    )
    return {
        "schema": NEXTFLOW_TEMPORAL_CONFIG_SCHEMA,
        "path": str(config_path),
        "plugin_id": "nf-temporal",
        "plugin_version": version,
        "executor": "temporal",
        "target": temporal_target,
        "namespace": namespace,
        "task_queue": task_queue,
    }


def nextflow_temporal_preflight(
    *,
    source_root: str | Path | None = None,
    nxf_home: str | Path | None = None,
    temporal_target: str | None = None,
    check_target: bool | None = None,
) -> dict[str, Any]:
    """Check local resources needed for Nextflow's Temporal executor."""

    root = nextflow_source_root(source_root)
    target = temporal_target or os.environ.get("MORPHIC_NEXTFLOW_TEMPORAL_TARGET") or DEFAULT_NEXTFLOW_TEMPORAL_TARGET
    should_check_target = _env_truthy("MORPHIC_CHECK_NEXTFLOW_TEMPORAL_TARGET") if check_target is None else check_target
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    source_ok = (root / "gradlew").is_file() and (root / "plugins" / "nf-temporal").is_dir()
    checks.append(
        {
            "check": "local Nextflow source root with nf-temporal",
            "status": "pass" if source_ok else "fail",
            "path": str(root),
        }
    )
    if not source_ok:
        blockers.append(f"local Nextflow source root with nf-temporal is not available: {root}")

    nextflow_bin = Path(local_nextflow_binary(root))
    nextflow_ok = nextflow_bin.is_file() or shutil.which(str(nextflow_bin)) is not None
    checks.append({"check": "Nextflow launcher for Temporal executor", "status": "pass" if nextflow_ok else "fail", "path": str(nextflow_bin)})
    if not nextflow_ok:
        blockers.append("Nextflow launcher for Temporal executor is not available")

    version = _nf_temporal_version(root)
    install_source = _nf_temporal_install_source(root, version)
    checks.append(
        {
            "check": "local nf-temporal plugin install source",
            "status": "pass" if install_source else "fail",
            "plugin_id": "nf-temporal",
            "plugin_version": version,
            "path": str(install_source) if install_source else None,
        }
    )
    if not install_source:
        blockers.append("local nf-temporal plugin build or cache is not available")

    if nxf_home is not None and version:
        installed = Path(nxf_home).expanduser() / "plugins" / f"nf-temporal-{version}"
        checks.append(
            {
                "check": "nf-temporal plugin installed in NXF_HOME",
                "status": "pass" if installed.is_dir() else "warn",
                "path": str(installed),
            }
        )

    if should_check_target:
        target_ok = _tcp_open(target, timeout_seconds=1.0)
        checks.append({"check": "Temporal gRPC target reachable", "status": "pass" if target_ok else "fail", "target": target})
        if not target_ok:
            blockers.append(f"Temporal gRPC target is not reachable: {target}")
    else:
        checks.append({"check": "Temporal gRPC target reachable", "status": "not_run", "target": target})

    return {
        "schema": "morphic.nextflow_temporal_preflight/v0",
        "status": "ready" if not blockers else "blocked",
        "source_root": str(root),
        "nextflow_bin": str(nextflow_bin),
        "temporal_target": target,
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(dict.fromkeys(blockers)) if blockers else None,
    }


def start_local_nextflow_temporal_worker(
    *,
    worker_log: str | Path,
    source_root: str | Path | None = None,
    temporal_target: str = DEFAULT_NEXTFLOW_TEMPORAL_TARGET,
    namespace: str = DEFAULT_NEXTFLOW_TEMPORAL_NAMESPACE,
    task_queue: str = DEFAULT_NEXTFLOW_TEMPORAL_TASK_QUEUE,
    ready_timeout_seconds: int = 45,
) -> subprocess.Popen[str]:
    """Start the local nf-temporal worker from the local Nextflow checkout."""

    root = nextflow_source_root(source_root)
    gradlew = root / "gradlew"
    if not gradlew.is_file():
        raise RuntimeError(f"local Nextflow Gradle wrapper is not available: {gradlew}")

    env = os.environ.copy()
    env.update(
        {
            "TEMPORAL_TARGET": temporal_target,
            "TEMPORAL_NAMESPACE": namespace,
            "TEMPORAL_TASK_QUEUE": task_queue,
            "COLUMNS": "120",
        }
    )
    log_path = Path(worker_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    worker = subprocess.Popen(
        [str(gradlew), ":plugins:nf-temporal:runTemporalWorker", "--console=plain", "-q"],
        cwd=str(root),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    log_handle.close()

    deadline = time.monotonic() + ready_timeout_seconds
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            raise RuntimeError(f"Temporal worker exited early:\n{_read_text(log_path)}")
        text = _read_text(log_path)
        if "worker starting" in text or "WorkerFactory" in text:
            return worker
        time.sleep(1)
    worker.terminate()
    raise RuntimeError(f"Temporal worker did not become ready:\n{_read_text(log_path)}")


def nextflow_artifact_candidate_paths(bundle: Path, params: dict[str, Any]) -> list[Path]:
    """Return expected Nextflow/nf-core output locations for artifact collection."""

    candidates = [
        Path(bundle) / ".nextflow.log",
        Path(bundle) / "manifests" / "nextflow-report.html",
        Path(bundle) / "manifests" / "nextflow-timeline.html",
        Path(bundle) / "manifests" / "nextflow-trace.txt",
    ]
    for key in ("outdir", "out_dir", "output_dir", "publish_dir", "output_root"):
        value = params.get(key)
        if not isinstance(value, (str, Path)):
            continue
        text = str(value).strip()
        if not text:
            continue
        path = Path(text).expanduser()
        candidates.append(path if path.is_absolute() else Path(bundle) / path)
    return candidates


def snapshot_nextflow_artifacts(bundle: str | Path, params: dict[str, Any] | None = None) -> dict[str, dict[str, int]]:
    """Snapshot current Nextflow artifact files before a run."""

    snapshot: dict[str, dict[str, int]] = {}
    for file_path in _iter_nextflow_artifact_files(Path(bundle), params or {}):
        try:
            stat_result = file_path.stat()
        except OSError:
            continue
        snapshot[str(file_path)] = {"mtime_ns": stat_result.st_mtime_ns, "size_bytes": stat_result.st_size}
    return snapshot


def collect_nextflow_artifact_manifest(
    bundle: str | Path,
    params: dict[str, Any] | None = None,
    *,
    before: dict[str, dict[str, int]] | None = None,
    max_files: int = 2000,
) -> dict[str, Any]:
    """Collect standard Nextflow reports, logs, and declared output paths."""

    bundle_path = Path(bundle)
    effective_params = params if params is not None else _load_nextflow_params(bundle_path)
    before = before or {}
    files: list[dict[str, Any]] = []
    for file_path in _iter_nextflow_artifact_files(bundle_path, effective_params, max_files=max_files):
        try:
            stat_result = file_path.stat()
        except OSError:
            continue
        key = str(file_path)
        previous = before.get(key)
        if previous and previous.get("mtime_ns") == stat_result.st_mtime_ns and previous.get("size_bytes") == stat_result.st_size:
            continue
        viewer, media_type = _viewer_for_artifact(file_path)
        role = _nextflow_artifact_role(file_path, bundle_path, effective_params)
        files.append(
            {
                "artifact_id": _artifact_id_for_path(file_path),
                "name": file_path.name,
                "relative_path": _relative_path(file_path, bundle_path),
                "path": str(file_path),
                "role": role,
                "artifact_type": _artifact_type_for_role(role),
                "size_bytes": stat_result.st_size,
                "mtime_ns": stat_result.st_mtime_ns,
                "media_type": media_type,
                "viewer": viewer,
                "viewable": viewer is not None,
            }
        )
    files.sort(key=lambda item: (str(item.get("relative_path") or ""), str(item.get("path") or "")))
    return {
        "schema": NEXTFLOW_ARTIFACT_MANIFEST_SCHEMA,
        "manifest_kind": "nextflow_outputs",
        "bundle_path": str(bundle_path),
        "file_count": len(files),
        "files": files,
    }


def run_nextflow_bundle(
    bundle: str | Path,
    *,
    execution_location_kind: str = "server",
    timeout_seconds: int = 3600,
    extra_args: list[str] | tuple[str, ...] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a rendered Nextflow bundle locally and write execution manifests.

    This executes only an already-rendered bundle. It does not download nf-core
    sources, containers, references, or pipeline assets by itself.
    """

    bundle_path = Path(bundle)
    script = bundle_path / "run.nextflow.sh"
    if not script.is_file():
        raise FileNotFoundError(f"Nextflow bundle is missing run.nextflow.sh: {script}")

    params = _load_nextflow_params(bundle_path)
    before = snapshot_nextflow_artifacts(bundle_path, params)
    command = ["bash", str(script), *[str(item) for item in (extra_args or [])]]
    started_at = _utc_now()
    started = time.monotonic()
    stdout = ""
    stderr = ""
    returncode: int | None
    timed_out = False

    run_env = os.environ.copy()
    if env:
        run_env.update({str(key): str(value) for key, value in env.items()})
    try:
        proc = subprocess.run(
            command,
            cwd=str(bundle_path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=run_env,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_output(exc.stdout)
        stderr = _decode_output(exc.stderr)
        returncode = None
        timed_out = True
    finished_at = _utc_now()
    duration_seconds = round(time.monotonic() - started, 3)

    artifact_manifest = collect_nextflow_artifact_manifest(bundle_path, params, before=before)
    metadata = _nextflow_bundle_metadata(bundle_path, params)
    result = {
        "schema": NEXTFLOW_EXECUTION_RESULT_SCHEMA,
        "status": "failed" if timed_out or returncode != 0 else "completed",
        "failure_kind": "timeout" if timed_out else (None if returncode == 0 else "process_exit"),
        "graph_id": metadata.get("graph_id"),
        "bundle_path": str(bundle_path),
        "execution_location_kind": str(execution_location_kind or "server"),
        "command": command,
        "command_display": " ".join(shlex.quote(part) for part in command),
        "returncode": returncode,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "duration_seconds": duration_seconds,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_tail": _tail_text(stdout),
        "stderr_tail": _tail_text(stderr),
        "pipeline": metadata.get("pipeline"),
        "release": metadata.get("release"),
        "profile": metadata.get("profile"),
        "params_hash": metadata.get("params_hash"),
        "source_manifest_hash": metadata.get("source_manifest_hash"),
        "artifact_manifest": artifact_manifest,
    }
    _write_json(bundle_path / "manifests" / "execution_artifacts.json", artifact_manifest)
    _write_json(bundle_path / "execution_result.json", result)
    return result


def nextflow_scheduler_command_manifest(
    bundle: str | Path,
    *,
    execution_location_kind: str = "scheduler_temporal",
    temporal_config_path: str | Path | None = None,
    temporal_target: str = "127.0.0.1:7233",
    namespace: str = "default",
    task_queue: str = "nextflow",
) -> dict[str, Any]:
    """Return deterministic command metadata for a scheduler-backed Nextflow run."""

    bundle_path = Path(bundle)
    params = _load_nextflow_params(bundle_path)
    metadata = _nextflow_bundle_metadata(bundle_path, params)
    extra_args: list[str] = []
    if temporal_config_path is not None:
        extra_args.extend(["-c", str(temporal_config_path)])
    command = ["bash", "run.nextflow.sh", *extra_args]
    return {
        "schema": NEXTFLOW_SCHEDULER_COMMAND_SCHEMA,
        "graph_id": metadata.get("graph_id"),
        "bundle_path": str(bundle_path),
        "execution_location_kind": str(execution_location_kind or "scheduler_temporal"),
        "scheduler": {
            "kind": "temporal",
            "target": temporal_target,
            "namespace": namespace,
            "task_queue": task_queue,
        },
        "command": command,
        "command_display": " ".join(shlex.quote(part) for part in command),
        "pipeline": metadata.get("pipeline"),
        "release": metadata.get("release"),
        "profile": metadata.get("profile"),
        "params_hash": metadata.get("params_hash"),
        "source_manifest_hash": metadata.get("source_manifest_hash"),
    }


def workflow_source_check(pipeline: str) -> dict[str, Any]:
    """Validate local workflow references while leaving registry names as declared."""

    text = str(pipeline or "").strip()
    if not text:
        return {"check": "Nextflow workflow source declared", "status": "fail", "blocker": "Nextflow pipeline is not declared"}
    if _local_pipeline_reference(text):
        path = Path(text).expanduser()
        ok = path.exists()
        return {
            "check": "local Nextflow workflow source exists",
            "status": "pass" if ok else "fail",
            "path": str(path),
            "blocker": None if ok else f"local Nextflow workflow source does not exist: {path}",
        }
    return {
        "check": "remote Nextflow workflow source declared",
        "status": "pass",
        "pipeline": text,
        "note": "The pipeline source is resolved by Nextflow at launch time.",
    }


def command_available_check(command: str, *, execution_location_kind: str) -> dict[str, Any]:
    """Check a command where the Workbench host is responsible for running it."""

    location = str(execution_location_kind or "server")
    if location in REMOTE_EXECUTION_KINDS:
        return {
            "check": f"{command} available on execution host",
            "status": "not_run",
            "command": command,
            "reason": "checked on the remote execution host",
        }
    if location == "local":
        return {
            "check": f"{command} available for caller-managed local execution",
            "status": "not_run",
            "command": command,
            "reason": "local caller runs preflight outside the Workbench API",
        }

    if command == "nextflow" and location in SCHEDULER_EXECUTION_KINDS:
        candidate = local_nextflow_binary()
        if Path(candidate).is_file():
            path = candidate
        else:
            path = shutil.which(candidate)
    else:
        path = shutil.which(command)
    if not path:
        return {
            "check": f"{command} available",
            "status": "fail",
            "command": command,
            "path": None,
            "blocker": f"{command} is not available on PATH",
        }
    try:
        proc = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    ok = proc is not None and proc.returncode == 0
    return {
        "check": f"{command} available",
        "status": "pass" if ok else "fail",
        "command": command,
        "path": path,
        "version": _version_text(proc) if proc is not None else None,
        "blocker": None if ok else f"{command} failed its version check",
    }


def profile_runtime_check(profile: str, *, execution_location_kind: str) -> dict[str, Any]:
    """Check local container/runtime availability implied by common Nextflow profiles."""

    runtime = NEXTFLOW_CONTAINER_PROFILES.get(str(profile or "").strip().lower())
    if runtime is None:
        return {
            "check": "selected Nextflow profile has local runtime mapping",
            "status": "not_run",
            "profile": profile,
        }
    location = str(execution_location_kind or "server")
    if location in REMOTE_EXECUTION_KINDS | SCHEDULER_EXECUTION_KINDS:
        return {
            "check": f"container runtime available for profile `{profile}`",
            "status": "not_run",
            "profile": profile,
            "runtime": runtime,
            "reason": "runtime is checked on the execution host",
        }
    if location == "local":
        return {
            "check": f"container runtime available for caller-managed profile `{profile}`",
            "status": "not_run",
            "profile": profile,
            "runtime": runtime,
            "reason": "local caller runs runtime preflight outside the Workbench API",
        }
    path = shutil.which(runtime)
    return {
        "check": f"container runtime available for profile `{profile}`",
        "status": "pass" if path else "fail",
        "profile": profile,
        "runtime": runtime,
        "path": path,
        "blocker": None if path else f"selected profile `{profile}` requires `{runtime}` on PATH",
    }


def _local_pipeline_reference(pipeline: str) -> bool:
    text = str(pipeline or "").strip()
    return text.startswith("/") or text.startswith("./") or text.startswith("../")


def _version_text(proc: subprocess.CompletedProcess[str]) -> str:
    return " ".join(part.strip() for part in [proc.stdout, proc.stderr] if part and part.strip())[:500]


def _nf_temporal_version(source_root: Path) -> str | None:
    version_path = source_root / "plugins" / "nf-temporal" / "VERSION"
    if not version_path.is_file():
        return None
    version = version_path.read_text(encoding="utf-8").strip()
    return version or None


def _cached_nf_temporal_plugin(source_root: Path, version: str) -> Path | None:
    candidates = [
        source_root / "validation" / "temporal-nfcore" / ".nextflow" / "plugins" / f"nf-temporal-{version}",
        source_root / "validation" / "temporal-mini" / "plugin-store" / f"nf-temporal-{version}",
    ]
    for candidate in candidates:
        if (candidate / "classes" / "META-INF" / "MANIFEST.MF").is_file() and (candidate / "lib").is_dir():
            return candidate
    return None


def _nf_temporal_install_source(source_root: Path, version: str | None) -> Path | None:
    if not version:
        return None
    cached = _cached_nf_temporal_plugin(source_root, version)
    if cached is not None:
        return cached
    jar = source_root / "plugins" / "nf-temporal" / "build" / "libs" / f"nf-temporal-{version}.jar"
    libs = source_root / "plugins" / "nf-temporal" / "build" / "target" / "libs"
    if jar.is_file() and libs.is_dir():
        return jar
    return None


def _tcp_open(target: str, *, timeout_seconds: float) -> bool:
    host, _, port_text = str(target or "").rpartition(":")
    if not host or not port_text:
        return False
    sock = socket.socket()
    sock.settimeout(timeout_seconds)
    try:
        sock.connect((host, int(port_text)))
    except (OSError, ValueError):
        return False
    finally:
        sock.close()
    return True


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _iter_nextflow_artifact_files(
    bundle: Path,
    params: dict[str, Any],
    *,
    max_files: int = 2000,
) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for candidate in nextflow_artifact_candidate_paths(bundle, params):
        for file_path in _files_under(candidate):
            key = str(file_path)
            if key in seen:
                continue
            seen.add(key)
            files.append(file_path)
            if len(files) >= max_files:
                return sorted(files, key=lambda item: str(item))
    return sorted(files, key=lambda item: str(item))


def _files_under(candidate: Path) -> list[Path]:
    if candidate.is_file():
        return [candidate]
    if not candidate.is_dir():
        return []
    return sorted([path for path in candidate.rglob("*") if path.is_file()], key=lambda item: str(item))


def _load_nextflow_params(bundle: Path) -> dict[str, Any]:
    params_path = bundle / "nf-params.json"
    if not params_path.is_file():
        return {}
    try:
        loaded = json.loads(params_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _nextflow_bundle_metadata(bundle: Path, params: dict[str, Any]) -> dict[str, Any]:
    graph = _load_json_object(bundle / "workflow_graph.json")
    manifest = _load_json_object(bundle / "manifests" / "bundle_manifest.json")
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    return {
        "graph_id": graph.get("graph_id") or manifest.get("graph_id"),
        "pipeline": manifest.get("pipeline") or runtime.get("pipeline_name") or runtime.get("pipeline"),
        "release": manifest.get("release") or runtime.get("release"),
        "profile": params.get("profile") or manifest.get("profile"),
        "params_hash": manifest.get("params_hash") or _prefixed_sha256(params),
        "source_manifest_hash": manifest.get("source_manifest_hash"),
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _viewer_for_artifact(path: Path) -> tuple[str | None, str]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html", "text/html"
    if suffix == ".json":
        return "json", "application/json"
    if suffix in {".txt", ".log", ".tsv", ".csv", ".md"}:
        return "text", mimetypes.guess_type(path.name)[0] or "text/plain"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        return "image", mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return None, mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _nextflow_artifact_role(path: Path, bundle: Path, params: dict[str, Any]) -> str:
    if path.name == ".nextflow.log":
        return "nextflow_log"
    if path.name == "nextflow-report.html":
        return "nextflow_report"
    if path.name == "nextflow-timeline.html":
        return "nextflow_timeline"
    if path.name == "nextflow-trace.txt":
        return "nextflow_trace"
    if _under_declared_output(path, bundle, params):
        return "workflow_output"
    return "nextflow_artifact"


def _artifact_type_for_role(role: str) -> str:
    return {
        "nextflow_log": "log",
        "nextflow_report": "report",
        "nextflow_timeline": "timeline",
        "nextflow_trace": "trace",
        "workflow_output": "workflow_output",
    }.get(role, "artifact")


def _under_declared_output(path: Path, bundle: Path, params: dict[str, Any]) -> bool:
    for key in ("outdir", "out_dir", "output_dir", "publish_dir", "output_root"):
        value = params.get(key)
        if not isinstance(value, (str, Path)):
            continue
        output = Path(value).expanduser()
        if not output.is_absolute():
            output = bundle / output
        try:
            path.relative_to(output)
        except ValueError:
            continue
        return True
    return False


def _relative_path(path: Path, bundle: Path) -> str:
    try:
        return str(path.relative_to(bundle))
    except ValueError:
        return path.name


def _artifact_id_for_path(path: Path) -> str:
    return f"artifact_{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:16]}"


def _prefixed_sha256(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _tail_text(value: str, *, limit: int = 4000) -> str:
    text = str(value or "")
    return text[-limit:]


def _decode_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
