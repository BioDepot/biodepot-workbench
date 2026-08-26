"""Temporal scheduler execution adapter for generated Workbench bundles."""

from __future__ import annotations

import copy
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from morphic_agent.bundle.containers import load_container_manifest
from morphic_agent.content.paths import scheduler_startup_script

DEFAULT_SCHEDULER_API_URL = "http://127.0.0.1:8000"
DEFAULT_SCHEDULER_STORAGE_DIR = "/tmp/temporal-scheduler-local"
DEFAULT_SCHEDULER_WORKER_QUEUE = "worker1"
DEFAULT_SCHEDULER_INPUT_COPY_MAX_BYTES = 512 * 1024 * 1024


def _default_scheduler_startup_script() -> str:
    return scheduler_startup_script()


@dataclass(frozen=True)
class SchedulerLocalTarget:
    location_id: str = "scheduler_temporal"
    api_base_url: str = DEFAULT_SCHEDULER_API_URL
    storage_dir: Path = Path(DEFAULT_SCHEDULER_STORAGE_DIR)
    worker_queue: str = DEFAULT_SCHEDULER_WORKER_QUEUE
    worker_cpus: int = 2
    worker_mem_mb: int = 4096
    worker_gpus: int = 0
    poll_interval_seconds: float = 2.0
    startup_script: str = field(default_factory=_default_scheduler_startup_script)
    remote_host: str = ""
    remote_user: str = ""
    remote_workdir: str = ""
    remote_port: int = 22
    remote_container_runtime: str = "docker"
    remote_check: bool = True


def scheduler_local_target(location: Any = None) -> SchedulerLocalTarget:
    metadata = dict(getattr(location, "metadata", None) or {})
    location_id = str(getattr(location, "location_id", "") or getattr(location, "kind", "") or "scheduler_temporal")
    remote_port = _parse_int(metadata.get("remote_port"), 22)
    remote_host = str(metadata.get("remote_host") or "").strip()
    remote_user = str(metadata.get("remote_user") or "").strip()
    remote_queue = _ssh_docker_queue(remote_user=remote_user, remote_host=remote_host, remote_port=remote_port)
    return SchedulerLocalTarget(
        location_id=location_id,
        api_base_url=str(
            metadata.get("scheduler_api_url")
            or os.environ.get("MORPHIC_SCHEDULER_API_URL")
            or os.environ.get("MORPHIC_TEMPORAL_SCHEDULER_URL")
            or DEFAULT_SCHEDULER_API_URL
        ).rstrip("/"),
        storage_dir=Path(
            str(
                metadata.get("scheduler_storage_dir")
                or os.environ.get("MORPHIC_SCHEDULER_STORAGE_DIR")
                or os.environ.get("SCHED_STORAGE_DIR")
                or DEFAULT_SCHEDULER_STORAGE_DIR
            )
        ).expanduser(),
        worker_queue=str(
            metadata.get("scheduler_worker_queue")
            or metadata.get("task_queue")
            or (remote_queue if location_id == "scheduler_remote_ssh" else "")
            or os.environ.get("MORPHIC_SCHEDULER_WORKER_QUEUE")
            or os.environ.get("LOCAL_WORKER_QUEUE")
            or DEFAULT_SCHEDULER_WORKER_QUEUE
        ),
        worker_cpus=_parse_int(metadata.get("scheduler_worker_cpus") or os.environ.get("MORPHIC_SCHEDULER_WORKER_CPUS") or os.environ.get("WORKER_CPUS"), 2),
        worker_mem_mb=_parse_mem_mb(
            metadata.get("scheduler_worker_mem_mb")
            or metadata.get("scheduler_worker_ram")
            or os.environ.get("MORPHIC_SCHEDULER_WORKER_MEM_MB")
            or os.environ.get("WORKER_RAM"),
            4096,
        ),
        worker_gpus=_parse_int(metadata.get("scheduler_worker_gpus") or os.environ.get("MORPHIC_SCHEDULER_WORKER_GPUS") or os.environ.get("WORKER_GPUS"), 0),
        startup_script=str(metadata.get("scheduler_startup_script") or scheduler_startup_script()),
        remote_host=remote_host,
        remote_user=remote_user,
        remote_workdir=str(metadata.get("remote_workdir") or "").strip(),
        remote_port=remote_port,
        remote_container_runtime=str(metadata.get("remote_container_runtime") or "docker").strip().lower() or "docker",
        remote_check=not (str(metadata.get("remote_check", True)).strip().lower() in {"0", "false", "no", "off"}),
    )


