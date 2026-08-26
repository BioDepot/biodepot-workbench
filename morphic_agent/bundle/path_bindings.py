"""Path-binding manifests for materialized workflow bundles."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PATH_BINDINGS_SCHEMA = "morphic.path_bindings/v0"

_OUTPUT_NAME_PARTS = (
    "output",
    "out_",
    "outdir",
    "out_dir",
    "prefix",
    "report",
    "result",
)


def build_path_bindings(
    graph: dict[str, Any],
    params: dict[str, Any],
    *,
    bundle_dir: Path,
    execution_location: str = "server",
    recipe_payload: dict[str, Any] | None = None,
    params_review_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a concrete path manifest for a materialized bundle."""

    bundle_dir = Path(bundle_dir)
    fields = _schema_fields(graph)
    bindings: list[dict[str, Any]] = []

    for name, field in fields.items():
        value = params.get(name)
        if _is_missing_path_value(value):
            continue
        if field.get("type") == "path":
            bindings.append(_binding_for_value(name, name, value, field, bundle_dir=bundle_dir, execution_location=execution_location))

    reads = params.get("reads")
    reads_field = fields.get("reads") or {
        "name": "reads",
        "type": "array",
        "artifact_type": "paired_fastq",
        "required": True,
    }
    if isinstance(reads, list):
        for index, item in enumerate(reads):
            if not isinstance(item, dict):
                continue
            for mate in ("r1", "r2"):
                value = item.get(mate)
                if _is_missing_path_value(value):
                    continue
                binding_id = f"reads[{index}].{mate}"
                bindings.append(
                    _binding_for_value(
                        binding_id,
                        binding_id,
                        value,
                        reads_field,
                        bundle_dir=bundle_dir,
                        execution_location=execution_location,
                        role="input",
                        artifact_type="fastq",
                    )
                )

    for name in ("output_prefix", "out_file_name_prefix", "counts_matrix", "output_root", "out_dir", "output_dir"):
        if name in fields or _is_missing_path_value(params.get(name)):
            continue
        bindings.append(
            _binding_for_value(
                name,
                name,
                params.get(name),
                {"name": name, "type": "path", "required": False},
                bundle_dir=bundle_dir,
                execution_location=execution_location,
            )
        )

    return {
        "schema": PATH_BINDINGS_SCHEMA,
        "graph_id": graph.get("graph_id"),
        "execution_location": _location_id(execution_location),
        "created_at": _utc_now(),
        "created_from": {
            "recipe_hash": _prefixed_sha256(recipe_payload) if recipe_payload is not None else None,
            "params_review_hash": _prefixed_sha256(params_review_payload) if params_review_payload is not None else None,
        },
        "base_paths": {
            "bundle_dir": ".",
            "workdir": ".",
        },
        "bindings": bindings,
    }


