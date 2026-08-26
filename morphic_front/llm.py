"""Provider-agnostic chat client.

One small surface (`ChatClient.complete(system, user) -> str`) over two wire
protocols, so the same agent loop drives any of:

  - free hosted gemma4 (vLLM, OpenAI-compatible) ...... kind="openai"
  - OpenAI / any OpenAI-compatible endpoint ........... kind="openai"
  - local vLLM or Ollama (`/v1`) ..................... kind="openai"
  - Anthropic Claude (Messages API) ................. kind="anthropic"

This file is intentionally *provider-neutral* — it is not Anthropic-SDK code.
The Anthropic branch speaks the Messages API over plain HTTP
(`POST /v1/messages`, `x-api-key`, `anthropic-version`) so it sits beside the
OpenAI-compatible branch without dragging in an SDK; the front end stays at
three lean deps. Credentials and endpoints come from config (see config.py);
nothing secret is hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

# Default Claude model and API version for the Anthropic branch. Override the
# model per-profile; api_version rarely changes.
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class ProviderConfig:
    name: str                         # profile name, e.g. "gemma4"
    kind: str                         # "openai" | "anthropic"
    model: str
    base_url: str = ""                # openai: ".../v1"; anthropic: "https://api.anthropic.com"
    api_key: str | None = None        # omitted for keyless local models
    temperature: float | None = 0.0   # ignored by the anthropic branch (4.x reject it)
    max_tokens: int = 1536
    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    extra_payload: dict[str, Any] = field(default_factory=dict)
    timeout: int = 120

    def __post_init__(self) -> None:
        if self.kind not in {"openai", "anthropic"}:
            raise ValueError(f"unknown provider kind: {self.kind!r} (use 'openai' or 'anthropic')")
        if self.kind == "anthropic" and not self.base_url:
            self.base_url = "https://api.anthropic.com"
        self.base_url = self.base_url.rstrip("/")


class ChatClient:
    """Thin OpenAI/Anthropic chat client returning assistant text."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def complete(self, system: str, user: str) -> str:
        if self.config.kind == "openai":
            return self._complete_openai(system, user)
        return self._complete_anthropic(system, user)

    # -- OpenAI-compatible: gemma4 (vLLM), OpenAI, local vLLM/Ollama ----------
    def _complete_openai(self, system: str, user: str) -> str:
        cfg = self.config
        url = f"{cfg.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": cfg.max_tokens,
            **cfg.extra_payload,
        }
        if cfg.temperature is not None:
            payload["temperature"] = cfg.temperature
        data = self._post(url, headers, payload)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected OpenAI-style response: {data}") from exc

    # -- Anthropic Messages API ---------------------------------------------
    def _complete_anthropic(self, system: str, user: str) -> str:
        cfg = self.config
        url = f"{cfg.base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": cfg.anthropic_version,
        }
        if cfg.api_key:
            headers["x-api-key"] = cfg.api_key
        # Note: no temperature/top_p — current Claude 4.x models reject them.
        payload: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            **cfg.extra_payload,
        }
        data = self._post(url, headers, payload)
        try:
            return "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
        except (AttributeError, TypeError) as exc:
            raise RuntimeError(f"unexpected Anthropic response: {data}") from exc

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(url, headers=headers, json=payload, timeout=self.config.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM request failed [{resp.status_code}] {url}: {resp.text[:500]}")
        return resp.json()
