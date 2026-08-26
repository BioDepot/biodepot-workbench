"""Resolve optional content roots from environment or sibling checkouts."""

from __future__ import annotations

import os
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONTENT = _PLATFORM_ROOT.parent / "recipes-tutorials"

_DEFAULT_SUITE_ROOTS = {
    "star": _PLATFORM_ROOT.parent / "STAR-suite",
    "chromap": _PLATFORM_ROOT.parent / "Chromap-suite",
    "multiomics": _PLATFORM_ROOT.parent / "multiomics-suite",
}


def platform_root() -> Path:
    return _PLATFORM_ROOT


def recipes_tutorials_root() -> Path:
    configured = str(os.environ.get("MORPHIC_RECIPES_TUTORIALS_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    sibling = _PLATFORM_ROOT.parent / "recipes-tutorials"
    if sibling.is_dir():
        return sibling.resolve()
    return _DEFAULT_CONTENT.resolve()


def suite_roots() -> dict[str, Path]:
    return {
        "star": Path(os.environ.get("STAR_SUITE_ROOT", str(_DEFAULT_SUITE_ROOTS["star"]))).expanduser().resolve(),
        "chromap": Path(os.environ.get("CHROMAP_SUITE_ROOT", str(_DEFAULT_SUITE_ROOTS["chromap"]))).expanduser().resolve(),
        "multiomics": Path(os.environ.get("MULTIOMICS_SUITE_ROOT", str(_DEFAULT_SUITE_ROOTS["multiomics"]))).expanduser().resolve(),
    }


def suite_root(suite_id: str) -> Path | None:
    return suite_roots().get(str(suite_id or "").strip().lower())


def star_suite_root() -> Path:
    return suite_roots()["star"]


def chromap_suite_root() -> Path:
    return suite_roots()["chromap"]


def multiomics_suite_root() -> Path:
    return suite_roots()["multiomics"]


def star_plot_contracts_dir() -> Path:
    return star_suite_root() / "docs" / "examples" / "example_perturb_plot_contracts"


def scheduler_startup_script() -> str:
    configured = str(os.environ.get("MORPHIC_SCHEDULER_STARTUP_SCRIPT") or "").strip()
    if configured:
        return configured
    return ""


def content_roots() -> list[Path]:
    raw = str(os.environ.get("MORPHIC_AGENT_CONTENT_ROOTS") or "").strip()
    if raw:
        roots: list[Path] = []
        for item in raw.split(os.pathsep):
            text = item.strip()
            if text:
                roots.append(Path(text).expanduser().resolve())
        return roots
    return [recipes_tutorials_root()]


def module_catalog_path() -> Path:
    return recipes_tutorials_root() / "deploy" / "workbench" / "registry" / "v0" / "modules.json"
