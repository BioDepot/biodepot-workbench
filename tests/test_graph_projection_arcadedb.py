"""Opt-in ArcadeDB projection adapter smoke tests."""

from __future__ import annotations

import os

import pytest

from morphic_agent.graph.projection import ArcadeDBProjectionRepository


pytestmark = pytest.mark.skipif(
    os.environ.get("MORPHIC_RUN_ARCADEDB") != "1",
    reason="set MORPHIC_RUN_ARCADEDB=1 to run ArcadeDB projection adapter tests",
)


def test_arcadedb_projection_adapter_requires_configured_endpoint():
    if not os.environ.get("MORPHIC_ARCADEDB_URL"):
        pytest.skip("MORPHIC_ARCADEDB_URL is not configured")

    adapter = ArcadeDBProjectionRepository()

    assert adapter.adapter_name == "arcadedb"
    assert adapter.endpoint == os.environ["MORPHIC_ARCADEDB_URL"]
