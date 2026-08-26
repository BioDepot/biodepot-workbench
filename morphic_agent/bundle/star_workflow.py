"""STAR bulk PE workflow param normalization aligned with star_bulk_pe_batch.yaml."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _resolved_star_root(star_root: str | Path | None) -> Path:
    if star_root:
        return Path(star_root).expanduser().resolve()
    configured = str(os.environ.get("STAR_SUITE_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    from morphic_agent.content.paths import star_suite_root

    return star_suite_root()


STAR_BULK_PE_WORKFLOW_ID = "star_bulk_pe_batch"

BAM_SORT_TO_SAM_TYPE: dict[str, tuple[str, str]] = {
    "none": ("None", "None"),
    "sorted": ("BAM", "SortedByCoordinate"),
    "unsorted": ("BAM", "Unsorted"),
}


def build_star_bulk_pe_workflow_params(
    params: dict[str, Any],
    *,
    out_prefix: str | None = None,
) -> dict[str, Any]:
    reads = params.get("reads") or []
    mate1: list[str] = []
    mate2: list[str] = []
    for item in reads:
        if not isinstance(item, dict):
            continue
        mate1.append(str(item.get("r1") or "").strip())
        mate2.append(str(item.get("r2") or "").strip())

    bam_sort = str(params.get("bam_sort") or "sorted")
    out_sam_kind, out_sam_sort = BAM_SORT_TO_SAM_TYPE.get(bam_sort, BAM_SORT_TO_SAM_TYPE["sorted"])

    prefix = str(
        out_prefix
        or params.get("out_file_name_prefix")
        or params.get("output_prefix")
        or ""
    ).strip()
    if prefix and not prefix.endswith("/"):
        prefix = f"{prefix}/"

    threads = int(params.get("run_thread_n", params.get("threads", 16)))
    return {
        "run_mode": "alignReads",
        "genome_dir": str(params.get("genome_dir") or "").strip(),
        "read_files_mate1": ",".join(mate1),
        "read_files_mate2": ",".join(mate2),
        "out_file_name_prefix": prefix,
        "out_file_name_prefix_auto": int(params.get("out_file_name_prefix_auto", 1)),
        "batch_mode": int(params.get("batch_mode", 1)),
        "out_sam_kind": out_sam_kind,
        "out_sam_sort": out_sam_sort,
        "run_thread_n": threads,
    }


def validate_star_bulk_pe_workflow_params(
    workflow_params: dict[str, Any],
    *,
    check_paths: bool = True,
) -> list[str]:
    errors: list[str] = []

    genome_dir = str(workflow_params.get("genome_dir") or "").strip()
    if not genome_dir:
        errors.append("genome_dir is required for STAR bulk PE alignment")
    elif check_paths and not Path(genome_dir).is_dir():
        errors.append(f"genome_dir is not an existing directory: {genome_dir}")

    mate1 = str(workflow_params.get("read_files_mate1") or "").strip()
    mate2 = str(workflow_params.get("read_files_mate2") or "").strip()
    if not mate1 or not mate2:
        errors.append("read_files_mate1 and read_files_mate2 are required")
    else:
        paths1 = [part.strip() for part in mate1.split(",") if part.strip()]
        paths2 = [part.strip() for part in mate2.split(",") if part.strip()]
        if not paths1 or not paths2:
            errors.append("read_files_mate1 and read_files_mate2 must be non-empty")
        elif len(paths1) != len(paths2):
            errors.append("read_files_mate1 and read_files_mate2 must have the same number of entries")
        elif check_paths:
            for path_text in paths1 + paths2:
                if not Path(path_text).exists():
                    errors.append(f"FASTQ path does not exist: {path_text}")

    prefix = str(workflow_params.get("out_file_name_prefix") or "").strip()
    if not prefix:
        errors.append("out_file_name_prefix is required")

    if str(workflow_params.get("run_mode") or "") != "alignReads":
        errors.append("run_mode must be alignReads")

    return errors


def build_star_argv_preview(workflow_params: dict[str, Any]) -> list[str]:
    """Conservative raw STAR preview when STAR suite render is unavailable.

    Suite-specific batch flags stay out of this preview. Executable readiness
    still requires the suite renderer so we do not treat this as a proven
    replacement for the curated STAR Suite workflow.
    """
    argv = [
        "STAR",
        "--runMode",
        str(workflow_params["run_mode"]),
        "--genomeDir",
        str(workflow_params["genome_dir"]),
        "--readFilesIn",
        str(workflow_params["read_files_mate1"]),
        str(workflow_params["read_files_mate2"]),
        "--outFileNamePrefix",
        str(workflow_params["out_file_name_prefix"]),
        "--runThreadN",
        str(int(workflow_params.get("run_thread_n", workflow_params.get("threads", 16)))),
    ]
    kind = str(workflow_params.get("out_sam_kind") or "")
    sort = str(workflow_params.get("out_sam_sort") or "")
    if kind and sort and kind != "None":
        argv.extend(["--outSAMtype", kind, sort])
    return argv


def argv_preview_is_runnable(argv: list[str]) -> bool:
    if not argv or argv[0] != "STAR":
        return False
    joined = " ".join(argv)
    return "<" not in joined and ">" not in joined


def try_render_star_workflow_command(
    workflow_params: dict[str, Any],
    *,
    star_root: str | Path,
) -> tuple[bool, str | None, list[str] | None]:
    root = Path(star_root)
    workflows_py = root / "mcp_server" / "tools" / "workflows.py"
    if not workflows_py.is_file():
        return False, "STAR suite workflows module not found", None

    script = """
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from mcp_server.config import load_config
from mcp_server.tools.workflows import render_workflow_command

workflow_params = json.loads(sys.argv[2])
load_config(Path(sys.argv[1]) / "mcp_server" / "config.yaml")
result = render_workflow_command("star_bulk_pe_batch", workflow_params)
print(json.dumps(result.argv))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(root), json.dumps(workflow_params)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(root),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc), None

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "STAR workflow render failed").strip()
        return False, message, None

    try:
        argv = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError:
        return False, "STAR workflow render returned invalid argv JSON", None
    if not isinstance(argv, list) or not argv:
        return False, "STAR workflow render returned an empty argv", None
    return True, None, [str(part) for part in argv]


def assess_star_render_readiness(
    params: dict[str, Any],
    *,
    out_prefix: str | None = None,
    star_root: str | Path | None = None,
    check_paths: bool = True,
) -> dict[str, Any]:
    workflow_params = build_star_bulk_pe_workflow_params(params, out_prefix=out_prefix)
    errors = validate_star_bulk_pe_workflow_params(workflow_params, check_paths=check_paths)
    argv_preview = build_star_argv_preview(workflow_params)
    preview_ok = not errors and argv_preview_is_runnable(argv_preview)

    suite_render_ok = False
    suite_argv: list[str] | None = None
    suite_error: str | None = None
    root = _resolved_star_root(star_root)
    if not errors:
        suite_render_ok, suite_error, suite_argv = try_render_star_workflow_command(
            workflow_params,
            star_root=root,
        )

    render_ok = suite_render_ok and suite_argv is not None
    render_mode = "suite" if render_ok else ("raw_preview_only" if preview_ok else "none")
    return {
        "workflow_params": workflow_params,
        "errors": errors,
        "argv_preview": argv_preview,
        "preview_ok": preview_ok,
        "fallback_preview_ok": preview_ok,
        "suite_render_ok": suite_render_ok,
        "suite_argv": suite_argv,
        "suite_error": suite_error,
        "render_ok": render_ok,
        "render_mode": render_mode,
    }
