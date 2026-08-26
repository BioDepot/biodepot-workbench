"""Bulk paired-end STAR + DESeq2 folder bundle materializer."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from morphic_agent.bundle.containers import (
    diagnose_container_manifest,
    load_container_manifest,
    resolve_deseq2_execution_route,
    write_container_launchers,
    write_container_manifest,
)
from morphic_agent.bundle.path_bindings import write_path_bindings
from morphic_agent.content.paths import star_suite_root
from morphic_agent.graph.params import validate_graph_params, validate_paired_reads
from morphic_agent.bundle.star_workflow import assess_star_render_readiness

BULK_DEG_CORE_GRAPH_ID = "bulk_pe_deseq2_v0"
BULK_DEG_PLOTS_GRAPH_ID = "bulk_pe_deseq2_plots_v0"
MATERIALIZABLE_BULK_DEG_GRAPH_IDS = frozenset({BULK_DEG_CORE_GRAPH_ID})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_graph_id(text: str) -> str:
    keep = []
    for ch in text.lower():
        keep.append(ch if ch.isalnum() else "_")
    value = "".join(keep).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "graph"


def _star_workflow_helper_source() -> str:
    return (Path(__file__).with_name("star_workflow.py")).read_text(encoding="utf-8")


def star_suite_cli_path(star_root: str | Path | None = None) -> Path:
    root = Path(star_root) if star_root else star_suite_root()
    return root / "mcp_server" / "cli.py"


def star_suite_workflows_path(star_root: str | Path | None = None) -> Path:
    root = Path(star_root) if star_root else star_suite_root()
    return root / "mcp_server" / "tools" / "workflows.py"


def _star_binary_available() -> bool:
    try:
        proc = subprocess.run(["bash", "-lc", "command -v STAR"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _rscript_available() -> bool:
    try:
        proc = subprocess.run(["bash", "-lc", "command -v Rscript"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _r_package_available(package: str) -> bool:
    if not _rscript_available():
        return False
    try:
        proc = subprocess.run(
            ["Rscript", "-e", f'quit(status=ifelse(requireNamespace("{package}", quietly=TRUE), 0, 1))'],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _deseq2_stack_available() -> bool:
    return _r_package_available("DESeq2") and _r_package_available("jsonlite")


def validate_bulk_deseq_params(graph: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    if _skip_star_requested(params):
        missing: list[str] = []
        field_errors: dict[str, str] = {}
        normalized = dict(params)
        for name in ("counts_matrix", "coldata", "design"):
            if _value_missing(params.get(name)):
                missing.append(name)
                field_errors[name] = "required value is missing"
        counts_path = Path(str(params.get("counts_matrix") or "")).expanduser()
        if params.get("counts_matrix") and not counts_path.is_file():
            field_errors["counts_matrix"] = "counts_matrix path does not exist"
            if "counts_matrix" not in missing:
                missing.append("counts_matrix")
        coldata_path = Path(str(params.get("coldata") or "")).expanduser()
        if params.get("coldata") and not coldata_path.is_file():
            field_errors["coldata"] = "coldata path does not exist"
            if "coldata" not in missing:
                missing.append("coldata")
        return {
            "valid": not missing and not field_errors,
            "normalized_params": normalized,
            "missing_required_inputs": missing,
            "field_errors": field_errors,
        }
    return validate_graph_params(graph, params)


def _value_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def _skip_star_requested(params: dict[str, Any]) -> bool:
    if str(params.get("skip_star") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    counts_path = str(params.get("counts_matrix") or "").strip()
    return bool(counts_path and Path(counts_path).expanduser().is_file())


def _deseq2_runtime_ready(
    *,
    host_deseq2_available: bool,
    container_diagnostic: dict[str, Any] | None,
    execution_location_kind: str,
    skip_star: bool,
) -> bool:
    route = resolve_deseq2_execution_route(
        execution_location_kind=execution_location_kind,
        host_deseq2_available=host_deseq2_available,
        container_diagnostic=container_diagnostic,
        skip_star=skip_star,
    )
    return bool(route.get("available"))


def assess_bulk_deg_execution_readiness(
    graph: dict[str, Any],
    params: dict[str, Any],
    *,
    star_root: str | Path | None = None,
    execution_location_kind: str = "server",
    bundle_dir: str | Path | None = None,
) -> dict[str, Any]:
    validation = validate_graph_params(graph, params)
    blockers: list[str] = []
    checks: list[dict[str, Any]] = []
    skip_star = _skip_star_requested(params)

    if skip_star:
        counts_raw = str(params.get("counts_matrix") or "")
        counts_path = Path(counts_raw).expanduser()
        if bundle_dir is not None and not counts_path.is_file() and counts_raw:
            counts_path = Path(bundle_dir) / counts_raw
        counts_ok = counts_path.is_file()
        checks.append(
            {
                "check": "pre-staged counts_matrix exists",
                "status": "pass" if counts_ok else "fail",
                "path": str(counts_path),
            }
        )
        if not counts_ok:
            blockers.append("skip_star requires an existing counts_matrix path")
        coldata_raw = str(params.get("coldata") or "")
        coldata_path = Path(coldata_raw).expanduser()
        if bundle_dir is not None and not coldata_path.is_file() and coldata_raw:
            coldata_path = Path(bundle_dir) / coldata_raw
        coldata_ok = coldata_path.is_file()
        checks.append(
            {
                "check": "path exists: coldata",
                "status": "pass" if coldata_ok else "fail",
                "path": str(coldata_path),
            }
        )
        if not coldata_ok:
            blockers.append("missing input path: coldata")
        design_ok = str(params.get("design") or "").strip() != ""
        checks.append({"check": "parameter present: design", "status": "pass" if design_ok else "fail"})
        if not design_ok:
            blockers.append("missing parameter: design")

    if graph.get("graph_id") == BULK_DEG_PLOTS_GRAPH_ID:
        plot_blocker = str(graph.get("run_blocker") or "plot helpers are not materialized")
        blockers.append(plot_blocker)
        checks.append(
            {
                "check": "plot module materialization",
                "status": "fail",
                "module_ids": ["volcano_plot", "heatmap_plot"],
            }
        )

    if not validation["valid"] and not skip_star:
        blockers.append("required parameters are missing or invalid")
        for name in validation.get("missing_required_inputs") or []:
            checks.append({"check": f"required parameter `{name}`", "status": "fail"})
        for name, message in (validation.get("field_errors") or {}).items():
            checks.append({"check": f"{name}: {message}", "status": "fail"})

    if not skip_star:
        reads_errors = validate_paired_reads(params.get("reads"))
    else:
        reads_errors = []
    if reads_errors:
        blockers.append("paired-end reads are incomplete")
        for message in reads_errors:
            checks.append({"check": message, "status": "fail", "field": "reads"})

    schema_fields = {
        str(field.get("name")): field
        for field in (graph.get("params_schema") or {}).get("fields") or []
        if isinstance(field, dict) and field.get("name")
    }
    if not skip_star:
        for field in graph.get("params_schema", {}).get("required") or []:
            if field in validation.get("missing_required_inputs") or []:
                continue
            if field == "reads":
                continue
            field_schema = schema_fields.get(field) or {}
            field_type = str(field_schema.get("type") or "string")
            artifact_type = str(field_schema.get("artifact_type") or "")
            value = params.get(field)
            if field_type in {"path", "array"}:
                path = Path(str(value or ""))
                if artifact_type == "star_genome_dir":
                    ok = path.is_dir()
                else:
                    ok = path.exists()
                checks.append({"check": f"path exists: {field}", "status": "pass" if ok else "fail", "path": str(path)})
                if not ok:
                    blockers.append(f"missing input path: {field}")
            else:
                ok = value not in (None, "")
                checks.append({"check": f"parameter present: {field}", "status": "pass" if ok else "fail", "value": value})
                if not ok:
                    blockers.append(f"missing parameter: {field}")

    if not skip_star:
        if not reads_errors:
            for index, item in enumerate(params.get("reads") or []):
                if not isinstance(item, dict):
                    continue
                for mate in ("r1", "r2"):
                    path = Path(str(item.get(mate) or ""))
                    ok = path.exists()
                    checks.append(
                        {
                            "check": f"reads[{index}].{mate} exists",
                            "status": "pass" if ok else "fail",
                            "path": str(path),
                        }
                    )
                    if not ok:
                        blockers.append(f"missing FASTQ path reads[{index}].{mate}")

        cli = star_suite_cli_path(star_root)
        workflows_py = star_suite_workflows_path(star_root)
        star_binary_ok = _star_binary_available()
        star_ok = cli.is_file() or workflows_py.is_file() or star_binary_ok
        checks.append(
            {
                "check": "STAR suite renderer or STAR binary available",
                "status": "pass" if star_ok else "fail",
                "path": str(workflows_py if workflows_py.is_file() else cli),
            }
        )
        if not star_ok:
            blockers.append("STAR suite renderer or STAR binary is not available on this host")

        out_prefix = str(params.get("out_file_name_prefix") or params.get("output_prefix") or "").strip()
        if not out_prefix:
            out_prefix = "/tmp/morphic-agent-star-preview/"
        star_render = assess_star_render_readiness(
            params,
            out_prefix=out_prefix,
            star_root=star_root,
            check_paths=True,
        )
        for message in star_render.get("errors") or []:
            checks.append({"check": f"STAR workflow params: {message}", "status": "fail"})
            blockers.append(message)
        if star_render.get("render_ok"):
            checks.append({"check": "STAR workflow command can render (suite)", "status": "pass"})
        else:
            if not star_render.get("errors"):
                suite_error = star_render.get("suite_error")
                if suite_error:
                    checks.append({"check": "STAR workflow command can render (suite)", "status": "fail", "detail": suite_error})
                    blockers.append(f"STAR workflow render failed: {suite_error}")
                else:
                    checks.append({"check": "STAR workflow command can render (suite)", "status": "fail"})
                    blockers.append("STAR workflow command cannot be rendered from current parameters")
                if star_render.get("fallback_preview_ok"):
                    checks.append(
                        {
                            "check": "raw STAR fallback preview available",
                            "status": "pass",
                            "detail": "Preview is review-only; executable readiness still requires Suite rendering.",
                        }
                    )
            elif not any(str(check.get("check", "")).startswith("STAR workflow params:") for check in checks):
                checks.append({"check": "STAR workflow command can render (suite)", "status": "fail"})
                blockers.append("STAR workflow command cannot be rendered from current parameters")
    else:
        star_ok = True
        star_render = {"render_ok": True}
        checks.append({"check": "STAR alignment skipped for DESeq2-only smoke path", "status": "pass"})

    deseq2_ok = _deseq2_stack_available()
    checks.append({"check": "DESeq2 R package available", "status": "pass" if _r_package_available("DESeq2") else "fail"})
    checks.append({"check": "jsonlite R package available", "status": "pass" if _r_package_available("jsonlite") else "fail"})

    container_manifest = load_container_manifest(Path(bundle_dir)) if bundle_dir is not None else None
    container_diagnostic = diagnose_container_manifest(container_manifest, execution_location_kind=execution_location_kind)
    execution_route = resolve_deseq2_execution_route(
        execution_location_kind=execution_location_kind,
        host_deseq2_available=deseq2_ok,
        container_diagnostic=container_diagnostic,
        skip_star=skip_star,
    )
    checks.append(
        {
            "check": "DESeq2 execution route available",
            "status": "pass" if execution_route.get("available") else "fail",
            "route_id": execution_route.get("route_id"),
            "summary": execution_route.get("summary"),
        }
    )
    if not execution_route.get("available") and execution_route.get("run_blocker"):
        blockers.append(str(execution_route["run_blocker"]))

    deseq2_runtime_ok = _deseq2_runtime_ready(
        host_deseq2_available=deseq2_ok,
        container_diagnostic=container_diagnostic,
        execution_location_kind=execution_location_kind,
        skip_star=skip_star,
    )

    input_failures = [
        check
        for check in checks
        if check.get("status") == "fail"
        and check.get("check")
        not in {
            "STAR suite renderer or STAR binary available",
            "DESeq2 R package available",
            "jsonlite R package available",
            "DESeq2 execution route available",
            "STAR alignment skipped for DESeq2-only smoke path",
            "STAR workflow command can render (suite)",
            "raw STAR fallback preview available",
            "plot module materialization",
        }
        and not str(check.get("check", "")).startswith("STAR workflow params:")
    ]
    inputs_ok = (validation["valid"] or skip_star) and not reads_errors and not input_failures
    star_render_ok = bool(star_render.get("render_ok"))
    executable_ready = (
        inputs_ok
        and star_ok
        and star_render_ok
        and deseq2_runtime_ok
        and graph.get("graph_id") not in {BULK_DEG_PLOTS_GRAPH_ID}
    )

    if graph.get("graph_id") == BULK_DEG_PLOTS_GRAPH_ID:
        status = "blocked"
    elif executable_ready:
        status = "preflight_passed"
    elif inputs_ok:
        status = "inputs_passed"
    else:
        status = "blocked"

    return {
        "status": status,
        "inputs_passed": inputs_ok,
        "executable_ready": executable_ready,
        "checks": checks,
        "blockers": blockers,
        "run_blocker": "; ".join(blockers) if blockers else None,
        "validation": validation,
        "execution_route": execution_route,
        "container_diagnostic": container_diagnostic,
        "skip_star": skip_star,
    }


def _star_bulk_pe_helper(*, star_root_default: str) -> str:
    quoted_root = shlex.quote(star_root_default)
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # STAR bulk paired-end count generation helper.
        set -euo pipefail
        BUNDLE_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")/.." && pwd)"
        PARAMS="$BUNDLE_DIR/params.review.json"
        STAR_ROOT="${{STAR_SUITE_ROOT:-{quoted_root}}}"
        OUT_DIR="$BUNDLE_DIR/outputs/star"
        mkdir -p "$OUT_DIR"
        python3 "$BUNDLE_DIR/helpers/render_star_argv.py" --params "$PARAMS" --out "$BUNDLE_DIR/manifests/star_render.json" --out-dir "$OUT_DIR" --star-root "$STAR_ROOT"
        python3 "$BUNDLE_DIR/helpers/execute_star_argv.py" --manifest "$BUNDLE_DIR/manifests/star_render.json" --star-root "$STAR_ROOT"
        """
    ).lstrip()


