"""Configuration loading: model profiles, Launchpad endpoint, SSH tunnels.

Resolution order:
  - model profiles come from config/models.yaml (falls back to
    config/models.example.yaml if you haven't copied it yet);
  - the active profile is MORPHIC_LLM_PROFILE, else the file's default_profile;
  - ${VAR} tokens anywhere in the YAML are filled from the environment (so keys
    and URLs live in .env, never in git).

Both the LLM and the Launchpad can optionally be reached over an SSH tunnel —
the same mechanism that lets a thin cloud client use host-local assets without
downloading them. See sshtunnel.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .llm import ProviderConfig
from .sshtunnel import SshTarget, SshTunnel

REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: Any) -> Any:
    """Recursively replace ${VAR} with os.environ (missing -> empty string)."""
    if isinstance(value, str):
        return _ENV_TOKEN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class ModelsConfigMissing(RuntimeError):
    """Raised when neither config/models.yaml nor config/models.example.yaml exists."""


def _models_path() -> Path | None:
    for name in ("models.yaml", "models.example.yaml"):
        candidate = REPO_ROOT / "config" / name
        if candidate.exists():
            return candidate
    return None


@dataclass
class TunnelSpec:
    enabled: bool
    ssh_host: str
    remote_port: int
    local_port: int
    ssh_user: str | None = None
    ssh_key: str | None = None

    def build(self) -> SshTunnel:
        target = SshTarget(host=self.ssh_host, user=self.ssh_user or None, key_path=self.ssh_key or None)
        return SshTunnel(target, remote_port=self.remote_port, local_port=self.local_port)


def _tunnel_from(spec: dict[str, Any] | None) -> TunnelSpec | None:
    if not spec or not spec.get("enabled"):
        return None
    return TunnelSpec(
        enabled=True,
        ssh_host=str(spec["ssh_host"]),
        remote_port=int(spec["remote_port"]),
        local_port=int(spec.get("local_port") or spec["remote_port"]),
        ssh_user=(str(spec["ssh_user"]) if spec.get("ssh_user") else None),
        ssh_key=(str(spec["ssh_key"]) if spec.get("ssh_key") else None),
    )


@dataclass
class AppConfig:
    provider: ProviderConfig
    provider_tunnel: TunnelSpec | None = None
    launchpad_base_url: str = "http://127.0.0.1:8875"
    launchpad_token: str | None = None
    launchpad_tunnel: TunnelSpec | None = None
    profile_name: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


def _provider_from_profile(name: str, profile: dict[str, Any]) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        kind=str(profile.get("kind", "openai")),
        model=str(profile["model"]),
        base_url=str(profile.get("base_url", "")),
        api_key=(profile.get("api_key") or None),
        temperature=profile.get("temperature", 0.0),
        max_tokens=int(profile.get("max_tokens", 1536)),
        extra_payload=dict(profile.get("extra_payload") or {}),
        timeout=int(profile.get("timeout", 120)),
    )


def load_config(profile_override: str | None = None) -> AppConfig:
    path = _models_path()
    if path is None:
        raise ModelsConfigMissing("no model config file (config/models.yaml) found")
    raw = _expand(yaml.safe_load(path.read_text()) or {})
    profiles: dict[str, Any] = raw.get("profiles") or {}
    if not profiles:
        raise RuntimeError("no model profiles defined in config/models*.yaml")

    name = (
        profile_override
        or os.environ.get("MORPHIC_LLM_PROFILE")
        or raw.get("default_profile")
        or next(iter(profiles))
    )
    if name not in profiles:
        raise RuntimeError(f"unknown model profile {name!r}; have: {', '.join(profiles)}")
    profile = profiles[name]

    # Launchpad config: env wins, then an optional `launchpad:` block in the YAML.
    lp = raw.get("launchpad") or {}
    base_url = os.environ.get("LAUNCHPAD_BASE_URL") or lp.get("base_url") or "http://127.0.0.1:8875"
    token = os.environ.get("LAUNCHPAD_AUTH_TOKEN") or lp.get("auth_token") or None

    return AppConfig(
        provider=_provider_from_profile(name, profile),
        provider_tunnel=_tunnel_from(profile.get("ssh_tunnel")),
        launchpad_base_url=base_url.rstrip("/"),
        launchpad_token=token,
        launchpad_tunnel=_tunnel_from(lp.get("ssh_tunnel")),
        profile_name=name,
    )
