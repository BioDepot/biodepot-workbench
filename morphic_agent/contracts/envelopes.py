"""Structured BioDepot tool response envelope."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolResponse:
    schema_version: str
    tool: str
    stable_id: str
    status: str
    payload: dict[str, Any]
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence_tier: str = "source_derived"
    blockers: list[str] = field(default_factory=list)
    required_human_decisions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