def _render_star_argv_helper(*, star_root_default: str) -> str:
    return textwrap.dedent(
        r'''#!/usr/bin/env python3
"""Render STAR bulk PE argv from reviewed params — editable helper, not a heredoc."""
import argparse
import json
from pathlib import Path

from star_workflow import (
    assess_star_render_readiness,
    build_star_bulk_pe_workflow_params,
    build_star_argv_preview,
)


parser = argparse.ArgumentParser()
parser.add_argument("--params", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--out-dir", required=True)
parser.add_argument("--star-root", default="__STAR_ROOT_DEFAULT__")
args = parser.parse_args()

params = json.loads(Path(args.params).read_text())["params"]
out_dir = Path(args.out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
workflow_params = build_star_bulk_pe_workflow_params(params, out_prefix=str(out_dir))
argv_preview = build_star_argv_preview(workflow_params)
readiness = assess_star_render_readiness(
    params,
    out_prefix=str(out_dir),
    star_root=args.star_root,
    check_paths=False,
)
if readiness.get("errors"):
    raise SystemExit("\n".join(str(message) for message in readiness["errors"]))
payload = {
    "workflow_id": "star_bulk_pe_batch",
    "workflow_params": workflow_params,
    "argv_preview": argv_preview,
    "suite_argv": readiness.get("suite_argv"),
    "suite_error": readiness.get("suite_error"),
    "suite_render_ok": readiness.get("suite_render_ok"),
    "render_mode": readiness.get("render_mode"),
    "params": {
        "genome_fasta": params.get("genome_fasta"),
        "gtf": params.get("gtf"),
        "bam_sort": params.get("bam_sort", "sorted"),
        "counts_matrix": str(out_dir / "star_ReadsPerGene.out.tab"),
    },
}
Path(args.out).parent.mkdir(parents=True, exist_ok=True)
Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
'''
    ).replace("__STAR_ROOT_DEFAULT__", star_root_default).lstrip()


