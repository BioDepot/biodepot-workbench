"""Reviewable bundle renderer and preflight diagnostics for nf-core pipelines."""

from __future__ import annotations

import hashlib
import json
import shlex
import stat
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from morphic_agent.bundle.path_bindings import load_path_bindings, validate_path_bindings_for_location, write_path_bindings
from morphic_agent.execution.nextflow import (
    nextflow_runtime_preflight,
    nextflow_scheduler_command_manifest,
    write_nextflow_temporal_config,
)
from morphic_agent.graph.params import validate_graph_params

NFCORE_BUNDLE_MANIFEST_SCHEMA = "morphic.nfcore_bundle_manifest/v0"
NFCORE_CONTAINER_MANIFEST_SCHEMA = "morphic.nfcore_container_manifest/v0"
NFCORE_PATH_CANDIDATES_SCHEMA = "morphic.nfcore_path_binding_candidates/v0"

def is_nfcore_pipeline_graph(graph: dict[str, Any]) -> bool:
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    return runtime.get("kind") == "nfcore_pipeline" or graph.get("materialization_status") == "runnable_nextflow_bundle"


def normalize_nfcore_params(graph: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Return params plus declared defaults, omitting absent optional nulls."""

    schema = graph.get("params_schema") if isinstance(graph.get("params_schema"), dict) else {}
    fields = schema.get("fields") if isinstance(schema.get("fields"), list) else []
    normalized: dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        name = str(field["name"])
        if name in params:
            normalized[name] = params[name]
        elif "default" in field:
            normalized[name] = field["default"]
    for name, value in sorted(params.items(), key=lambda item: str(item[0])):
        normalized.setdefault(str(name), value)
    return normalized


def materialize_nfcore_pipeline_bundle(
    graph: dict[str, Any],
    out_root: str | Path,
    *,
    params: dict[str, Any],
    execution_location: str = "server",
) -> Path:
    """Render a reviewable nf-core Nextflow launch bundle without running it."""

    if not is_nfcore_pipeline_graph(graph):
        raise ValueError("graph is not an nf-core pipeline graph")

    root = Path(out_root)
    bundle = root / _safe_graph_id(str(graph.get("graph_id") or "nfcore_pipeline"))
    manifests = bundle / "manifests"
    bundle.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(exist_ok=True)

    normalized_params = normalize_nfcore_params(graph, params)
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    source_manifest = graph.get("source_manifest") if isinstance(graph.get("source_manifest"), dict) else {}
    params_review_payload = {
        "schema": "morphic.nfcore_params_review/v0",
        "graph_id": graph.get("graph_id"),
        "params": normalized_params,
    }
    recipe_payload = {
        "schema": "morphic.nfcore_pipeline_recipe/v0",
        "graph_id": graph.get("graph_id"),
        "title": graph.get("title"),
        "runtime": runtime,
        "source_manifest": source_manifest,
        "materialization_status": graph.get("materialization_status"),
    }
    bundle_manifest = {
        "schema": NFCORE_BUNDLE_MANIFEST_SCHEMA,
        "graph_id": graph.get("graph_id"),
        "created_at": _utc_now(),
        "pipeline": runtime.get("pipeline_name") or runtime.get("pipeline"),
        "release": runtime.get("release"),
        "entrypoint": runtime.get("entrypoint"),
        "params_file": "nf-params.json",
        "launch_script": "run.nextflow.sh",
        "source_manifest_hash": source_manifest.get("schema_hash"),
        "params_hash": _prefixed_sha256(normalized_params),
    }
    if _location_id(execution_location) == "scheduler_temporal":
        bundle_manifest["temporal_config"] = "manifests/nextflow-temporal.config"
        bundle_manifest["scheduler_command_manifest"] = "manifests/nextflow_scheduler_command.json"

    (bundle / "workflow_graph.json").write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle / "recipe.json").write_text(json.dumps(recipe_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle / "params.schema.json").write_text(json.dumps(graph.get("params_schema") or {}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle / "params.review.json").write_text(json.dumps(params_review_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle / "nf-params.json").write_text(json.dumps(normalized_params, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (manifests / "source_manifest.json").write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (manifests / "bundle_manifest.json").write_text(json.dumps(bundle_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (manifests / "path_binding_candidates.json").write_text(
        json.dumps(
            {
                "schema": NFCORE_PATH_CANDIDATES_SCHEMA,
                "graph_id": graph.get("graph_id"),
                "candidates": graph.get("path_binding_candidates") or [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    write_path_bindings(
        bundle,
        graph,
        normalized_params,
        execution_location=execution_location,
        recipe_payload=recipe_payload,
        params_review_payload=params_review_payload,
    )
    if _location_id(execution_location) == "scheduler_temporal":
        temporal_config = write_nextflow_temporal_config(manifests / "nextflow-temporal.config")
        scheduler_command = nextflow_scheduler_command_manifest(
            bundle,
            temporal_config_path=Path(temporal_config["path"]),
            temporal_target=str(temporal_config["target"]),
            namespace=str(temporal_config["namespace"]),
            task_queue=str(temporal_config["task_queue"]),
        )
        (manifests / "nextflow_scheduler_command.json").write_text(
            json.dumps(scheduler_command, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _write_nfcore_container_manifest(bundle, graph, normalized_params)
    run_nextflow = bundle / "run.nextflow.sh"
    run_nextflow.write_text(_run_nextflow_sh(graph, normalized_params), encoding="utf-8")
    run_nextflow.chmod(run_nextflow.stat().st_mode | stat.S_IXUSR)
    run_sh = bundle / "run.sh"
    run_sh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'BUNDLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'
        'exec "$BUNDLE_DIR/run.nextflow.sh" "$@"\n',
        encoding="utf-8",
    )
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR)
    (bundle / "README.md").write_text(_readme(graph), encoding="utf-8")
    return bundle


def preflight_nfcore_bundle(
    graph: dict[str, Any],
    params: dict[str, Any],
    *,
    bundle_dir: str | Path | None = None,
    execution_location_kind: str = "server",
) -> dict[str, Any]:
    """Diagnose whether an nf-core bundle is launch-ready without executing Nextflow."""

    bundle = Path(bundle_dir) if bundle_dir is not None else None
    normalized_params = normalize_nfcore_params(graph, params)
    validation = validate_graph_params(graph, normalized_params)
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    nfcore_graph = is_nfcore_pipeline_graph(graph)
    checks.append({"check": "nf-core pipeline graph", "status": "pass" if nfcore_graph else "fail"})
    if not nfcore_graph:
        blockers.append("graph is not an nf-core pipeline graph")

    if validation["valid"]:
        checks.append({"check": "required nf-core params present", "status": "pass"})
    else:
        blockers.append("required nf-core parameters are missing")
        for name in validation.get("missing_required_inputs") or []:
            checks.append({"check": f"required parameter `{name}`", "status": "fail"})

    if bundle is not None:
        expected_files = [
            "nf-params.json",
            "run.nextflow.sh",
            "workflow_graph.json",
            "manifests/source_manifest.json",
            "manifests/path_bindings.json",
            "manifests/container.json",
        ]
        if _location_id(execution_location_kind) == "scheduler_temporal":
            expected_files.extend(
                [
                    "manifests/nextflow-temporal.config",
                    "manifests/nextflow_scheduler_command.json",
                ]
            )
        for relative in expected_files:
            path = bundle / relative
            ok = path.is_file()
            checks.append({"check": f"bundle contains {relative}", "status": "pass" if ok else "fail", "path": str(path)})
            if not ok:
                blockers.append(f"bundle is missing {relative}")
        params_file = bundle / "nf-params.json"
        if params_file.is_file():
            try:
                loaded = json.loads(params_file.read_text(encoding="utf-8"))
                params_ok = isinstance(loaded, dict)
            except json.JSONDecodeError as exc:
                loaded = None
                params_ok = False
                checks.append({"check": "nf-params.json is valid JSON", "status": "fail", "error": str(exc)})
            else:
                checks.append({"check": "nf-params.json is valid JSON", "status": "pass" if params_ok else "fail"})
            if not params_ok:
                blockers.append("nf-params.json is not a JSON object")
            elif isinstance(loaded, dict):
                normalized_params = loaded

    profile = _selected_profile(graph, normalized_params)
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    pipeline = str(runtime.get("pipeline_name") or runtime.get("pipeline") or "")
    release = str(runtime.get("release") or "")
    nextflow_preflight = nextflow_runtime_preflight(
        pipeline=pipeline,
        release=release,
        profile=profile,
        execution_location_kind=execution_location_kind,
    )
    checks.extend(nextflow_preflight.get("checks") or [])
    blockers.extend(nextflow_preflight.get("blockers") or [])

    if bundle is not None:
        manifest = load_path_bindings(bundle)
        path_validation = validate_path_bindings_for_location(
            manifest,
            bundle_dir=bundle,
            execution_location=_location_id(execution_location_kind),
        )
        checks.extend(path_validation.get("checks") or [])
        blockers.extend(path_validation.get("blockers") or [])
    else:
        path_validation = None
        checks.append({"check": "path bindings manifest present", "status": "not_run"})

    executable_ready = not blockers
    return {
        "schema": "morphic.nfcore_preflight_result/v0",
        "status": "preflight_passed" if executable_ready else "blocked",
        "graph_id": graph.get("graph_id"),
        "inputs_passed": validation["valid"] and not list((path_validation or {}).get("blockers") or []),
        "executable_ready": executable_ready,
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(dict.fromkeys(blockers)) if blockers else None,
        "validation": validation,
        "selected_profile": profile,
        "nextflow_preflight": nextflow_preflight,
        "launch_command": nextflow_preflight.get("launch_command") if executable_ready or bundle is not None else None,
    }


def _write_nfcore_container_manifest(bundle: Path, graph: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    profile = _selected_profile(graph, params)
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    manifest = {
        "schema": NFCORE_CONTAINER_MANIFEST_SCHEMA,
        "graph_id": graph.get("graph_id"),
        "profile_id": profile,
        "status": "delegated_to_nextflow",
        "container_authority": "nf-core/nextflow profile",
        "pipeline": runtime.get("pipeline_name") or runtime.get("pipeline"),
        "release": runtime.get("release"),
        "supported_profiles": _supported_profiles(graph),
        "selected_profile": profile,
        "notes": [
            "nf-core container images are resolved by Nextflow and the selected profile.",
            "This tranche does not download containers or resolve per-process image digests.",
        ],
    }
    manifests = bundle / "manifests"
    manifests.mkdir(exist_ok=True)
    (manifests / "container.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _run_nextflow_sh(graph: dict[str, Any], params: dict[str, Any]) -> str:
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    pipeline = str(runtime.get("pipeline_name") or runtime.get("pipeline") or graph.get("title") or "")
    release = str(runtime.get("release") or "")
    default_profile = _selected_profile(graph, params)
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        BUNDLE_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
        NEXTFLOW_BIN="${{NEXTFLOW_BIN:-nextflow}}"
        PIPELINE="${{NFCORE_WORKFLOW_PATH-{shlex.quote(pipeline)}}}"
        RELEASE="${{NFCORE_RELEASE-{shlex.quote(release)}}}"
        PROFILE="${{NFCORE_PROFILE-{shlex.quote(default_profile)}}}"
        NEXTFLOW_CONFIG_FILE="${{NEXTFLOW_CONFIG_FILE:-}}"
        if [[ -z "$NEXTFLOW_CONFIG_FILE" && -f "$BUNDLE_DIR/manifests/nextflow-temporal.config" ]]; then
          NEXTFLOW_CONFIG_FILE="$BUNDLE_DIR/manifests/nextflow-temporal.config"
        fi

        if ! command -v "$NEXTFLOW_BIN" >/dev/null 2>&1; then
          echo "Nextflow launcher was not found: $NEXTFLOW_BIN" >&2
          exit 127
        fi

        # Review equivalent: nextflow run "$PIPELINE"
        cmd=("$NEXTFLOW_BIN" run "$PIPELINE")
        if [[ -n "$RELEASE" && "$PIPELINE" != /* && "$PIPELINE" != ./* ]]; then
          cmd+=(-r "$RELEASE")
        fi
        if [[ -n "$PROFILE" ]]; then
          cmd+=(-profile "$PROFILE")
        fi
        if [[ -n "$NEXTFLOW_CONFIG_FILE" ]]; then
          cmd+=(-c "$NEXTFLOW_CONFIG_FILE")
        fi
        cmd+=(-with-trace "$BUNDLE_DIR/manifests/nextflow-trace.txt")
        cmd+=(-with-report "$BUNDLE_DIR/manifests/nextflow-report.html")
        cmd+=(-with-timeline "$BUNDLE_DIR/manifests/nextflow-timeline.html")
        cmd+=(-params-file "$BUNDLE_DIR/nf-params.json")

        printf 'Launching nf-core pipeline:'
        printf ' %q' "${{cmd[@]}}"
        printf '\\n'
        exec "${{cmd[@]}}" "$@"
        """
    )


