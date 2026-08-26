"""Execution-location profiles for the BioDepot workbench.

The current workbench can only run generated bundles in the API service
environment. This module makes that location explicit and defines the blocked
locations that future remote and scheduler adapters can claim.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

DEFAULT_EXECUTION_LOCATION_ID = "server"


@dataclass(frozen=True)
class ExecutionLocation:
    location_id: str
    kind: str
    label: str
    description: str
    authority: str
    execution_mode: str
    path_visibility: str
    run_strategy: str
    allowed_actions: tuple[str, ...]
    required_connectors: tuple[str, ...] = ()
    scheduler: str | None = None
    metadata: Mapping[str, Any] | None = None
    is_default: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "location_id": self.location_id,
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "authority": self.authority,
            "execution_mode": self.execution_mode,
            "path_visibility": self.path_visibility,
            "run_strategy": self.run_strategy,
            "allowed_actions": list(self.allowed_actions),
            "required_connectors": list(self.required_connectors),
            "scheduler": self.scheduler,
            "metadata": dict(self.metadata or {}),
            "is_default": self.is_default,
        }


@dataclass(frozen=True)
class ExecutionLocationGate:
    action: str
    allowed: bool
    run_blocker: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "allowed": self.allowed, "run_blocker": self.run_blocker}


_BASE_LOCATIONS: dict[str, ExecutionLocation] = {
    "server": ExecutionLocation(
        location_id="server",
        kind="server",
        label="Workbench server",
        description="Run in the workbench API service environment using the generated bundle path.",
        authority="workbench_service",
        execution_mode="server_subprocess",
        path_visibility="server_visible_paths",
        run_strategy="preflight_then_bash_run_sh",
        allowed_actions=("render", "preflight", "execute", "stream_logs", "collect_outputs"),
        metadata={"compatibility_profile": "production", "current_host_role": "server"},
        is_default=True,
    ),
    "local": ExecutionLocation(
        location_id="local",
        kind="local",
        label="Caller local",
        description="Caller-managed workstation or shell; the API can render bundles but cannot run caller-local paths.",
        authority="caller",
        execution_mode="caller_managed_shell",
        path_visibility="caller_visible_paths",
        run_strategy="download_or_copy_bundle_then_run_locally",
        allowed_actions=("render", "download", "caller_run"),
    ),
    "remote_ssh": ExecutionLocation(
        location_id="remote_ssh",
        kind="remote_ssh",
        label="Remote SSH host",
        description="Copy the generated bundle to a configured SSH destination and run the container launcher there.",
        authority="workbench_service",
        execution_mode="ssh_remote_container",
        path_visibility="remote_visible_paths",
        run_strategy="copy_bundle_over_ssh_then_run_container_launcher",
        allowed_actions=("render", "preflight", "execute", "stream_logs", "collect_outputs"),
        required_connectors=("ssh",),
        metadata={"preferred_container_runtime": "docker"},
    ),
    "remote": ExecutionLocation(
        location_id="remote",
        kind="remote",
        label="Remote host or cluster",
        description="Remote host, cluster, or storage location reached through an execution connector.",
        authority="remote_connector",
        execution_mode="remote_dispatch",
        path_visibility="remote_visible_paths",
        run_strategy="submit_to_remote_connector_after_connector_preflight",
        allowed_actions=("render", "preflight_preview", "submit_preview"),
        required_connectors=("remote_executor",),
    ),
    "scheduler_temporal": ExecutionLocation(
        location_id="scheduler_temporal",
        kind="scheduler_temporal",
        label="Local Temporal scheduler",
        description="Stage the generated bundle into local scheduler storage and run it through the BioDepot/BwB Temporal scheduler.",
        authority="workbench_service",
        execution_mode="temporal_scheduler_local",
        path_visibility="scheduler_bundle_storage",
        run_strategy="stage_bundle_then_submit_temporal_workflow",
        allowed_actions=("render", "preflight", "execute", "stream_logs", "collect_outputs"),
        required_connectors=("temporal_scheduler",),
        scheduler="temporal",
        metadata={"scheduler_api_url": "http://127.0.0.1:8000", "scheduler_worker_queue": "worker1"},
    ),
    "scheduler_remote_ssh": ExecutionLocation(
        location_id="scheduler_remote_ssh",
        kind="scheduler_remote_ssh",
        label="Remote SSH via Temporal scheduler",
        description="Stage the generated bundle into scheduler storage and run it on a configured SSH Docker host through Temporal.",
        authority="workbench_service",
        execution_mode="temporal_scheduler_ssh_docker",
        path_visibility="scheduler_bundle_storage",
        run_strategy="stage_bundle_then_submit_temporal_ssh_docker_workflow",
        allowed_actions=("render", "preflight", "execute", "stream_logs", "collect_outputs"),
        required_connectors=("temporal_scheduler", "ssh"),
        scheduler="temporal",
        metadata={"scheduler_api_url": "http://127.0.0.1:8000", "remote_container_runtime": "docker"},
    ),
}

_ALIASES = {
    "": DEFAULT_EXECUTION_LOCATION_ID,
    "default": DEFAULT_EXECUTION_LOCATION_ID,
    "production": DEFAULT_EXECUTION_LOCATION_ID,
    "server": "server",
    "workbench_server": "server",
    "local": "local",
    "caller": "local",
    "client": "local",
    "download": "local",
    "remote_ssh": "remote_ssh",
    "ssh": "remote_ssh",
    "ssh_remote": "remote_ssh",
    "remote": "remote",
    "cluster": "remote",
    "slurm": "remote",
    "hpc": "remote",
    "temporal": "scheduler_temporal",
    "scheduler": "scheduler_temporal",
    "temporal_scheduler": "scheduler_temporal",
    "scheduler_temporal": "scheduler_temporal",
    "scheduler_remote_ssh": "scheduler_remote_ssh",
    "temporal_ssh": "scheduler_remote_ssh",
    "scheduler_ssh": "scheduler_remote_ssh",
    "ssh_scheduler": "scheduler_remote_ssh",
    "remote_ssh_scheduler": "scheduler_remote_ssh",
}

_REQUEST_METADATA_KEYS = {
    "connector_id",
    "remote_host",
    "remote_user",
    "remote_workdir",
    "remote_port",
    "remote_container_runtime",
    "remote_path_overrides",
    "remote_check",
    "path_mapping",
    "scheduler_api_url",
    "scheduler_storage_dir",
    "scheduler_worker_queue",
    "scheduler_worker_cpus",
    "scheduler_worker_mem_mb",
    "scheduler_worker_ram",
    "scheduler_worker_gpus",
    "scheduler_startup_script",
    "scheduler_namespace",
    "task_queue",
    "workflow_type",
}


def list_execution_locations() -> list[dict[str, Any]]:
    return [_BASE_LOCATIONS[key].as_dict() for key in ("server", "local", "remote_ssh", "remote", "scheduler_temporal", "scheduler_remote_ssh")]


def resolve_execution_location(raw: Any = None) -> ExecutionLocation:
    """Resolve a request location/profile into a normalized location contract."""

    metadata: dict[str, Any] = {}
    if raw is None:
        location_key = DEFAULT_EXECUTION_LOCATION_ID
    elif isinstance(raw, str):
        location_key = _alias(raw)
    elif isinstance(raw, Mapping):
        candidate = (
            raw.get("location_id")
            or raw.get("id")
            or raw.get("kind")
            or raw.get("profile")
            or raw.get("execution_profile")
            or DEFAULT_EXECUTION_LOCATION_ID
        )
        location_key = _alias(str(candidate))
        nested_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
        metadata = {key: raw[key] for key in _REQUEST_METADATA_KEYS if key in raw}
        metadata.update({key: nested_metadata[key] for key in _REQUEST_METADATA_KEYS if key in nested_metadata})
    else:
        raise ValueError("execution_location must be a string or object")

    base = _BASE_LOCATIONS.get(location_key)
    if base is None:
        raise ValueError(f"unsupported execution location: {location_key}")
    if metadata:
        merged = {**dict(base.metadata or {}), **metadata}
        return replace(base, metadata=merged)
    return base


def execution_dispatch_for_location(location: ExecutionLocation) -> dict[str, Any]:
    metadata = dict(location.metadata or {})
    if location.kind == "server":
        return {
            "dispatch_kind": "server_subprocess",
            "adapter": "server_subprocess_compat",
            "direct_api_execution": True,
            "durability": "request_scoped",
            "scheduler": None,
        }
    if location.kind == "local":
        return {
            "dispatch_kind": "caller_managed_shell",
            "direct_api_execution": False,
            "durability": "caller_managed",
            "command_hint": "bash run.sh",
        }
    if location.kind == "remote_ssh":
        runtime = str(metadata.get("remote_container_runtime") or metadata.get("preferred_container_runtime") or "docker")
        return {
            "dispatch_kind": "ssh_remote_container",
            "adapter": "ssh_tar_container_compat",
            "direct_api_execution": True,
            "durability": "request_scoped_remote",
            "connector_required": True,
            "connector_id": "ssh",
            "remote_host": metadata.get("remote_host"),
            "remote_user": metadata.get("remote_user"),
            "remote_port": metadata.get("remote_port"),
            "remote_workdir": metadata.get("remote_workdir"),
            "remote_container_runtime": runtime,
            "command_hint": "./run.docker.sh" if runtime in {"docker", "podman"} else "./run.apptainer.sh",
        }
    if location.kind == "remote":
        return {
            "dispatch_kind": "remote_connector",
            "direct_api_execution": False,
            "connector_required": True,
            "connector_id": metadata.get("connector_id"),
            "remote_host": metadata.get("remote_host"),
        }
    if location.kind == "scheduler_temporal":
        return {
            "dispatch_kind": "temporal_workflow",
            "adapter": "temporal_scheduler_local_bundle",
            "direct_api_execution": True,
            "connector_required": False,
            "scheduler": "temporal",
            "api_base_url": metadata.get("scheduler_api_url"),
            "storage_dir": metadata.get("scheduler_storage_dir"),
            "worker_queue": metadata.get("scheduler_worker_queue") or metadata.get("task_queue"),
            "namespace": metadata.get("scheduler_namespace"),
            "task_queue": metadata.get("task_queue"),
            "workflow_type": metadata.get("workflow_type"),
            "durability": "temporal_workflow",
            "command_hint": "submit generated bundle to local Temporal scheduler",
        }
    if location.kind == "scheduler_remote_ssh":
        runtime = str(metadata.get("remote_container_runtime") or "docker")
        return {
            "dispatch_kind": "temporal_ssh_docker_workflow",
            "adapter": "temporal_scheduler_ssh_docker",
            "direct_api_execution": True,
            "connector_required": True,
            "connector_id": "ssh",
            "scheduler": "temporal",
            "api_base_url": metadata.get("scheduler_api_url"),
            "storage_dir": metadata.get("scheduler_storage_dir"),
            "worker_queue": metadata.get("scheduler_worker_queue") or metadata.get("task_queue"),
            "namespace": metadata.get("scheduler_namespace"),
            "task_queue": metadata.get("task_queue"),
            "workflow_type": metadata.get("workflow_type") or "RemoteDockerWorkflow",
            "remote_host": metadata.get("remote_host"),
            "remote_user": metadata.get("remote_user"),
            "remote_port": metadata.get("remote_port"),
            "remote_workdir": metadata.get("remote_workdir"),
            "remote_container_runtime": runtime,
            "durability": "temporal_workflow",
            "command_hint": "submit generated bundle to Temporal SSH Docker workflow",
        }
    return {"dispatch_kind": location.execution_mode, "direct_api_execution": "execute" in location.allowed_actions}


def execution_location_gate(location: ExecutionLocation, action: str = "execute") -> ExecutionLocationGate:
    if location.kind == "remote_ssh" and action == "execute":
        metadata = dict(location.metadata or {})
        missing = [
            field
            for field in ("remote_host", "remote_workdir")
            if not str(metadata.get(field) or "").strip()
        ]
        if missing:
            return ExecutionLocationGate(
                action=action,
                allowed=False,
                run_blocker=f"Remote SSH execution requires {', '.join(missing)}.",
            )
    if location.kind == "scheduler_remote_ssh" and action == "execute":
        metadata = dict(location.metadata or {})
        missing = [
            field
            for field in ("remote_host", "remote_user", "remote_workdir")
            if not str(metadata.get(field) or "").strip()
        ]
        if missing:
            return ExecutionLocationGate(
                action=action,
                allowed=False,
                run_blocker=f"Scheduler SSH execution requires {', '.join(missing)}.",
            )
    if action in location.allowed_actions:
        return ExecutionLocationGate(action=action, allowed=True)
    if location.kind == "local":
        blocker = (
            "The workbench API cannot execute a caller-local bundle. "
            "Render or download the bundle, run it in the local environment, and register outputs separately."
        )
    elif location.kind == "remote":
        blocker = "Remote execution requires a configured remote executor connector before this API can submit the bundle."
    elif location.kind == "scheduler_temporal":
        blocker = "Temporal scheduler execution requires the local scheduler API to be reachable before this API can submit the bundle."
    elif location.kind == "scheduler_remote_ssh":
        blocker = "Temporal SSH execution requires the scheduler API and SSH Docker worker before this API can submit the bundle."
    else:
        blocker = f"Execution location `{location.location_id}` does not allow `{action}`."
    return ExecutionLocationGate(action=action, allowed=False, run_blocker=blocker)


def annotate_preflight_for_location(result: Mapping[str, Any], location: ExecutionLocation) -> dict[str, Any]:
    payload = dict(result)
    payload["execution_location"] = location.as_dict()
    payload["execution_dispatch"] = execution_dispatch_for_location(location)
    gate = execution_location_gate(location, "execute")
    payload["execution_run_gate"] = gate.as_dict()
    if gate.allowed:
        return payload

    blocker = gate.run_blocker or "Selected execution location cannot run through this API path."
    checks = list(payload.get("checks") or [])
    checks.append(
        {
            "check": "execution location supports workbench API execution",
            "status": "fail",
            "location_id": location.location_id,
            "location_kind": location.kind,
        }
    )
    blockers = list(payload.get("blockers") or [])
    _append_unique_blocker(blockers, blocker)
    existing_blocker = str(payload.get("run_blocker") or "").strip()
    run_blockers = _split_blockers(existing_blocker)
    _append_unique_blocker(run_blockers, blocker)
    payload.update(
        {
            "status": "blocked" if payload.get("status") in {"preflight_passed", "inputs_passed"} else payload.get("status", "blocked"),
            "checks": checks,
            "blockers": blockers,
            "location_blocker": blocker,
            "run_blocker": "; ".join(run_blockers),
            "executable_ready": False,
        }
    )
    return payload


def _alias(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in _ALIASES:
        raise ValueError(f"unsupported execution location: {value}")
    return _ALIASES[normalized]


def _split_blockers(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _append_unique_blocker(items: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    key = _blocker_key(text)
    if any(_blocker_key(item) == key for item in items):
        return
    items.append(text)


def _blocker_key(value: str) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    if "caller-local bundle" in text:
        return "caller-local bundle"
    return text