def _execute_star_argv_helper(*, star_root_default: str) -> str:
    return textwrap.dedent(
        r'''#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from star_workflow import try_render_star_workflow_command

parser = argparse.ArgumentParser()
parser.add_argument("--manifest", required=True)
parser.add_argument("--star-root", default="__STAR_ROOT_DEFAULT__")
args = parser.parse_args()
manifest = json.loads(Path(args.manifest).read_text())
workflow_params = manifest.get("workflow_params") or {}
argv = manifest.get("suite_argv") or []

star_root = Path(args.star_root)
if not argv and workflow_params:
    ok, error, rendered = try_render_star_workflow_command(workflow_params, star_root=star_root)
    if ok and rendered:
        argv = rendered
    else:
        suite_error = error or manifest.get("suite_error") or "STAR suite render failed"
        raise SystemExit(f"STAR suite render failed; refusing to run raw preview: {suite_error}")

if not argv:
    raise SystemExit("STAR suite argv is missing from manifest")
if any("<" in part or ">" in part for part in argv):
    raise SystemExit("STAR argv still contains placeholder tokens")
exe = str(argv[0])
if os.path.isabs(exe) or "/" in exe:
    if not Path(exe).is_file() or not os.access(exe, os.X_OK):
        raise SystemExit(f"STAR executable is not runnable: {exe}")
elif shutil.which(exe) is None:
    raise SystemExit(f"STAR executable not found in PATH: {exe}")
subprocess.run(argv, check=True)
'''
    ).replace("__STAR_ROOT_DEFAULT__", star_root_default).lstrip()