def _readme(graph: dict[str, Any]) -> str:
    runtime = graph.get("runtime") if isinstance(graph.get("runtime"), dict) else {}
    title = str(graph.get("title") or graph.get("graph_id") or "nf-core pipeline")
    return textwrap.dedent(
        f"""\
        # {title}

        This bundle is a reviewable Workbench wrapper around an upstream nf-core Nextflow pipeline.

        Review these files before launching:

        - `nf-params.json`
        - `run.nextflow.sh`
        - `manifests/path_bindings.json`
        - `manifests/container.json`
        - `workflow_graph.json`

        Pipeline: `{runtime.get("pipeline_name") or runtime.get("pipeline")}`
        Release: `{runtime.get("release") or ""}`

        Run with:

        ```bash
        bash run.nextflow.sh
        ```
        """
    )


def _selected_profile(graph: dict[str, Any], params: dict[str, Any]) -> str:
    if str(params.get("profile") or "").strip():
        return str(params["profile"]).strip()
    for field in (graph.get("params_schema") or {}).get("fields") or []:
        if isinstance(field, dict) and field.get("name") == "profile" and field.get("default"):
            return str(field["default"])
    return "docker"


def _supported_profiles(graph: dict[str, Any]) -> list[str]:
    for field in (graph.get("params_schema") or {}).get("fields") or []:
        if isinstance(field, dict) and field.get("name") == "profile" and isinstance(field.get("enum"), list):
            return [str(item) for item in field["enum"]]
    return ["apptainer", "conda", "docker", "podman", "singularity"]


def _safe_graph_id(text: str) -> str:
    keep = []
    for ch in text.lower():
        keep.append(ch if ch.isalnum() else "_")
    value = "".join(keep).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "nfcore_pipeline"


def _location_id(execution_location_kind: str) -> str:
    return str(execution_location_kind or "server")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prefixed_sha256(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