def write_path_bindings(
    bundle_dir: Path,
    graph: dict[str, Any],
    params: dict[str, Any],
    *,
    execution_location: str = "server",
    recipe_payload: dict[str, Any] | None = None,
    params_review_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = build_path_bindings(
        graph,
        params,
        bundle_dir=bundle_dir,
        execution_location=execution_location,
        recipe_payload=recipe_payload,
        params_review_payload=params_review_payload,
    )
    manifests_dir = Path(bundle_dir) / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "path_bindings.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_path_bindings(bundle_dir: Path) -> dict[str, Any] | None:
    path = Path(bundle_dir) / "manifests" / "path_bindings.json"
    if not path.is_file():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def path_bindings_hash(manifest: dict[str, Any]) -> str:
    return _prefixed_sha256(manifest)


def resolve_params_for_location(
    params: dict[str, Any],
    manifest: dict[str, Any] | None,
    *,
    bundle_dir: Path,
    execution_location: str,
) -> dict[str, Any]:
    """Return params with manifest path values applied for the selected location."""

    if not manifest:
        return dict(params)
    location_id = _location_id(execution_location)
    resolved = deepcopy(params)
    bundle_dir = Path(bundle_dir)

    for binding in _manifest_bindings(manifest):
        path_kind = str(binding.get("path_kind") or "")
        if not _path_kind_allowed(path_kind, location_id):
            continue
        param = str(binding.get("param") or binding.get("field") or binding.get("binding_id") or "")
        if not param:
            continue
        raw_path = str(binding.get("path") or "")
        if not raw_path:
            continue
        value = str((bundle_dir / raw_path).resolve()) if path_kind == "bundle_relative" else raw_path
        _set_param_path(resolved, param, value)
    return resolved


def validate_path_bindings_for_location(
    manifest: dict[str, Any] | None,
    *,
    bundle_dir: Path,
    execution_location: str,
) -> dict[str, Any]:
    location_id = _location_id(execution_location)
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    if manifest is None:
        return {
            "valid": True,
            "status": "missing",
            "checks": [{"check": "path bindings manifest present", "status": "not_run"}],
            "blockers": [],
            "path_bindings_hash": None,
        }

    schema_ok = manifest.get("schema") == PATH_BINDINGS_SCHEMA
    checks.append({"check": "path bindings manifest schema", "status": "pass" if schema_ok else "fail"})
    if not schema_ok:
        blockers.append("path bindings manifest has an unsupported schema")

    bindings = _manifest_bindings(manifest)
    checks.append({"check": "path bindings are listed", "status": "pass" if bindings else "not_run", "count": len(bindings)})

    manifest_location = _manifest_location_id(manifest)
    if manifest_location:
        location_matches = manifest_location == location_id
        checks.append(
            {
                "check": "path bindings execution locale matches selected locale",
                "status": "pass" if location_matches else "fail",
                "manifest_location_id": manifest_location,
                "selected_location_id": location_id,
            }
        )
        if not location_matches:
            blockers.append(
                f"path bindings were rendered for `{manifest_location}` execution; "
                f"regenerate the run directory for `{location_id}` or edit manifests/path_bindings.json before running there"
            )
            return {
                "valid": False,
                "status": "blocked",
                "checks": checks,
                "blockers": blockers,
                "path_bindings_hash": path_bindings_hash(manifest),
            }

    for binding in bindings:
        binding_id = str(binding.get("binding_id") or binding.get("param") or "path")
        path_kind = str(binding.get("path_kind") or "")
        allowed = _path_kind_allowed(path_kind, location_id)
        checks.append(
            {
                "check": f"path binding kind allowed: {binding_id}",
                "status": "pass" if allowed else "fail",
                "path_kind": path_kind,
                "location_id": location_id,
            }
        )
        if not allowed:
            blockers.append(f"path binding `{binding_id}` uses `{path_kind}` for `{location_id}` execution")
            continue
        if path_kind == "bundle_relative":
            path = Path(bundle_dir) / str(binding.get("path") or "")
            role = str(binding.get("role") or "")
            if _role_is_output(role):
                parent = path.parent
                existing_parent = parent
                while not existing_parent.exists() and existing_parent.parent != existing_parent:
                    existing_parent = existing_parent.parent
                ok = existing_parent.exists()
                checks.append({"check": f"bundle-relative output parent visible: {binding_id}", "status": "pass" if ok else "fail", "path": str(parent)})
                if not ok:
                    blockers.append(f"bundle-relative output parent is not visible: {binding_id}")
            else:
                ok = path.exists()
                checks.append({"check": f"bundle-relative input visible: {binding_id}", "status": "pass" if ok else "fail", "path": str(path)})
                if location_id in {"server", "remote_ssh"} and not ok:
                    blockers.append(f"bundle-relative input is missing: {binding_id}")
        elif location_id == "local":
            checks.append({"check": f"caller-visible path is caller-managed: {binding_id}", "status": "not_run"})

    return {
        "valid": not blockers,
        "status": "valid" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "path_bindings_hash": path_bindings_hash(manifest),
    }


def path_bindings_response(bundle_dir: Path) -> dict[str, Any]:
    manifest = load_path_bindings(bundle_dir)
    if manifest is None:
        return {"path_bindings_path": None, "path_bindings_hash": None}
    return {
        "path_bindings_path": "manifests/path_bindings.json",
        "path_bindings_hash": path_bindings_hash(manifest),
    }


def _schema_fields(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    schema = graph.get("params_schema") if isinstance(graph.get("params_schema"), dict) else {}
    fields = schema.get("fields") if isinstance(schema.get("fields"), list) else []
    return {str(field.get("name")): field for field in fields if isinstance(field, dict) and field.get("name")}


def _binding_for_value(
    binding_id: str,
    param: str,
    value: Any,
    field: dict[str, Any],
    *,
    bundle_dir: Path,
    execution_location: str,
    role: str | None = None,
    artifact_type: str | None = None,
) -> dict[str, Any]:
    role = role or _role_for_field(binding_id, field)
    manifest_path, path_kind = _manifest_path_and_kind(value, role=role, bundle_dir=bundle_dir, execution_location=execution_location)
    return {
        "binding_id": binding_id,
        "field": str(field.get("name") or param),
        "param": param,
        "role": role,
        "artifact_type": artifact_type or field.get("artifact_type"),
        "path": manifest_path,
        "path_kind": path_kind,
        "required": bool(field.get("required", False)),
        "consumed_by": list(field.get("consumed_by") or []),
    }


def _manifest_path_and_kind(value: Any, *, role: str, bundle_dir: Path, execution_location: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    expanded = Path(raw).expanduser()
    location_id = _location_id(execution_location)
    if location_id == "local":
        external_kind = "caller_visible"
    elif location_id == "remote_ssh":
        external_kind = "remote_visible"
    elif location_id in {"scheduler_temporal", "scheduler_remote_ssh"}:
        external_kind = "scheduler_visible"
    else:
        external_kind = "server_visible"
    if expanded.is_absolute():
        try:
            relative = expanded.resolve().relative_to(bundle_dir.resolve())
            return (relative.as_posix() or "."), "bundle_relative"
        except (OSError, ValueError):
            if location_id in {"local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"} and _role_is_output(role):
                return f"outputs/{expanded.name or 'output'}", "bundle_relative"
            return raw, external_kind
    candidate = bundle_dir / raw
    if candidate.exists():
        try:
            relative = candidate.resolve().relative_to(bundle_dir.resolve())
            return (relative.as_posix() or "."), "bundle_relative"
        except (OSError, ValueError):
            pass
    if _role_is_output(role):
        return raw, "bundle_relative"
    return raw, external_kind


def _role_for_field(name: str, field: dict[str, Any]) -> str:
    lower = name.lower()
    if _role_is_output(lower):
        if "prefix" in lower:
            return "output_prefix"
        return "output"
    artifact_type = str(field.get("artifact_type") or "").lower()
    if artifact_type in {"directory", "output_dir"}:
        return "output"
    return "input"


def _role_is_output(role: str) -> bool:
    lower = role.lower()
    return any(part in lower for part in _OUTPUT_NAME_PARTS)


def _path_kind_allowed(path_kind: str, location_id: str) -> bool:
    if path_kind == "bundle_relative":
        return True
    if location_id in {"scheduler_temporal", "scheduler_remote_ssh"}:
        return False
    if location_id == "local":
        return path_kind == "caller_visible"
    if location_id == "remote_ssh":
        return path_kind == "remote_visible"
    return path_kind == "server_visible"


def _manifest_bindings(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    bindings = manifest.get("bindings")
    return [binding for binding in bindings if isinstance(binding, dict)] if isinstance(bindings, list) else []


def _is_missing_path_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _location_id(value: str) -> str:
    text = str(value or "server").strip().lower().replace("-", "_")
    if text in {"local", "caller", "client", "download"}:
        return "local"
    if text in {"remote_ssh", "ssh", "ssh_remote"}:
        return "remote_ssh"
    if text in {"scheduler_temporal", "temporal", "temporal_scheduler", "scheduler"}:
        return "scheduler_temporal"
    if text in {"scheduler_remote_ssh", "temporal_ssh", "scheduler_ssh", "ssh_scheduler", "remote_ssh_scheduler"}:
        return "scheduler_remote_ssh"
    return "server"


def _manifest_location_id(manifest: dict[str, Any]) -> str | None:
    raw = manifest.get("execution_location")
    if raw is None or str(raw).strip() == "":
        return None
    return _location_id(str(raw))


def _set_param_path(params: dict[str, Any], param: str, value: str) -> None:
    if param.startswith("reads["):
        try:
            prefix, mate = param.split("].", 1)
            index = int(prefix.removeprefix("reads["))
        except (ValueError, IndexError):
            return
        reads = params.setdefault("reads", [])
        if not isinstance(reads, list):
            return
        while len(reads) <= index:
            reads.append({})
        if isinstance(reads[index], dict):
            reads[index][mate] = value
        return
    params[param] = value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prefixed_sha256(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