def _deseq2_helper() -> str:
    return textwrap.dedent(
        r'''#!/usr/bin/env Rscript
args <- commandArgs(trailingOnly = TRUE)
params_path <- args[[1]]
out_dir <- args[[2]]
if (!requireNamespace("DESeq2", quietly = TRUE)) {
  stop("DESeq2 package is not installed; install DESeq2 or use the pinned container helper.")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite package is not installed; install jsonlite before running the DESeq2 helper.")
}
params <- jsonlite::fromJSON(params_path)$params
bundle_dir <- dirname(dirname(params_path))
resolve_path <- function(raw) {
  if (is.null(raw) || raw == "") {
    return(raw)
  }
  if (file.exists(raw)) {
    return(raw)
  }
  candidate <- file.path(bundle_dir, raw)
  if (file.exists(candidate)) {
    return(candidate)
  }
  raw
}
counts_path <- resolve_path(params$counts_matrix)
if (is.null(counts_path) || counts_path == "" || !file.exists(counts_path)) {
  star_manifest <- file.path(dirname(dirname(params_path)), "manifests", "star_render.json")
  if (file.exists(star_manifest)) {
    manifest <- jsonlite::fromJSON(star_manifest)
    counts_path <- manifest$params$counts_matrix
  }
}
if (is.null(counts_path) || counts_path == "" || !file.exists(counts_path)) {
  stop("STAR count matrix not found; STAR alignment must complete before DESeq2 can run.")
}
if (is.null(params$coldata) || params$coldata == "" || !file.exists(resolve_path(params$coldata))) {
  stop("coldata path is missing or does not exist.")
}
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
coldata <- read.delim(resolve_path(params$coldata), row.names = 1, check.names = FALSE)
counts <- read.delim(counts_path, row.names = 1, check.names = FALSE)
if (ncol(counts) < 2) {
  stop("count matrix must have at least two sample columns for DESeq2.")
}
dds <- DESeq2::DESeqDataSetFromMatrix(
  countData = counts,
  colData = coldata,
  design = as.formula(params$design)
)
dds <- DESeq2::DESeq(dds)
res <- DESeq2::results(dds)
write.csv(as.data.frame(res), file.path(out_dir, "deseq2_results.csv"))
jsonlite::write_json(
  list(status = "completed", counts_matrix = counts_path, results = file.path(out_dir, "deseq2_results.csv")),
  file.path(out_dir, "deseq2_execution.json"),
  auto_unbox = TRUE,
  pretty = TRUE
)
'''
    ).lstrip()


