"""Registry tool implementations."""

from __future__ import annotations

from typing import Any

from morphic_agent.contracts.envelopes import ToolResponse
from morphic_agent.registry.catalog import ModuleCatalog


class RegistryTools:
    def __init__(self, catalog: ModuleCatalog | None = None) -> None:
        self.catalog = catalog or ModuleCatalog()

    def list_modules(self, query: str = "", filters: dict[str, Any] | None = None) -> ToolResponse:
        modules = self.catalog.list_modules(query, filters)
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="list_modules",
            stable_id=f"list_modules:{query}:{filters}",
            status="ok",
            payload={"modules": modules, "count": len(modules)},
            summary=f"Found {len(modules)} module(s) in the local catalog.",
            confidence_tier="curated_profile",
        )

    def get_module_contract(self, module_id: str) -> ToolResponse:
        module = self.catalog.get_module(module_id)
        if not module:
            return ToolResponse(
                schema_version="morphic.tool_response/v0",
                tool="get_module_contract",
                stable_id=f"module:{module_id}",
                status="not_found",
                payload={"module_id": module_id},
                summary=f"No module contract found for `{module_id}`.",
                blockers=[f"unknown module_id `{module_id}`"],
            )
        return ToolResponse(
            schema_version="morphic.tool_response/v0",
            tool="get_module_contract",
            stable_id=f"module:{module_id}",
            status="ok",
            payload={"module": module},
            summary=module.get("title") or module_id,
            evidence=module.get("evidence") or [],
            confidence_tier=str(module.get("confidence_tier") or "source_derived"),
        )
