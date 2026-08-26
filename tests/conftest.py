"""Default content-root configuration for platform tests."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_CONTENT_ROOT = Path(__file__).resolve().parent / "fixtures"

if not os.environ.get("MORPHIC_RECIPES_TUTORIALS_ROOT"):
    sibling = Path(__file__).resolve().parents[1].parent / "recipes-tutorials"
    if sibling.is_dir():
        os.environ["MORPHIC_RECIPES_TUTORIALS_ROOT"] = str(sibling)
    else:
        os.environ["MORPHIC_RECIPES_TUTORIALS_ROOT"] = str(_DEFAULT_CONTENT_ROOT)
