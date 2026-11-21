"""Model config resolution when no config file or no base URL is available."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

import morphic_front.config as front_config
from morphic_agent.api.workbench_html import WORKBENCH_HTML
from morphic_agent.planner.llm_fallback import complete_with_llm_fallback, llm_provider_status

_ENV_KEYS = (
    "MORPHIC_AGENT_MODEL_BASE_URL",
    "MODEL_BASE_URL",
    "MORPHIC_AGENT_DISABLE_CONFIG_LLM",
    "MORPHIC_AGENT_ENABLE_CONFIG_LLM",
    "MORPHIC_AGENT_LLM_PROFILE",
    "MORPHIC_LLM_PROFILE",
    "EMPTY_PROFILE_URL",
)


@pytest.fixture()
def clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_missing_models_file_reports_no_provider_guidance(clean_env, tmp_path):
    clean_env.setattr(front_config, "REPO_ROOT", tmp_path)
    status = llm_provider_status()
    assert status["configured"] is False
    assert "No LLM provider is configured" in status["error"]
    assert "No such file" not in status["error"]
    result = complete_with_llm_fallback("hello", {})
    assert result["ok"] is False
    assert "No LLM provider is configured" in result["error"]


def test_profile_with_empty_base_url_is_not_configured(clean_env, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "models.yaml").write_text(
        "default_profile: p\nprofiles:\n  p:\n    model: m\n    base_url: ${EMPTY_PROFILE_URL}\n"
    )
    clean_env.setattr(front_config, "REPO_ROOT", tmp_path)
    status = llm_provider_status()
    assert status["configured"] is False
    assert "No LLM provider is configured" in status["error"]
    result = complete_with_llm_fallback("hello", {})
    assert result["ok"] is False
    assert "No LLM provider is configured" in result["error"]


def test_profile_with_base_url_is_configured(clean_env, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "models.yaml").write_text(
        "default_profile: p\nprofiles:\n  p:\n    model: m\n    base_url: ${EMPTY_PROFILE_URL}\n"
    )
    clean_env.setattr(front_config, "REPO_ROOT", tmp_path)
    clean_env.setenv("EMPTY_PROFILE_URL", "http://127.0.0.1:9/v1")
    assert llm_provider_status()["configured"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not available")
@pytest.mark.parametrize(
    ("status", "body", "expect_message", "expect_payload"),
    [
        (502, "<html>Bad Gateway</html>", "HTTP 502", {"error": "<html>Bad Gateway</html>"}),
        (500, '{"detail": "boom"}', "boom", {"detail": "boom"}),
        (200, '{"ok": true}', None, {"ok": True}),
    ],
)
def test_request_json_handles_non_json_error_bodies(status, body, expect_message, expect_payload):
    match = re.search(r"    function requestJson\(path.*?\n    }\n", WORKBENCH_HTML, re.S)
    assert match
    script = (
        "const state = {clientSessionId: 's'}; const appPath = (p) => p;\n"
        + match.group(0)
        + f"""
const status = {status}; const body = {json.dumps(body)};
globalThis.fetch = async () => ({{ok: status < 400, status, text: async () => body}});
requestJson("/x").then(
  (value) => console.log(JSON.stringify({{ok: true, value}})),
  (err) => console.log(JSON.stringify({{ok: false, message: err.message, payload: err.payload}})),
);
"""
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20, check=True)
    result = json.loads(out.stdout)
    if expect_message is None:
        assert result == {"ok": True, "value": expect_payload}
    else:
        assert result["ok"] is False
        assert expect_message in result["message"]
        assert result["payload"] == expect_payload
