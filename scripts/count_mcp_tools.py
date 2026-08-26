#!/usr/bin/env python3
"""Count the tools registered by the public Workbench MCP server."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from fastmcp import Client

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from morphic_agent.mcp import build_workbench_mcp
from morphic_agent.workbench import WorkbenchService


async def _measure() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="biodepot-workbench-mcp-") as directory:
        root = Path(directory)
        service = WorkbenchService.create(db_path=root / "workbench.sqlite3")
        server = build_workbench_mcp(service=service, bundle_root=root / "bundles")
        async with Client(server) as client:
            names = sorted(tool.name for tool in await client.list_tools())
    return {"tool_count": len(names), "tools": names}


def main() -> int:
    print(json.dumps(asyncio.run(_measure()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