def _preflight_helper(*, star_root_default: str) -> str:
    return textwrap.dedent(
        r'''#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--graph", required=True)
parser.add_argument("--params", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()

graph = json.loads(Path(args.graph).read_text())
params = json.loads(Path(args.params).read_text())["params"]
bundle_dir = Path(args.params).parent
checks = []
blockers = []

def _resolve_path(raw):
    path = Path(str(raw or "")).expanduser()
    if path.is_file() or path.is_dir():
        return path
    candidate = bundle_dir / raw
    if candidate.is_file() or candidate.is_dir():
        return candidate
    return path

def _skip_star_requested(local_params):
    if str(local_params.get("skip_star") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    counts_path = str(local_params.get("counts_matrix") or "").strip()
    return bool(counts_path and Path(counts_path).expanduser().is_file())

skip_star = _skip_star_requested(params)

if graph.get("graph_id") == "bulk_pe_deseq2_plots_v0":
    blockers.append(graph.get("run_blocker") or "plot helpers are not materialized")
    checks.append({"check": "plot module materialization", "status": "fail"})

if skip_star:
    counts_path = _resolve_path(params.get("counts_matrix"))
    counts_ok = counts_path.is_file()
    checks.append({"check": "pre-staged counts_matrix exists", "status": "pass" if counts_ok else "fail", "path": str(counts_path)})
    if not counts_ok:
        blockers.append("skip_star requires an existing counts_matrix path")
    coldata_path = _resolve_path(params.get("coldata"))
    coldata_ok = coldata_path.is_file()
    checks.append({"check": "path exists: coldata", "status": "pass" if coldata_ok else "fail", "path": str(coldata_path)})
    if not coldata_ok:
        blockers.append("missing input path: coldata")
    design_ok = str(params.get("design") or "").strip() != ""
    checks.append({"check": "parameter present: design", "status": "pass" if design_ok else "fail"})
    if not design_ok:
        blockers.append("missing parameter: design")
    checks.append({"check": "STAR alignment skipped for DESeq2-only smoke path", "status": "pass"})
    star_ok = True
    star_render_ok = True
else:
    reads = params.get("reads") or []
    if not isinstance(reads, list) or not reads:
        blockers.append("reads must be a non-empty list")
        checks.append({"check": "reads present", "status": "fail"})
    else:
        for index, item in enumerate(reads):
            if not isinstance(item, dict):
                blockers.append(f"reads[{index}] must be an object")
                checks.append({"check": f"reads[{index}] object", "status": "fail"})
                continue
            for mate in ("r1", "r2"):
                raw = str(item.get(mate) or "").strip()
                if not raw:
                    blockers.append(f"reads[{index}].{mate} is required")
                    checks.append({"check": f"reads[{index}].{mate} present", "status": "fail"})
                    continue
                path = Path(raw)
                ok = path.exists()
                checks.append({"check": f"reads[{index}].{mate} exists", "status": "pass" if ok else "fail", "path": str(path)})
                if not ok:
                    blockers.append(f"missing FASTQ path reads[{index}].{mate}")

    fields = {f["name"]: f for f in graph.get("params_schema", {}).get("fields", []) if isinstance(f, dict)}
    for name in graph.get("params_schema", {}).get("required", []):
        if name == "reads":
            continue
        value = params.get(name)
        field = fields.get(name, {})
        if field.get("type") in {"path", "array"}:
            path = Path(str(value or ""))
            if field.get("artifact_type") == "star_genome_dir":
                ok = path.is_dir()
            else:
                ok = path.exists()
            checks.append({"check": f"path exists: {name}", "status": "pass" if ok else "fail", "path": str(path)})
            if not ok:
                blockers.append(f"missing input path: {name}")
        elif value in (None, ""):
            blockers.append(f"missing parameter: {name}")
            checks.append({"check": f"parameter present: {name}", "status": "fail"})

    from star_workflow import assess_star_render_readiness

    star_root = Path(os.environ.get("STAR_SUITE_ROOT") or "__STAR_ROOT_DEFAULT__")
    cli = star_root / "mcp_server" / "cli.py"
    workflows_py = star_root / "mcp_server" / "tools" / "workflows.py"
    star_binary_ok = False
    try:
        star_binary_ok = subprocess.run(["bash", "-lc", "command -v STAR"], capture_output=True, text=True, timeout=5).returncode == 0
    except Exception:
        star_binary_ok = False
    star_ok = cli.is_file() or workflows_py.is_file() or star_binary_ok
    checks.append({"check": "STAR suite renderer or STAR binary available", "status": "pass" if star_ok else "fail", "path": str(workflows_py if workflows_py.is_file() else cli)})
    if not star_ok:
        blockers.append("STAR suite renderer or STAR binary is not available on this host")

    star_render = assess_star_render_readiness(
        params,
        out_prefix=str(Path(args.params).parent / "outputs" / "star"),
        star_root=star_root,
        check_paths=True,
    )
    for message in star_render.get("errors") or []:
        blockers.append(message)
        checks.append({"check": f"STAR workflow params: {message}", "status": "fail"})

    star_render_ok = bool(star_render.get("render_ok"))
    if star_render_ok:
        checks.append({"check": "STAR workflow command can render (suite)", "status": "pass"})
    elif not star_render.get("errors"):
        detail = star_render.get("suite_error") or "STAR workflow command cannot be rendered from current parameters"
        checks.append({"check": "STAR workflow command can render (suite)", "status": "fail", "detail": detail})
        blockers.append(f"STAR workflow render failed: {detail}")
        if star_render.get("fallback_preview_ok"):
            checks.append({
                "check": "raw STAR fallback preview available",
                "status": "pass",
                "detail": "Preview is review-only; executable readiness still requires Suite rendering.",
            })
        else:
            checks.append({"check": "raw STAR fallback preview available", "status": "fail"})

def _r_package_available(package):
    try:
        return subprocess.run(
            ["Rscript", "-e", f'quit(status=ifelse(requireNamespace("{package}", quietly=TRUE), 0, 1))'],
            capture_output=True,
            text=True,
            timeout=30,
        ).returncode == 0
    except Exception:
        return False

deseq2_ok = _r_package_available("DESeq2")
jsonlite_ok = _r_package_available("jsonlite")
checks.append({"check": "DESeq2 R package available", "status": "pass" if deseq2_ok else "fail"})
checks.append({"check": "jsonlite R package available", "status": "pass" if jsonlite_ok else "fail"})
if not (deseq2_ok and jsonlite_ok):
    blockers.append("DESeq2 and jsonlite must both be available via Rscript on this host")

input_failures = [c for c in checks if c.get("status") == "fail" and c.get("check") not in {
    "STAR suite renderer or STAR binary available",
    "DESeq2 R package available",
    "jsonlite R package available",
    "STAR workflow command can render (suite)",
    "raw STAR fallback preview available",
    "plot module materialization",
    "STAR alignment skipped for DESeq2-only smoke path",
} and not str(c.get("check", "")).startswith("STAR workflow params:")]
inputs_ok = not input_failures and graph.get("graph_id") != "bulk_pe_deseq2_plots_v0"
deseq2_runtime_ok = deseq2_ok and jsonlite_ok
executable_ready = inputs_ok and star_ok and star_render_ok and deseq2_runtime_ok and graph.get("graph_id") != "bulk_pe_deseq2_plots_v0"
if graph.get("graph_id") == "bulk_pe_deseq2_plots_v0":
    status = "blocked"
elif executable_ready:
    status = "preflight_passed"
elif inputs_ok:
    status = "inputs_passed"
else:
    status = "blocked"

result = {
    "schema": "morphic.preflight_result/v0",
    "status": status,
    "inputs_passed": inputs_ok,
    "executable_ready": executable_ready,
    "checks": checks,
    "blockers": blockers,
    "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
}
Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
raise SystemExit(0 if executable_ready else 2)
'''
    ).replace("__STAR_ROOT_DEFAULT__", star_root_default).lstrip()


