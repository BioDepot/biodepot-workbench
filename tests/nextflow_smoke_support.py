"""Shared tiny Nextflow bundle builder for gated smoke tests."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

from morphic_agent.execution.nextflow import DEFAULT_NEXTFLOW_SOURCE_ROOT, install_local_nf_temporal_plugin, local_nextflow_binary


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nextflow"


def make_tiny_nextflow_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "tiny_nextflow_bundle"
    manifests = bundle / "manifests"
    shutil.copytree(FIXTURE_ROOT / "tiny_workflow", bundle / "workflow")
    manifests.mkdir(parents=True)
    params = {"message": "hello from tiny nextflow smoke", "outdir": "results"}
    (bundle / "nf-params.json").write_text(json.dumps(params, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle / "workflow_graph.json").write_text(
        json.dumps(
            {
                "schema": "morphic.workflow_graph/v0",
                "graph_id": "tiny_nextflow_smoke_v0",
                "runtime": {
                    "kind": "nextflow",
                    "pipeline": str(bundle / "workflow"),
                    "release": None,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (manifests / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "schema": "morphic.nextflow_test_bundle/v0",
                "graph_id": "tiny_nextflow_smoke_v0",
                "pipeline": str(bundle / "workflow"),
                "params_hash": "sha256:test",
                "source_manifest_hash": "sha256:test-source",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    script = bundle / "run.nextflow.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'BUNDLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'
        'NEXTFLOW_BIN="${NEXTFLOW_BIN:-nextflow}"\n'
        'cmd=("$NEXTFLOW_BIN" run "$BUNDLE_DIR/workflow")\n'
        'if [[ -n "${NEXTFLOW_CONFIG_FILE:-}" ]]; then\n'
        '  cmd+=(-c "$NEXTFLOW_CONFIG_FILE")\n'
        "fi\n"
        'cmd+=(-with-trace "$BUNDLE_DIR/manifests/nextflow-trace.txt")\n'
        'cmd+=(-with-report "$BUNDLE_DIR/manifests/nextflow-report.html")\n'
        'cmd+=(-with-timeline "$BUNDLE_DIR/manifests/nextflow-timeline.html")\n'
        'cmd+=(-params-file "$BUNDLE_DIR/nf-params.json")\n'
        'exec "${cmd[@]}" "$@"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bundle
