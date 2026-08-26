"""MCP adapters for the BioDepot Workbench service."""

__all__ = ["build_workbench_mcp"]


def __getattr__(name: str):
    if name == "build_workbench_mcp":
        from .server import build_workbench_mcp

        return build_workbench_mcp
    raise AttributeError(name)
