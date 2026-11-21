"""Default content-root configuration for platform tests."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_DEFAULT_CONTENT_ROOT = _FIXTURES
_CATALOG_FIXTURE = _FIXTURES / "module_catalog.json"
_CATALOG_RELATIVE = Path("deploy") / "workbench" / "registry" / "v0" / "modules.json"


def _fixture_content_root() -> Path:
    """Content root that serves the synthetic catalog at the path the loader expects.

    The release scrub rejects a committed directory with that name, so the
    layout is assembled in a temporary directory from the fixture files.
    """
    root = Path(tempfile.mkdtemp(prefix="workbench-content-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    for entry in _FIXTURES.iterdir():
        (root / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    target = root / _CATALOG_RELATIVE
    target.parent.mkdir(parents=True)
    shutil.copyfile(_CATALOG_FIXTURE, target)
    # Binary-format inputs are ignored by version control, so generate the placeholder here.
    data = root / "data"
    data.mkdir(exist_ok=True)
    (data / "demo_trimodal_small.h5mu").write_text("synthetic placeholder for a trimodal MuData file\n", encoding="utf-8")
    return root


_configured = os.environ.get("MORPHIC_RECIPES_TUTORIALS_ROOT")
if not _configured:
    sibling = Path(__file__).resolve().parents[1].parent / "recipes-tutorials"
    if sibling.is_dir():
        os.environ["MORPHIC_RECIPES_TUTORIALS_ROOT"] = str(sibling)
    else:
        os.environ["MORPHIC_RECIPES_TUTORIALS_ROOT"] = str(_fixture_content_root())
elif Path(_configured).expanduser().resolve() == _FIXTURES.resolve() and not (_FIXTURES / _CATALOG_RELATIVE).exists():
    os.environ["MORPHIC_RECIPES_TUTORIALS_ROOT"] = str(_fixture_content_root())


def _synthetic_multiomics_suite() -> Path:
    """Minimal suite checkout that exposes one trimodal recipe to the suite inventory."""
    root = Path(tempfile.mkdtemp(prefix="workbench-multiomics-suite-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    server = root / "mcp_server"
    server.mkdir()
    (server / "config.yaml").write_text(
        "workflows:\n"
        "  - id: synthetic_trimodal_qc\n"
        "    title: Synthetic trimodal QC report\n"
        "    summary: Synthetic trimodal MuData QC recipe used by tests.\n"
        "    kind: workflow\n",
        encoding="utf-8",
    )
    return root


if not os.environ.get("MULTIOMICS_SUITE_ROOT"):
    _sibling_suite = Path(__file__).resolve().parents[1].parent / "multiomics-suite"
    if not _sibling_suite.is_dir():
        os.environ["MULTIOMICS_SUITE_ROOT"] = str(_synthetic_multiomics_suite())
