"""Small identity helpers shared by public storage repositories."""

from __future__ import annotations

import re
from typing import Any


def safe_workspace_slug(value: Any, fallback: str = "anonymous") -> str:
    """Return a bounded filesystem-safe identity component."""

    text = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip(".-")
    return text[:80] or fallback
