"""LLM fallback for conversational questions outside local graph coverage."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from morphic_front.config import ModelsConfigMissing, load_config
from morphic_front.llm import ChatClient, ProviderConfig

_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off"}
_NO_PROVIDER_MESSAGE = (
    "No LLM provider is configured. Set MODEL_BASE_URL/MODEL_API_KEY "
    "or MORPHIC_AGENT_MODEL_BASE_URL/MORPHIC_AGENT_MODEL_API_KEY, "
    "or allow config/models.yaml by unsetting MORPHIC_AGENT_DISABLE_CONFIG_LLM."
)


def _profile_unconfigured(provider: ProviderConfig, tunneled: bool) -> bool:
    """A profile whose base_url expanded to empty (and has no tunnel) cannot be called."""
    return not tunneled and not str(provider.base_url or "").strip()


def _env_provider_config() -> ProviderConfig | None:
    base_url = os.environ.get("MORPHIC_AGENT_MODEL_BASE_URL") or os.environ.get("MODEL_BASE_URL")
    api_key = os.environ.get("MORPHIC_AGENT_MODEL_API_KEY") or os.environ.get("MODEL_API_KEY") or None
    model = (
        os.environ.get("MORPHIC_AGENT_MODEL_NAME")
        or os.environ.get("MODEL_NAME")
        or os.environ.get("MORPHIC_AGENT_DEFAULT_MODEL")
        or os.environ.get("DEFAULT_MODEL")
        or "gemma4-report"
    )
    if base_url:
        return ProviderConfig(
            name="env",
            kind="openai",
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_tokens=int(os.environ.get("MORPHIC_AGENT_LLM_MAX_TOKENS") or "700"),
            timeout=int(os.environ.get("MORPHIC_AGENT_LLM_TIMEOUT") or "45"),
        )

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        return ProviderConfig(
            name="openai",
            kind="openai",
            model=os.environ.get("OPENAI_MODEL") or "gpt-4o-mini",
            base_url=os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            api_key=openai_key,
            max_tokens=int(os.environ.get("MORPHIC_AGENT_LLM_MAX_TOKENS") or "700"),
            timeout=int(os.environ.get("MORPHIC_AGENT_LLM_TIMEOUT") or "45"),
        )
    return None


def _config_llm_enabled() -> bool:
    if str(os.environ.get("MORPHIC_AGENT_DISABLE_CONFIG_LLM") or "").strip().lower() in _TRUTHY:
        return False
    raw = os.environ.get("MORPHIC_AGENT_ENABLE_CONFIG_LLM")
    if raw is not None:
        return str(raw).strip().lower() not in _FALSEY
    return True


def complete_with_llm_fallback(goal: str, context: dict[str, Any]) -> dict[str, Any]:
    config = _env_provider_config()
    if config is not None:
        return _complete_with_config(goal, context, config)

    if _config_llm_enabled():
        try:
            app_config = load_config(os.environ.get("MORPHIC_AGENT_LLM_PROFILE") or None)
            if _profile_unconfigured(app_config.provider, bool(app_config.provider_tunnel)):
                return {"ok": False, "error": _NO_PROVIDER_MESSAGE}
            if app_config.provider_tunnel:
                with app_config.provider_tunnel.build() as tunnel:
                    provider = replace(app_config.provider, base_url=f"{tunnel.local_url}/v1")
                    return _complete_with_config(goal, context, provider)
            return _complete_with_config(goal, context, app_config.provider)
        except ModelsConfigMissing:
            return {"ok": False, "error": _NO_PROVIDER_MESSAGE}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "provider": "config"}

    if config is None:
        return {
            "ok": False,
            "error": (
                "No LLM provider is configured. Set MODEL_BASE_URL/MODEL_API_KEY "
                "or MORPHIC_AGENT_MODEL_BASE_URL/MORPHIC_AGENT_MODEL_API_KEY, "
                "or allow config/models.yaml by unsetting MORPHIC_AGENT_DISABLE_CONFIG_LLM."
            ),
        }


def llm_provider_status() -> dict[str, Any]:
    config = _env_provider_config()
    if config is not None:
        return {
            "configured": True,
            "provider": config.name,
            "model": config.model,
            "source": "environment",
        }

    if _config_llm_enabled():
        try:
            app_config = load_config(os.environ.get("MORPHIC_AGENT_LLM_PROFILE") or None)
        except ModelsConfigMissing:
            return {"configured": False, "available": False, "error": _NO_PROVIDER_MESSAGE}
        except Exception as exc:
            return {
                "configured": False,
                "available": False,
                "provider": "config",
                "error": str(exc),
                "source": "config",
            }
        if _profile_unconfigured(app_config.provider, bool(app_config.provider_tunnel)):
            return {"configured": False, "available": False, "error": _NO_PROVIDER_MESSAGE}
        return {
            "configured": True,
            "provider": app_config.provider.name,
            "model": app_config.provider.model,
            "source": "config",
            "profile": os.environ.get("MORPHIC_AGENT_LLM_PROFILE") or None,
            "uses_tunnel": bool(app_config.provider_tunnel),
        }

    return {
        "configured": False,
        "available": False,
        "error": (
            "No LLM provider is configured. Set MODEL_BASE_URL/MODEL_API_KEY "
            "or MORPHIC_AGENT_MODEL_BASE_URL/MORPHIC_AGENT_MODEL_API_KEY, "
            "or allow config/models.yaml by unsetting MORPHIC_AGENT_DISABLE_CONFIG_LLM."
        ),
    }


def check_llm_available(*, probe: bool = False) -> dict[str, Any]:
    status = llm_provider_status()
    if not status.get("configured"):
        return {**status, "available": False, "probe": False}
    if not probe:
        return {**status, "available": None, "probe": False}

    result = complete_with_llm_fallback(
        "Reply with exactly: OK",
        {"purpose": "model availability probe", "expected_response": "OK"},
    )
    available = bool(result.get("ok") and str(result.get("text") or "").strip())
    return {
        **status,
        "available": available,
        "probe": True,
        "probe_provider": result.get("provider"),
        "probe_model": result.get("model"),
        "error": None if available else result.get("error") or "Model probe returned no text.",
    }


def _complete_with_config(goal: str, context: dict[str, Any], config: ProviderConfig) -> dict[str, Any]:

    system = (
        "You are the BioDepot workbench planning assistant and you are consulted first for every user chat turn. "
        "Drive the conversation: answer the user directly, ask clarifying questions when needed, and recommend "
        "next actions. The local BioDepot/STAR Suite recipes, modules, graphs, and workflows in context are hints "
        "and tools, not a cage; you may also answer from general bioinformatics knowledge when local tooling is "
        "incomplete. Be explicit about what is locally supported versus general guidance. Do not claim that a "
        "run directory, script, or bundle already exists until local tooling has generated one; for a runnable "
        "local graph, say it can materialize a bundle after parameter review and approval. Do not draft "
        "parameters or scripts yourself; ask the user to confirm when local tooling should draft them. When a "
        "candidate_graph_preview is present, use its exact graph_id, module labels, required_human_inputs, and "
        "params_schema field names when discussing needed parameters; do not invent parameter names or file types. "
        "Keep the answer concise."
    )
    user = (
        "User question:\n"
        f"{goal}\n\n"
        "Local context JSON:\n"
        f"{context}"
    )
    try:
        text = ChatClient(config).complete(system, user).strip()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "provider": config.name, "model": config.model}
    return {"ok": True, "text": text, "provider": config.name, "model": config.model}