def localize_bundle_manifest_for_scheduler(bundle: Path, location: Any = None) -> dict[str, Any] | None:
    """Copy server-readable inputs into the bundle and make scheduler paths bundle-relative."""

    manifest_path = Path(bundle) / "manifests" / "path_bindings.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return None
    target = scheduler_local_target(location)
    localized = localize_path_manifest_for_scheduler(manifest, target)
    localized = stage_server_inputs_for_scheduler(Path(bundle), localized, target)
    manifest_path.write_text(json.dumps(localized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return localized


def localize_path_manifest_for_scheduler(manifest: dict[str, Any], target: SchedulerLocalTarget) -> dict[str, Any]:
    localized = copy.deepcopy(manifest)
    localized["execution_location"] = target.location_id
    localized["scheduler_destination"] = {
        "api_base_url": target.api_base_url,
        "storage_dir": str(target.storage_dir),
        "worker_queue": target.worker_queue,
    }
    if target.location_id == "scheduler_remote_ssh":
        localized["remote_destination"] = {
            "host": target.remote_host,
            "user": target.remote_user,
            "workdir": target.remote_workdir,
            "port": target.remote_port,
        }
    for binding in localized.get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        role = str(binding.get("role") or "")
        if _is_output_role(role):
            raw_path = str(binding.get("path") or "").strip()
            if str(binding.get("path_kind") or "") != "bundle_relative" or Path(raw_path).expanduser().is_absolute():
                binding["path"] = _scheduler_output_path(binding)
                binding["path_kind"] = "bundle_relative"
                binding["localized_for_scheduler"] = True
        elif str(binding.get("path_kind") or "") in {"server_visible", "caller_visible", "remote_visible", "scheduler_visible"}:
            binding["path_kind"] = "scheduler_visible"
    return localized


def stage_server_inputs_for_scheduler(bundle: Path, manifest: dict[str, Any], target: SchedulerLocalTarget) -> dict[str, Any]:
    localized = copy.deepcopy(manifest)
    max_bytes = _scheduler_input_copy_max_bytes()
    remaining_bytes = max_bytes
    staged: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    inputs_dir = Path(bundle) / "inputs"

    for binding in localized.get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        binding_id = str(binding.get("binding_id") or binding.get("param") or binding.get("field") or "path")
        role = str(binding.get("role") or "")
        path_kind = str(binding.get("path_kind") or "")
        raw_path = str(binding.get("path") or "").strip()
        if _is_output_role(role) or path_kind == "bundle_relative" or not raw_path:
            continue
        source = _server_source_path(raw_path)
        if source is None or not source.exists():
            skipped.append(
                {
                    "binding_id": binding_id,
                    "path": raw_path,
                    "server_path": str(source) if source is not None else None,
                    "reason": "missing_server_path",
                    "message": "The Workbench server cannot read this input; copy it into the bundle or mount it into scheduler storage.",
                }
            )
            continue
        size_bytes = _path_size_bytes(source, limit=max(remaining_bytes, 0))
        if size_bytes is None:
            skipped.append(
                {
                    "binding_id": binding_id,
                    "path": raw_path,
                    "server_path": str(source),
                    "reason": "unreadable_server_path",
                    "message": "The Workbench server could not inspect this input.",
                }
            )
            continue
        if size_bytes > remaining_bytes:
            skipped.append(
                {
                    "binding_id": binding_id,
                    "path": raw_path,
                    "server_path": str(source),
                    "reason": "copy_limit_exceeded",
                    "size_bytes": size_bytes,
                    "max_bytes": max_bytes,
                    "message": (
                        "Input is larger than the scheduler packet copy limit; move it into scheduler-visible storage "
                        "or raise MORPHIC_SCHEDULER_INPUT_COPY_MAX_BYTES."
                    ),
                }
            )
            continue
        relative = Path("inputs") / _safe_path_component(binding_id) / source.name
        destination = inputs_dir / _safe_path_component(binding_id) / source.name
        _copy_path(source, destination)
        remaining_bytes -= size_bytes
        binding["path"] = relative.as_posix()
        binding["path_kind"] = "bundle_relative"
        binding["staged_for_scheduler"] = True
        binding["staged_from"] = str(source)
        staged.append(
            {
                "binding_id": binding_id,
                "source_path": str(source),
                "bundle_path": relative.as_posix(),
                "size_bytes": size_bytes,
            }
        )

    if staged or skipped:
        localized["scheduler_input_staging"] = {
            "strategy": "copy_server_readable_inputs_into_scheduler_bundle",
            "max_bytes": max_bytes,
            "staged": staged,
            "skipped": skipped,
            "storage_dir": str(target.storage_dir),
        }
    return localized


def scheduler_preflight(
    *,
    bundle: Path | None,
    location: Any,
    path_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    target = scheduler_local_target(location)
    if target.location_id == "scheduler_remote_ssh":
        return scheduler_remote_ssh_preflight(bundle=bundle, location=location, path_manifest=path_manifest)

    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    api_check = _scheduler_api_check(target)
    checks.append(api_check)
    if api_check["status"] != "pass":
        blockers.append(
            "Temporal scheduler API is not reachable. Start the local scheduler stack with "
            f"`{target.startup_script}` or set MORPHIC_SCHEDULER_API_URL."
        )

    storage_ready = _storage_dir_ready(target.storage_dir)
    checks.append(
        {
            "check": "scheduler storage directory writable",
            "status": "pass" if storage_ready else "fail",
            "path": str(target.storage_dir),
        }
    )
    if not storage_ready:
        blockers.append(f"scheduler storage directory is not writable: {target.storage_dir}")

    docker_path = shutil.which("docker")
    checks.append({"check": "host docker client available for scheduler worker", "status": "pass" if docker_path else "fail", "path": docker_path})
    if not docker_path:
        blockers.append("docker client is not installed on the Workbench server")

    image = _container_image(bundle)
    checks.append({"check": "container image declared", "status": "pass" if image else "fail", "image": image})
    if not image:
        blockers.append("bundle is missing a container image declaration")
    elif docker_path:
        image_ok = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=15).returncode == 0
        checks.append({"check": "container image available to local Docker", "status": "pass" if image_ok else "warn", "image": image})

    staging = _scheduler_input_staging_status(path_manifest)
    checks.extend(staging["checks"])
    blockers.extend(staging["blockers"])

    if bundle is not None:
        run_sh = Path(bundle) / "run.sh"
        checks.append({"check": "bundle contains run.sh", "status": "pass" if run_sh.is_file() else "fail", "path": str(run_sh)})
        if not run_sh.is_file():
            blockers.append("bundle is missing run.sh")

    return {
        "schema": "morphic.scheduler_preflight/v0",
        "status": "preflight_passed" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(blockers) if blockers else None,
        "scheduler": _target_payload(target),
    }


def scheduler_remote_ssh_preflight(
    *,
    bundle: Path | None,
    location: Any,
    path_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    target = scheduler_local_target(location)
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    api_check = _scheduler_api_check(target)
    checks.append(api_check)
    if api_check["status"] != "pass":
        blockers.append(
            "Temporal scheduler API is not reachable. Start the local scheduler stack with "
            f"`{target.startup_script}` or set MORPHIC_SCHEDULER_API_URL."
        )
    elif not _scheduler_api_has_route(target, "/start_ssh_docker_workflow"):
        checks.append({"check": "scheduler SSH Docker workflow endpoint available", "status": "fail", "url": target.api_base_url})
        blockers.append("Temporal scheduler API does not expose /start_ssh_docker_workflow; rebuild/restart the scheduler API.")
    else:
        checks.append({"check": "scheduler SSH Docker workflow endpoint available", "status": "pass", "url": target.api_base_url})

    storage_ready = _storage_dir_ready(target.storage_dir)
    checks.append(
        {
            "check": "scheduler staging directory writable",
            "status": "pass" if storage_ready else "fail",
            "path": str(target.storage_dir),
        }
    )
    if not storage_ready:
        blockers.append(f"scheduler staging directory is not writable: {target.storage_dir}")

    missing = []
    if not target.remote_host:
        missing.append("remote_host")
    if not target.remote_user:
        missing.append("remote_user")
    if not target.remote_workdir:
        missing.append("remote_workdir")
    for field in ("remote_host", "remote_user", "remote_workdir"):
        value = getattr(target, field)
        checks.append({"check": f"{field} provided", "status": "pass" if str(value or "").strip() else "fail", field: value})
    if missing:
        blockers.append(f"Scheduler SSH execution requires {', '.join(missing)}.")
    runtime_ok = target.remote_container_runtime == "docker"
    checks.append(
        {
            "check": "scheduler SSH container runtime is Docker",
            "status": "pass" if runtime_ok else "fail",
            "remote_container_runtime": target.remote_container_runtime,
        }
    )
    if not runtime_ok:
        blockers.append("Scheduler SSH execution currently supports Docker remote hosts only.")

    ssh_path = shutil.which("ssh")
    rsync_path = shutil.which("rsync")
    checks.append({"check": "local ssh client available", "status": "pass" if ssh_path else "fail", "path": ssh_path})
    checks.append({"check": "local rsync client available", "status": "pass" if rsync_path else "fail", "path": rsync_path})
    if not ssh_path:
        blockers.append("ssh client is not installed on the Workbench server")
    if not rsync_path:
        blockers.append("rsync client is not installed on the Workbench server")

    image = _container_image(bundle)
    checks.append({"check": "container image declared", "status": "pass" if image else "fail", "image": image})
    if not image:
        blockers.append("bundle is missing a container image declaration")

    staging = _scheduler_input_staging_status(path_manifest)
    checks.extend(staging["checks"])
    blockers.extend(staging["blockers"])

    if bundle is not None:
        run_sh = Path(bundle) / "run.sh"
        checks.append({"check": "bundle contains run.sh", "status": "pass" if run_sh.is_file() else "fail", "path": str(run_sh)})
        if not run_sh.is_file():
            blockers.append("bundle is missing run.sh")
    else:
        checks.append({"check": "bundle_path provided for scheduler SSH execution", "status": "fail"})
        blockers.append("bundle_path is required for scheduler SSH preflight")

    if target.remote_check and target.remote_host and target.remote_user and target.remote_workdir and ssh_path:
        remote_check = _run_scheduler_remote_ssh_check(target, image=image)
        checks.extend(remote_check["checks"])
        blockers.extend(remote_check["blockers"])

    return {
        "schema": "morphic.scheduler_remote_ssh_preflight/v0",
        "status": "preflight_passed" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(blockers) if blockers else None,
        "scheduler": _target_payload(target),
    }


def run_scheduler_bundle(
    *,
    bundle: Path,
    location: Any,
    timeout: int,
) -> dict[str, Any]:
    target = scheduler_local_target(location)
    bundle = Path(bundle)
    image = _container_image(bundle)
    if not image:
        raise RuntimeError("bundle is missing a container image declaration")
    run_id = _scheduler_run_id(bundle)
    staged_bundle = target.storage_dir / run_id / "singularity_data" / "bundle"
    if staged_bundle.exists():
        shutil.rmtree(staged_bundle)
    staged_bundle.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, staged_bundle, symlinks=True)

    payload = _workflow_payload(run_id=run_id, image=image, target=target)
    started = _post_json(f"{target.api_base_url}/start_workflow", payload, timeout=20)
    workflow_id = str(started.get("workflow_id") or "")
    temporal_run_id = str(started.get("run_id") or "")
    if not workflow_id:
        raise RuntimeError(f"scheduler did not return workflow_id: {started}")
    _post_json(
        f"{target.api_base_url}/add_worker_to_workflow",
        {
            "workflow_id": workflow_id,
            "worker_queue": target.worker_queue,
            "worker_cpus": target.worker_cpus,
            "worker_mem_mb": target.worker_mem_mb,
            "worker_gpus": target.worker_gpus,
        },
        timeout=20,
    )
    final_status = _poll_workflow_status(target, workflow_id=workflow_id, run_id=temporal_run_id, timeout=timeout)
    if staged_bundle.is_dir():
        shutil.copytree(staged_bundle, bundle, dirs_exist_ok=True)
    stdout = _scheduler_stdout(final_status)
    stderr = ""
    workflow_status = str(final_status.get("workflow_status") or "")
    returncode = 0 if workflow_status == "Finished" else 1
    result_path = bundle / "execution_result.json"
    if returncode == 0 and not result_path.is_file():
        result_path.write_text(
            json.dumps(
                {
                    "schema": "morphic.scheduler_execution_result/v0",
                    "status": "completed",
                    "graph_id": _graph_id(bundle),
                    "scheduler": {
                        "workflow_id": workflow_id,
                        "run_id": temporal_run_id,
                        "bundle_run_id": run_id,
                        "api_base_url": target.api_base_url,
                        "worker_queue": target.worker_queue,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "scheduler": {
            "workflow_id": workflow_id,
            "run_id": temporal_run_id,
            "bundle_run_id": run_id,
            "api_base_url": target.api_base_url,
            "storage_dir": str(target.storage_dir),
            "worker_queue": target.worker_queue,
        },
        "final_status": final_status,
        "staged_bundle": str(staged_bundle),
    }


def run_scheduler_remote_ssh_bundle(
    *,
    bundle: Path,
    location: Any,
    timeout: int,
) -> dict[str, Any]:
    target = scheduler_local_target(location)
    bundle = Path(bundle)
    image = _container_image(bundle)
    if not image:
        raise RuntimeError("bundle is missing a container image declaration")
    if not target.remote_host or not target.remote_user or not target.remote_workdir:
        raise RuntimeError("scheduler SSH execution requires remote_host, remote_user, and remote_workdir")

    run_id = _scheduler_run_id(bundle)
    packet_dir = target.storage_dir / run_id / "ssh_packet"
    staged_bundle = packet_dir / "bundle"
    download_dir = target.storage_dir / run_id / "ssh_output"
    if packet_dir.exists():
        shutil.rmtree(packet_dir)
    if download_dir.exists():
        shutil.rmtree(download_dir)
    packet_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, staged_bundle, symlinks=True)
    localize_bundle_manifest_for_scheduler(staged_bundle, location)

    command = (
        "set -euo pipefail; "
        "cd bundle; "
        "bash run.sh; "
        "cd ..; "
        "mkdir -p output/bundle; "
        "cp -a bundle/. output/bundle/"
    )
    payload = {
        "config": {
            "executors": {
                "ssh_docker": {
                    "ip_addr": target.remote_host,
                    "user": target.remote_user,
                    "storage_dir": target.remote_workdir,
                    "port": target.remote_port,
                }
            }
        },
        "task_queue": target.worker_queue,
        "job": {
            "image": image,
            "cmd": ["bash", "-lc", command],
            "input_files": {str(packet_dir) + "/": "."},
            "use_gpu": target.worker_gpus > 0,
            "gpu_device": "",
            "env": _remote_scheduler_env(),
            "timeout_seconds": timeout,
            "local_output_dir": str(download_dir),
            "cleanup": True,
        },
    }
    started = _post_json(f"{target.api_base_url}/start_ssh_docker_workflow", payload, timeout=20)
    workflow_id = str(started.get("workflow_id") or "")
    temporal_run_id = str(started.get("run_id") or "")
    if not workflow_id:
        raise RuntimeError(f"scheduler did not return workflow_id: {started}")

    final_status = _poll_ssh_docker_workflow_status(target, workflow_id=workflow_id, run_id=temporal_run_id, timeout=timeout)
    returned_bundle = download_dir / "bundle"
    if returned_bundle.is_dir():
        shutil.copytree(returned_bundle, bundle, dirs_exist_ok=True)
    stdout = _scheduler_remote_stdout(final_status)
    stderr = ""
    workflow_status = str(final_status.get("workflow_status") or "")
    returncode = 0 if workflow_status == "Finished" else 1
    result_path = bundle / "execution_result.json"
    if returncode == 0 and not result_path.is_file():
        result_path.write_text(
            json.dumps(
                {
                    "schema": "morphic.scheduler_remote_ssh_execution_result/v0",
                    "status": "completed",
                    "graph_id": _graph_id(bundle),
                    "scheduler": {
                        "workflow_id": workflow_id,
                        "run_id": temporal_run_id,
                        "bundle_run_id": run_id,
                        "api_base_url": target.api_base_url,
                        "worker_queue": target.worker_queue,
                    },
                    "remote": {
                        "host": target.remote_host,
                        "user": target.remote_user,
                        "workdir": target.remote_workdir,
                        "port": target.remote_port,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "scheduler": {
            "workflow_id": workflow_id,
            "run_id": temporal_run_id,
            "bundle_run_id": run_id,
            "api_base_url": target.api_base_url,
            "storage_dir": str(target.storage_dir),
            "worker_queue": target.worker_queue,
        },
        "remote": {
            "host": target.remote_host,
            "user": target.remote_user,
            "workdir": target.remote_workdir,
            "port": target.remote_port,
        },
        "final_status": final_status,
        "staged_bundle": str(staged_bundle),
        "download_dir": str(download_dir),
    }


def _workflow_payload(*, run_id: str, image: str, target: SchedulerLocalTarget) -> dict[str, Any]:
    command = (
        "bash -lc 'set -euo pipefail; "
        "cd /data/bundle; "
        "bash run.sh; "
        "printf \"%s\\n\" \"scheduler-run-completed\" > /tmp/output/scheduler_result.txt'"
    )
    return {
        "use_singularity": False,
        "workflow_def": {
            "run_id": run_id,
            "use_local_storage": True,
            "nodes": [
                {
                    "id": 0,
                    "title": "Workbench local scheduler bundle",
                    "description": "Run a generated Workbench bundle through the local Temporal scheduler.",
                    "image_name": image,
                    "command": [command],
                    "arg_types": {},
                    "parameters": {
                        "useScheduler": True,
                        "useGpu": False,
                        "iterate": False,
                        "nWorkers": 1,
                        "runMode": 2,
                        "repeat": False,
                        "exportGraphics": False,
                        "controlAreaVisible": True,
                        "__version__": 1,
                        "inputConnectionsStore": {},
                        "triggerReady": {},
                        "runTriggers": [],
                        "iterateSettings": {"iterableAttrs": [], "nWorkers": 1},
                        "optionsChecked": {},
                    },
                    "required_parameters": [],
                    "options_checked": {},
                    "cores": target.worker_cpus,
                    "mem_mb": target.worker_mem_mb,
                    "gpus": target.worker_gpus,
                    "slots": 1,
                    "async": False,
                    "barrier_for": None,
                    "iterate": False,
                    "iterate_settings": {"iterableAttrs": [], "nWorkers": 1},
                    "static_env": {},
                    "port_mappings": [],
                    "port_vars": None,
                }
            ],
            "links": [],
        },
    }


def _poll_workflow_status(target: SchedulerLocalTarget, *, workflow_id: str, run_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = _post_json(
            f"{target.api_base_url}/workflow_status",
            {"workflow_id": workflow_id, "run_id": run_id} if run_id else {"workflow_id": workflow_id},
            timeout=20,
        )
        workflow_status = str(last_status.get("workflow_status") or "")
        if workflow_status in {"Finished", "Failed", "Cancelled", "Terminated", "TimedOut"}:
            return last_status
        time.sleep(target.poll_interval_seconds)
    raise subprocess.TimeoutExpired(f"scheduler workflow {workflow_id}", timeout)


def _poll_ssh_docker_workflow_status(target: SchedulerLocalTarget, *, workflow_id: str, run_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] = {}
    payload = {"workflow_id": workflow_id, "run_id": run_id} if run_id else {"workflow_id": workflow_id}
    while time.monotonic() < deadline:
        last_status = _post_json(f"{target.api_base_url}/ssh_docker_workflow_status", payload, timeout=20)
        workflow_status = str(last_status.get("workflow_status") or "")
        if workflow_status in {"Finished", "Failed", "Canceled", "Cancelled", "Terminated", "TimedOut"}:
            return last_status
        time.sleep(target.poll_interval_seconds)
    raise subprocess.TimeoutExpired(f"scheduler SSH Docker workflow {workflow_id}", timeout)


def _scheduler_stdout(status: dict[str, Any]) -> str:
    parts: list[str] = []
    node_statuses = status.get("node_statuses") if isinstance(status.get("node_statuses"), dict) else {}
    for node_id in sorted(node_statuses):
        node = node_statuses.get(node_id)
        if not isinstance(node, dict):
            continue
        logs = node.get("logs") if isinstance(node.get("logs"), dict) else {}
        for key in sorted(logs):
            parts.append(str(logs[key]))
    if not parts:
        parts.append(json.dumps(status, indent=2, sort_keys=True))
    return "".join(parts)


def _scheduler_remote_stdout(status: dict[str, Any]) -> str:
    result = status.get("result") if isinstance(status.get("result"), dict) else {}
    logs = str(result.get("logs") or "")
    if logs:
        return logs
    return json.dumps(status, indent=2, sort_keys=True)


def _scheduler_input_staging_status(path_manifest: dict[str, Any] | None) -> dict[str, Any]:
    staging = path_manifest.get("scheduler_input_staging") if isinstance(path_manifest, dict) else None
    if not isinstance(staging, dict):
        return {"checks": [], "blockers": []}
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    for item in [entry for entry in staging.get("staged") or [] if isinstance(entry, dict)]:
        checks.append(
            {
                "check": f"server input staged into scheduler bundle: {item.get('binding_id') or 'path'}",
                "status": "pass",
                "source_path": item.get("source_path"),
                "bundle_path": item.get("bundle_path"),
                "size_bytes": item.get("size_bytes"),
            }
        )
    for item in [entry for entry in staging.get("skipped") or [] if isinstance(entry, dict)]:
        binding_id = str(item.get("binding_id") or "path")
        message = str(item.get("message") or "Input was not staged into the scheduler bundle.")
        checks.append(
            {
                "check": f"server input staged into scheduler bundle: {binding_id}",
                "status": "fail",
                "reason": item.get("reason"),
                "path": item.get("path"),
                "server_path": item.get("server_path"),
                "size_bytes": item.get("size_bytes"),
                "max_bytes": item.get("max_bytes") or staging.get("max_bytes"),
            }
        )
        blockers.append(f"scheduler input `{binding_id}` was not copied into the bundle: {message}")
    return {"checks": checks, "blockers": blockers}


def _scheduler_api_check(target: SchedulerLocalTarget) -> dict[str, Any]:
    try:
        _get_json(f"{target.api_base_url}/openapi.json", timeout=5)
    except Exception as exc:
        return {"check": "Temporal scheduler API reachable", "status": "fail", "url": target.api_base_url, "message": str(exc)}
    return {"check": "Temporal scheduler API reachable", "status": "pass", "url": target.api_base_url}


def _scheduler_api_has_route(target: SchedulerLocalTarget, route: str) -> bool:
    try:
        payload = _get_json(f"{target.api_base_url}/openapi.json", timeout=5)
    except Exception:
        return False
    paths = payload.get("paths") if isinstance(payload, dict) else {}
    return isinstance(paths, dict) and route in paths


def _post_json(url: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
    loaded = json.loads(data) if data.strip() else {}
    return loaded if isinstance(loaded, dict) else {"payload": loaded}


def _get_json(url: str, *, timeout: int) -> dict[str, Any]:
    request = Request(url, method="GET")
    with urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
    loaded = json.loads(data) if data.strip() else {}
    return loaded if isinstance(loaded, dict) else {"payload": loaded}


def _storage_dir_ready(path: Path) -> bool:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        probe = Path(path) / f".morphic-scheduler-probe-{uuid.uuid4().hex}"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _container_image(bundle: Path | None) -> str:
    if bundle is None:
        return ""
    try:
        manifest = load_container_manifest(Path(bundle))
    except (OSError, json.JSONDecodeError):
        return ""
    return str((manifest or {}).get("image", {}).get("reference") or "")


def _graph_id(bundle: Path) -> str:
    try:
        payload = json.loads((Path(bundle) / "workflow_graph.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("graph_id") or "")


def _scheduler_run_id(bundle: Path) -> str:
    graph_id = _safe_path_component(_graph_id(bundle) or Path(bundle).name)
    return f"morphic-{graph_id}-{uuid.uuid4().hex[:10]}"


def _run_scheduler_remote_ssh_check(target: SchedulerLocalTarget, *, image: str) -> dict[str, Any]:
    commands = [
        f"mkdir -p {shlex.quote(target.remote_workdir)}",
        "command -v bash >/dev/null",
        "command -v rsync >/dev/null",
        "command -v docker >/dev/null",
        "docker info --format '{{.ID}}' >/dev/null",
    ]
    image_check: dict[str, Any] | None = None
    if image:
        commands.append(f"docker image inspect {shlex.quote(image)} >/dev/null 2>&1 || true")
        image_check = {"check": "remote Docker image may need pull", "status": "warn", "image": image}
    proc = subprocess.run(
        [*_ssh_args(target), "set -euo pipefail; " + "; ".join(commands)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    checks = [
        {
            "check": "remote SSH Docker readiness check",
            "status": "pass" if proc.returncode == 0 else "fail",
            "remote_host": target.remote_host,
            "remote_workdir": target.remote_workdir,
            "stderr_tail": _tail(proc.stderr),
        }
    ]
    if image_check is not None:
        checks.append(image_check)
    blockers = [] if proc.returncode == 0 else [f"remote SSH Docker readiness check failed for {target.remote_host}: {_tail(proc.stderr) or _tail(proc.stdout) or proc.returncode}"]
    return {"checks": checks, "blockers": blockers}


def _ssh_args(target: SchedulerLocalTarget) -> list[str]:
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
    ]
    if target.remote_port and target.remote_port != 22:
        args.extend(["-p", str(target.remote_port)])
    args.append(f"{target.remote_user}@{target.remote_host}")
    return args


def _ssh_docker_queue(*, remote_user: str, remote_host: str, remote_port: int) -> str:
    if not remote_user or not remote_host:
        return ""
    return f"{remote_user}@{remote_host}:{int(remote_port or 22)}"


def _remote_scheduler_env() -> dict[str, str]:
    return {
        "HOME": "/tmp",
        "WRITE_PNG": "0",
        "MORPHIC_EXECUTION_LOCATION": "scheduler_remote_ssh",
    }


def _scheduler_output_path(binding: Mapping[str, Any]) -> str:
    raw_path = str(binding.get("path") or "").strip()
    name = Path(raw_path).expanduser().name if raw_path else ""
    binding_id = str(binding.get("binding_id") or binding.get("param") or binding.get("field") or "output")
    return f"outputs/{name or _safe_path_component(binding_id)}"


def _server_source_path(raw_path: str) -> Path:
    expanded = Path(raw_path).expanduser()
    return expanded if expanded.is_absolute() else _server_repo_root() / expanded


def _server_repo_root() -> Path:
    from morphic_agent.content.paths import recipes_tutorials_root

    return recipes_tutorials_root()


def _path_size_bytes(path: Path, *, limit: int) -> int | None:
    try:
        if path.is_file():
            return path.stat().st_size
        if not path.is_dir():
            return None
    except OSError:
        return None
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
                if total > limit:
                    return total
    except OSError:
        return None
    return total


def _copy_path(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _scheduler_input_copy_max_bytes() -> int:
    raw = str(os.environ.get("MORPHIC_SCHEDULER_INPUT_COPY_MAX_BYTES") or "").strip()
    if not raw:
        return DEFAULT_SCHEDULER_INPUT_COPY_MAX_BYTES
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_SCHEDULER_INPUT_COPY_MAX_BYTES


def _safe_path_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value or ""))
    return (cleaned.strip("._") or "path")[:80]


def _is_output_role(role: str) -> bool:
    lower = role.lower()
    return any(part in lower for part in ("output", "out_", "outdir", "out_dir", "prefix", "report", "result"))


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_mem_mb(value: Any, default: int) -> int:
    text = str(value or "").strip().lower().replace(" ", "")
    if not text:
        return default
    multiplier = 1
    if text.endswith("gb") or text.endswith("g"):
        multiplier = 1024
        text = text.removesuffix("gb").removesuffix("g")
    elif text.endswith("mb") or text.endswith("m"):
        text = text.removesuffix("mb").removesuffix("m")
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return default


def _target_payload(target: SchedulerLocalTarget) -> dict[str, Any]:
    payload = {
        "location_id": target.location_id,
        "api_base_url": target.api_base_url,
        "storage_dir": str(target.storage_dir),
        "worker_queue": target.worker_queue,
        "worker_cpus": target.worker_cpus,
        "worker_mem_mb": target.worker_mem_mb,
        "worker_gpus": target.worker_gpus,
        "startup_script": target.startup_script,
    }
    if target.location_id == "scheduler_remote_ssh":
        payload["remote"] = {
            "host": target.remote_host,
            "user": target.remote_user,
            "workdir": target.remote_workdir,
            "port": target.remote_port,
            "container_runtime": target.remote_container_runtime,
            "check_remote": target.remote_check,
        }
    return payload


def _tail(value: str, limit: int = 500) -> str:
    text = str(value or "")
    return text[-limit:] if len(text) > limit else text


def scheduler_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        return f"HTTP {exc.code}: {body or exc.reason}"
    if isinstance(exc, URLError):
        return str(exc.reason)
    return str(exc)
