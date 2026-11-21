"""SSH execution adapter for generated Workbench bundles."""

from __future__ import annotations

import copy
import io
import posixpath
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULT_REMOTE_INPUT_COPY_MAX_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class RemoteSshTarget:
    host: str
    user: str | None
    workdir: str
    port: int | None = None
    container_runtime: str = "docker"
    check_remote: bool = True
    path_overrides: Mapping[str, str] | None = None

    @property
    def hostspec(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


def validate_ssh_name(value: str, label: str) -> str:
    """Reject host or user values that ssh could parse as options or that hide extra arguments."""
    if value.startswith("-"):
        raise ValueError(f"{label} must not start with '-'")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{label} must not contain whitespace or control characters")
    return value


def remote_ssh_target(location: Any) -> RemoteSshTarget:
    metadata = dict(getattr(location, "metadata", None) or {})
    host = str(metadata.get("remote_host") or "").strip()
    workdir = str(metadata.get("remote_workdir") or "").strip()
    if not host:
        raise ValueError("remote_host is required for remote SSH execution")
    if not workdir:
        raise ValueError("remote_workdir is required for remote SSH execution")
    validate_ssh_name(host, "remote_host")
    validate_ssh_name(str(metadata.get("remote_user") or "").strip(), "remote_user")
    runtime = str(metadata.get("remote_container_runtime") or metadata.get("preferred_container_runtime") or "docker").strip().lower()
    if runtime not in {"docker", "podman", "apptainer", "shell"}:
        raise ValueError("remote_container_runtime must be docker, podman, apptainer, or shell")
    port = metadata.get("remote_port")
    try:
        normalized_port = int(port) if port not in {None, ""} else None
    except (TypeError, ValueError) as exc:
        raise ValueError("remote_port must be an integer") from exc
    raw_check = metadata.get("remote_check", True)
    return RemoteSshTarget(
        host=host,
        user=str(metadata.get("remote_user") or "").strip() or None,
        workdir=workdir,
        port=normalized_port,
        container_runtime=runtime,
        check_remote=not (str(raw_check).strip().lower() in {"0", "false", "no", "off"}),
        path_overrides=_normalize_path_overrides(metadata.get("remote_path_overrides") or metadata.get("path_mapping")),
    )


def remote_ssh_preflight(
    *,
    bundle: Path,
    location: Any,
    path_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    target: RemoteSshTarget | None = None
    try:
        target = remote_ssh_target(location)
    except ValueError as exc:
        blockers.append(str(exc))

    ssh_path = shutil.which("ssh")
    checks.append({"check": "local ssh client available", "status": "pass" if ssh_path else "fail", "path": ssh_path})
    if not ssh_path:
        blockers.append("ssh client is not installed on the Workbench server")

    if target is not None:
        effective_manifest = localize_path_manifest_for_remote(path_manifest, target) if path_manifest is not None else None
        checks.append({"check": "remote_host provided", "status": "pass", "remote_host": target.host})
        checks.append({"check": "remote_workdir provided", "status": "pass", "remote_workdir": target.workdir})
        launcher = _launcher_for_runtime(bundle, target.container_runtime)
        checks.append(
            {
                "check": "bundle contains selected remote launcher",
                "status": "pass" if launcher.is_file() else "fail",
                "path": str(launcher),
                "remote_container_runtime": target.container_runtime,
            }
        )
        if not launcher.is_file():
            blockers.append(f"bundle is missing launcher for remote runtime `{target.container_runtime}`")

        if effective_manifest is not None:
            staging_status = _remote_input_staging_status(effective_manifest)
            checks.extend(staging_status["checks"])
            blockers.extend(staging_status["blockers"])
            checks.extend(_remote_path_override_checks(effective_manifest, target))

        if target.check_remote and ssh_path:
            remote_check = _run_ssh_check(target, effective_manifest)
            checks.extend(remote_check["checks"])
            blockers.extend(remote_check["blockers"])

    return {
        "schema": "morphic.remote_ssh_preflight/v0",
        "status": "preflight_passed" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(blockers) if blockers else None,
        "remote": _target_payload(target),
    }


def run_remote_ssh_bundle(
    *,
    bundle: Path,
    location: Any,
    timeout: int,
) -> dict[str, Any]:
    target = remote_ssh_target(location)
    bundle = Path(bundle)
    with tempfile.TemporaryDirectory(prefix="morphic-remote-ssh-") as tmp:
        staged = Path(tmp) / bundle.name
        shutil.copytree(bundle, staged, symlinks=True)
        localize_bundle_manifest(staged, location)
        _upload_bundle(staged, target, timeout=timeout)
        proc = _execute_remote_bundle(target, timeout=timeout)
        copy_back = _download_bundle(target, bundle, timeout=timeout)
        stderr = "\n".join(part for part in [proc.stderr, copy_back.get("stderr", "")] if part)
        returncode = proc.returncode
        if copy_back.get("status") != "copied_back" and returncode == 0:
            returncode = 1
        return {
            "returncode": returncode,
            "stdout": proc.stdout or "",
            "stderr": stderr,
            "remote": _target_payload(target),
            "remote_copy_back": copy_back,
        }


def localize_bundle_manifest(bundle: Path, location: Any) -> dict[str, Any] | None:
    manifest_path = Path(bundle) / "manifests" / "path_bindings.json"
    if not manifest_path.is_file():
        return None
    target = remote_ssh_target(location)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return None
    localized = localize_path_manifest_for_remote(manifest, target)
    localized = stage_server_inputs_for_remote(Path(bundle), localized, target)
    manifest_path.write_text(json.dumps(localized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return localized


def localize_path_manifest_for_remote(manifest: dict[str, Any], target: RemoteSshTarget) -> dict[str, Any]:
    localized = copy.deepcopy(manifest)
    localized["execution_location"] = "remote_ssh"
    localized["remote_destination"] = {
        "host": target.host,
        "user": target.user,
        "workdir": target.workdir,
    }
    overrides = dict(target.path_overrides or {})
    for binding in localized.get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        override = _override_for_binding(binding, overrides)
        if override is not None:
            binding["path"] = override
            binding["path_kind"] = "bundle_relative" if not Path(override).expanduser().is_absolute() else "remote_visible"
        elif str(binding.get("path_kind") or "") in {"server_visible", "caller_visible"}:
            binding["path_kind"] = "remote_visible"
    return localized


def stage_server_inputs_for_remote(bundle: Path, manifest: dict[str, Any], target: RemoteSshTarget) -> dict[str, Any]:
    """Copy server-readable inputs into the SSH packet when no remote override is provided."""

    localized = copy.deepcopy(manifest)
    max_bytes = _remote_input_copy_max_bytes()
    remaining_bytes = max_bytes
    staged: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    overrides = dict(target.path_overrides or {})
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
        if _override_for_binding(binding, overrides) is not None:
            continue
        source = _server_source_path(raw_path)
        if source is None:
            skipped.append(
                {
                    "binding_id": binding_id,
                    "path": raw_path,
                    "reason": "unsupported_server_path",
                    "message": "Only regular files and directories can be staged into an SSH bundle.",
                }
            )
            continue
        if not source.exists():
            skipped.append(
                {
                    "binding_id": binding_id,
                    "path": raw_path,
                    "server_path": str(source),
                    "reason": "missing_server_path",
                    "message": "The Workbench server cannot read this input; provide remote_path_overrides or place the file on shared storage.",
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
                    "message": "The Workbench server could not inspect this input; provide remote_path_overrides or fix server permissions.",
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
                        "Input is larger than the SSH packet copy limit; provide remote_path_overrides, use shared storage, "
                        "or raise MORPHIC_REMOTE_SSH_INPUT_COPY_MAX_BYTES."
                    ),
                }
            )
            continue

        relative = Path("inputs") / _safe_path_component(binding_id) / source.name
        destination = Path(bundle) / relative
        _copy_path(source, destination)
        remaining_bytes -= size_bytes
        binding["path"] = relative.as_posix()
        binding["path_kind"] = "bundle_relative"
        binding["staged_for_remote_ssh"] = True
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
        localized["remote_input_staging"] = {
            "strategy": "copy_server_readable_inputs_into_ssh_bundle",
            "max_bytes": max_bytes,
            "staged": staged,
            "skipped": skipped,
        }
    return localized


def _run_ssh_check(target: RemoteSshTarget, path_manifest: dict[str, Any] | None) -> dict[str, Any]:
    commands = [
        f"mkdir -p {_shell_quote(target.workdir)}",
        "command -v tar >/dev/null",
        "command -v bash >/dev/null",
    ]
    if target.container_runtime == "podman":
        commands.append("command -v podman >/dev/null")
    elif target.container_runtime == "docker":
        commands.append("command -v docker >/dev/null")
    elif target.container_runtime == "apptainer":
        commands.append("command -v apptainer >/dev/null")
    for path in _remote_input_paths(path_manifest):
        commands.append(f"test -e {_shell_quote(path)}")
    for path in _remote_output_parents(path_manifest):
        commands.append(f"mkdir -p {_shell_quote(path)}")
    proc = subprocess.run(
        [*_ssh_args(target), "set -euo pipefail; " + "; ".join(commands)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    check = {
        "check": "remote ssh readiness check",
        "status": "pass" if proc.returncode == 0 else "fail",
        "remote_host": target.host,
        "remote_workdir": target.workdir,
        "stderr_tail": _tail(proc.stderr),
    }
    blockers = [] if proc.returncode == 0 else [f"remote SSH readiness check failed for {target.host}: {_tail(proc.stderr) or _tail(proc.stdout) or proc.returncode}"]
    return {"checks": [check], "blockers": blockers}


def _upload_bundle(staged: Path, target: RemoteSshTarget, *, timeout: int) -> None:
    payload = _tar_directory(staged)
    remote_command = f"set -euo pipefail; rm -rf {_shell_quote(target.workdir)}; mkdir -p {_shell_quote(target.workdir)}; tar -xzf - -C {_shell_quote(target.workdir)}"
    proc = subprocess.run([*_ssh_args(target), remote_command], input=payload, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"remote bundle upload failed: {_tail(proc.stderr.decode(errors='replace'))}")


def _execute_remote_bundle(target: RemoteSshTarget, *, timeout: int) -> subprocess.CompletedProcess[str]:
    command = _remote_run_command(target)
    return subprocess.run([*_ssh_args(target), command], capture_output=True, text=True, timeout=timeout)


def _download_bundle(target: RemoteSshTarget, bundle: Path, *, timeout: int) -> dict[str, Any]:
    remote_command = f"set -euo pipefail; tar -czf - -C {_shell_quote(target.workdir)} ."
    proc = subprocess.run([*_ssh_args(target), remote_command], capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        return {"status": "failed", "stderr": _tail(proc.stderr.decode(errors="replace"))}
    try:
        _extract_tar(proc.stdout, bundle)
    except (RuntimeError, OSError, tarfile.TarError, EOFError) as exc:
        return {"status": "failed", "stderr": _tail(f"remote copy-back extraction failed: {exc}")}
    return {"status": "copied_back", "stderr": _tail(proc.stderr.decode(errors="replace"))}


def _remote_run_command(target: RemoteSshTarget) -> str:
    if target.container_runtime == "shell":
        launcher = "bash run.sh"
    elif target.container_runtime == "apptainer":
        launcher = "./run.apptainer.sh"
    elif target.container_runtime == "podman":
        launcher = "CONTAINER_RUNTIME=podman ./run.docker.sh"
    else:
        launcher = "./run.docker.sh"
    return f"set -euo pipefail; cd {_shell_quote(target.workdir)}; {launcher}"


def _launcher_for_runtime(bundle: Path, runtime: str) -> Path:
    if runtime == "shell":
        return Path(bundle) / "run.sh"
    if runtime == "apptainer":
        return Path(bundle) / "run.apptainer.sh"
    return Path(bundle) / "run.docker.sh"


def _remote_path_override_checks(path_manifest: dict[str, Any], target: RemoteSshTarget) -> list[dict[str, Any]]:
    overrides = dict(target.path_overrides or {})
    checks: list[dict[str, Any]] = []
    if overrides:
        checks.append({"check": "remote path overrides provided", "status": "pass", "count": len(overrides)})
    bindings = [binding for binding in path_manifest.get("bindings") or [] if isinstance(binding, dict)]
    for binding in bindings:
        role = str(binding.get("role") or "")
        path_kind = str(binding.get("path_kind") or "")
        path = str(_override_for_binding(binding, overrides) or binding.get("path") or "")
        if _is_output_role(role) or path_kind == "bundle_relative":
            continue
        checks.append(
            {
                "check": f"remote-visible input path declared: {binding.get('binding_id') or binding.get('param') or 'path'}",
                "status": "pass" if Path(path).expanduser().is_absolute() else "warn",
                "path": path,
            }
        )
    return checks


def _remote_input_staging_status(path_manifest: dict[str, Any]) -> dict[str, Any]:
    staging = path_manifest.get("remote_input_staging") if isinstance(path_manifest, dict) else None
    if not isinstance(staging, dict):
        return {"checks": [], "blockers": []}
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    staged = [item for item in staging.get("staged") or [] if isinstance(item, dict)]
    skipped = [item for item in staging.get("skipped") or [] if isinstance(item, dict)]
    for item in staged:
        checks.append(
            {
                "check": f"server input staged into SSH bundle: {item.get('binding_id') or 'path'}",
                "status": "pass",
                "source_path": item.get("source_path"),
                "bundle_path": item.get("bundle_path"),
                "size_bytes": item.get("size_bytes"),
            }
        )
    for item in skipped:
        binding_id = str(item.get("binding_id") or "path")
        reason = str(item.get("reason") or "not_staged")
        message = str(item.get("message") or "Input was not staged into the SSH bundle.")
        checks.append(
            {
                "check": f"server input staged into SSH bundle: {binding_id}",
                "status": "fail",
                "reason": reason,
                "path": item.get("path"),
                "server_path": item.get("server_path"),
                "size_bytes": item.get("size_bytes"),
                "max_bytes": item.get("max_bytes") or staging.get("max_bytes"),
            }
        )
        blockers.append(f"remote SSH input `{binding_id}` was not copied into the bundle: {message}")
    return {"checks": checks, "blockers": blockers}


def _remote_input_paths(path_manifest: dict[str, Any] | None) -> list[str]:
    paths: list[str] = []
    for binding in (path_manifest or {}).get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        role = str(binding.get("role") or "")
        path_kind = str(binding.get("path_kind") or "")
        path = str(binding.get("path") or "")
        if _is_output_role(role) or path_kind == "bundle_relative" or not path:
            continue
        if Path(path).expanduser().is_absolute():
            paths.append(path)
    return paths


def _remote_output_parents(path_manifest: dict[str, Any] | None) -> list[str]:
    paths: list[str] = []
    for binding in (path_manifest or {}).get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        role = str(binding.get("role") or "")
        path_kind = str(binding.get("path_kind") or "")
        path = str(binding.get("path") or "")
        if not _is_output_role(role) or path_kind == "bundle_relative" or not path:
            continue
        expanded = Path(path).expanduser()
        if expanded.is_absolute():
            paths.append(str(expanded.parent))
    return paths


def _normalize_path_overrides(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, Mapping):
        return {str(key): str(value) for key, value in raw.items() if str(key).strip() and str(value).strip()}
    if isinstance(raw, list):
        result: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("binding_id") or item.get("param") or item.get("field") or "").strip()
            value = str(item.get("remote_path") or item.get("path") or "").strip()
            if key and value:
                result[key] = value
        return result
    return {}


def _remote_input_copy_max_bytes() -> int:
    raw = str(os.environ.get("MORPHIC_REMOTE_SSH_INPUT_COPY_MAX_BYTES") or "").strip()
    if not raw:
        return DEFAULT_REMOTE_INPUT_COPY_MAX_BYTES
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_REMOTE_INPUT_COPY_MAX_BYTES


def _server_source_path(raw_path: str) -> Path | None:
    expanded = Path(raw_path).expanduser()
    source = expanded if expanded.is_absolute() else _server_repo_root() / expanded
    try:
        if source.is_file() or source.is_dir():
            return source
    except OSError:
        return source
    return source


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


def _safe_path_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value or ""))
    return (cleaned.strip("._") or "path")[:80]


def _override_for_binding(binding: Mapping[str, Any], overrides: Mapping[str, str]) -> str | None:
    for key in (binding.get("binding_id"), binding.get("param"), binding.get("field")):
        text = str(key or "").strip()
        if text and text in overrides:
            return str(overrides[text])
    return None


def _tar_directory(directory: Path) -> bytes:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for item in sorted(Path(directory).iterdir(), key=lambda path: path.name):
            archive.add(item, arcname=item.name, recursive=True)
    return payload.getvalue()


def _extract_tar(payload: bytes, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    root = directory.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        links: set[str] = set()
        for member in members:
            name = posixpath.normpath(member.name)
            if member.name.startswith("/") or ".." in member.name.split("/"):
                raise RuntimeError("remote copy-back archive contains unsafe paths")
            if any(name == link or name.startswith(link + "/") for link in links):
                raise RuntimeError("remote copy-back archive writes through a symlink")
            if member.issym():
                # In-tree relative links (for example Nextflow publishDir) are fine.
                linkname = member.linkname
                joined = posixpath.normpath(posixpath.join(posixpath.dirname(name), linkname))
                if not linkname or linkname.startswith("/") or joined == ".." or joined.startswith("../"):
                    raise RuntimeError("remote copy-back archive contains unsafe symlinks")
                links.add(name)
                continue
            if not (member.isreg() or member.isdir()):
                raise RuntimeError("remote copy-back archive contains links or special files")
            target = (directory / member.name).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeError("remote copy-back archive contains unsafe paths") from exc
        archive.extractall(directory, members=members)


def _ssh_args(target: RemoteSshTarget) -> list[str]:
    args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if target.port:
        args.extend(["-p", str(target.port)])
    validate_ssh_name(target.host, "remote_host")
    validate_ssh_name(target.user or "", "remote_user")
    args.extend(["--", target.hostspec])
    return args


def _target_payload(target: RemoteSshTarget | None) -> dict[str, Any] | None:
    if target is None:
        return None
    return {
        "host": target.host,
        "user": target.user,
        "workdir": target.workdir,
        "port": target.port,
        "container_runtime": target.container_runtime,
        "check_remote": target.check_remote,
        "path_overrides": dict(target.path_overrides or {}),
    }


def _is_output_role(role: str) -> bool:
    lower = role.lower()
    return any(part in lower for part in ("output", "out_", "outdir", "out_dir", "prefix", "report", "result"))


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _tail(text: str, limit: int = 2000) -> str:
    text = str(text or "")
    return text[-limit:]