def _run_sh(*, include_plot_blocker: bool = False) -> str:
    plot_block = ""
    if include_plot_blocker:
        plot_block = textwrap.dedent(
            """
            if [[ -f "$BUNDLE_DIR/manifests/plot_blocker.json" ]]; then
              echo "Plot modules are not materialized for this graph:" >&2
              cat "$BUNDLE_DIR/manifests/plot_blocker.json" >&2
              exit 4
            fi
            """
        )
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        BUNDLE_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
        python3 "$BUNDLE_DIR/helpers/preflight.py" \\
          --graph "$BUNDLE_DIR/workflow_graph.json" \\
          --params "$BUNDLE_DIR/params.review.json" \\
          --out "$BUNDLE_DIR/manifests/preflight_result.json"
        {plot_block}if [[ "$(python3 - "$BUNDLE_DIR/params.review.json" <<'PY'
import json
import sys
from pathlib import Path

params = json.loads(Path(sys.argv[1]).read_text()).get("params") or {{}}
skip = str(params.get("skip_star") or "").strip().lower() in {{"1", "true", "yes", "on"}}
counts = str(params.get("counts_matrix") or "").strip()
if not skip and counts:
    skip = Path(counts).expanduser().is_file()
print("1" if skip else "0")
PY
        )" == "1" ]]; then
          echo "Skipping STAR alignment; using pre-staged counts_matrix for DESeq2."
        else
          bash "$BUNDLE_DIR/helpers/render_star_bulk_pe.sh"
        fi
        Rscript "$BUNDLE_DIR/helpers/run_deseq2.R" "$BUNDLE_DIR/params.review.json" "$BUNDLE_DIR/outputs/deseq2"
        echo "STAR alignment and DESeq2 completed. Review outputs/ and manifests/."
        """
    )


def materialize_bulk_deseq_bundle(
    graph: dict[str, Any],
    out_root: str | Path,
    *,
    params: dict[str, Any] | None = None,
    execution_location: str = "server",
) -> Path:
    out_root = Path(out_root)
    bundle = out_root / _safe_graph_id(str(graph["graph_id"]))
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "helpers").mkdir(parents=True)
    (bundle / "manifests").mkdir(parents=True)
    (bundle / "outputs").mkdir(parents=True)

    merged = dict(params or {})
    star_out = str(bundle / "outputs" / "star")
    merged.setdefault("output_prefix", star_out)
    merged.setdefault("out_file_name_prefix", f"{star_out}/")
    star_manifest_path = bundle / "outputs" / "star" / "star_ReadsPerGene.out.tab"
    merged.setdefault("counts_matrix", str(star_manifest_path))

    counts_source = str(params.get("counts_matrix") or "").strip() if params else ""
    if _skip_star_requested(merged) and counts_source:
        source_path = Path(counts_source).expanduser()
        staged_counts = bundle / "inputs" / "counts_matrix" / source_path.name
        staged_counts.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_file():
            shutil.copy2(source_path, staged_counts)
            merged["counts_matrix"] = f"inputs/counts_matrix/{source_path.name}"
            merged["skip_star"] = True
    coldata_source = str(params.get("coldata") or "").strip() if params else ""
    if coldata_source:
        source_path = Path(coldata_source).expanduser()
        staged_coldata = bundle / "inputs" / "coldata" / source_path.name
        staged_coldata.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_file():
            shutil.copy2(source_path, staged_coldata)
            merged["coldata"] = f"inputs/coldata/{source_path.name}"

    graph_payload = dict(graph)
    graph_payload["canonical_graph_hash"] = _sha256_json(
        {
            "graph_id": graph["graph_id"],
            "nodes": graph.get("nodes"),
            "edges": graph.get("edges"),
        }
    )

    recipe_payload = {
        "schema": "morphic.materialized_recipe/v0",
        "graph_id": graph["graph_id"],
        "title": graph.get("title"),
        "canonical_graph_hash": graph_payload["canonical_graph_hash"],
        "nodes": graph.get("nodes"),
        "edges": graph.get("edges"),
    }
    params_review_payload = {"params": merged}

    (bundle / "workflow_graph.json").write_text(json.dumps(graph_payload, indent=2, sort_keys=True) + "\n")
    (bundle / "recipe.json").write_text(json.dumps(recipe_payload, indent=2, sort_keys=True) + "\n")
    (bundle / "params.schema.json").write_text(json.dumps(graph.get("params_schema") or {}, indent=2, sort_keys=True) + "\n")
    (bundle / "params.review.json").write_text(json.dumps(params_review_payload, indent=2, sort_keys=True) + "\n")
    write_path_bindings(
        bundle,
        graph,
        merged,
        execution_location=execution_location,
        recipe_payload=recipe_payload,
        params_review_payload=params_review_payload,
    )
    container_profile_key = "bulk_pe_deseq2_counts_v0" if _skip_star_requested(merged) else str(graph["graph_id"])
    write_container_manifest(bundle, str(graph["graph_id"]), profile_key=container_profile_key)
    (bundle / "manifests" / "projection_manifest.json").write_text(
        json.dumps(
            {
                "schema": "morphic.graph_projection_manifest/v0",
                "canonical_store": "postgres",
                "graph_index": "arcadedb",
                "materialized_at": _utc_now(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    star_root_default = str(star_suite_root())
    helpers = {
        "star_workflow.py": _star_workflow_helper_source(),
        "render_star_bulk_pe.sh": _star_bulk_pe_helper(star_root_default=star_root_default),
        "render_star_argv.py": _render_star_argv_helper(star_root_default=star_root_default),
        "execute_star_argv.py": _execute_star_argv_helper(star_root_default=star_root_default),
        "run_deseq2.R": _deseq2_helper(),
        "preflight.py": _preflight_helper(star_root_default=star_root_default),
    }
    manifest_lines = ["helper_id\tbundle_path"]
    for name, source in helpers.items():
        path = bundle / "helpers" / name
        path.write_text(source)
        if name.endswith((".sh", ".py")):
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        manifest_lines.append(f"{name}\thelpers/{name}")
    (bundle / "helper_manifest.tsv").write_text("\n".join(manifest_lines) + "\n")

    run_sh = bundle / "run.sh"
    run_sh.write_text(_run_sh(include_plot_blocker=False))
    run_sh.chmod(0o755)
    write_container_launchers(bundle, str(graph["graph_id"]), profile_key=container_profile_key)
    (bundle / "README.md").write_text(
        "\n".join(
            [
                f"# {graph.get('title') or graph['graph_id']}",
                "",
                "Reviewable folder bundle for STAR bulk PE counts + DESeq2.",
                "",
                "1. Review workflow_graph.json and params.review.json.",
                "2. Edit helpers/ before local run if needed.",
                "3. Run ./run.sh only after API preflight reports executable_ready.",
                "4. For container execution, use ./run.docker.sh or ./run.apptainer.sh; the image is declared in manifests/container.json.",
                "5. Set skip_star=true with a pre-staged counts_matrix to run DESeq2-only smoke fixtures without STAR.",
                "",
            ]
        )
    )
    return bundle


def preflight_bulk_deseq_bundle(
    graph: dict[str, Any],
    params: dict[str, Any],
    *,
    execution_location_kind: str = "server",
    bundle_dir: str | Path | None = None,
) -> dict[str, Any]:
    result = assess_bulk_deg_execution_readiness(
        graph,
        params,
        execution_location_kind=execution_location_kind,
        bundle_dir=bundle_dir,
    )
    return {
        "status": result["status"],
        "graph_id": graph["graph_id"],
        "checks": result["checks"],
        "blockers": result["blockers"],
        "run_blocker": result["run_blocker"],
        "inputs_passed": result["inputs_passed"],
        "executable_ready": result["executable_ready"],
        "validation": result["validation"],
        "execution_route": result.get("execution_route"),
        "container_diagnostic": result.get("container_diagnostic"),
        "skip_star": result.get("skip_star"),
    }
