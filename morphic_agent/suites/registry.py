"""Read-only suite recipe inventory for broad smoke coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from morphic_agent.content.paths import suite_root as configured_suite_root
from morphic_agent.suites.star import list_star_workflows

SUITE_LABELS = {
    "star": "STAR Suite",
    "chromap": "Chromap Suite",
    "multiomics": "Multiomics Suite",
}


def _list_field(item: dict[str, Any], key: str) -> list[Any]:
    value = item.get(key)
    return value if isinstance(value, list) else []


def _dict_field(item: dict[str, Any], key: str) -> dict[str, Any]:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def _contract_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "parameters": _list_field(item, "parameters"),
        "parameter_groups": _list_field(item, "parameter_groups"),
        "inputs": _list_field(item, "inputs"),
        "outputs": _list_field(item, "outputs"),
        "preflight": _list_field(item, "preflight"),
        "docs": _list_field(item, "docs"),
        "smoke_coverage": _dict_field(item, "smoke_coverage"),
        "handoff_artifacts": _list_field(item, "handoff_artifacts"),
        "command_template": _list_field(item, "command_template"),
        "constraints": _list_field(item, "constraints"),
        "notes": _list_field(item, "notes"),
    }


def suite_root(suite_id: str) -> Path | None:
    return configured_suite_root(suite_id)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _source_exists(root: Path, rel_path: Any) -> bool:
    text = str(rel_path or "").strip()
    if not text:
        return False
    path = Path(text)
    if path.is_absolute():
        return path.exists()
    try:
        resolved = (root / path).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    return resolved.exists()


def _recipe_from_workflow(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    recipe_id = str(item.get("id") or item.get("workflow_id") or "").strip()
    schema_file = str(item.get("schema_file") or f"mcp_server/workflows/{recipe_id}.yaml")
    schema_payload: dict[str, Any] = {}
    if _source_exists(root, schema_file):
        try:
            schema_payload = _load_yaml((root / schema_file).resolve())
        except OSError:
            schema_payload = {}
    contract_source = {**schema_payload, **item}
    return {
        "id": recipe_id,
        "recipe_id": recipe_id,
        "workflow_id": recipe_id,
        "title": str(item.get("title") or schema_payload.get("title") or recipe_id),
        "summary": str(item.get("summary") or schema_payload.get("summary") or ""),
        "kind": str(item.get("kind") or schema_payload.get("kind") or "workflow"),
        "entry_script": item.get("entry_script") or schema_payload.get("entry_script"),
        "schema_file": schema_file,
        "source_kind": "workflow_config",
        "source_path": schema_file,
        "source_exists": _source_exists(root, schema_file),
        "runtime_class": item.get("runtime_class") or schema_payload.get("runtime_class"),
        "visibility": str(item.get("visibility") or "public"),
        **_contract_fields(contract_source),
    }


def _recipe_from_registry_item(root: Path, item: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    recipe_id = str(item.get("id") or item.get("recipe_id") or item.get("workflow_id") or "").strip()
    workflow_id = str(item.get("workflow_id") or recipe_id).strip()
    entry_script = item.get("entry_script")
    schema_file = item.get("schema_file")
    return {
        "id": recipe_id,
        "recipe_id": recipe_id,
        "workflow_id": workflow_id,
        "title": str(item.get("title") or recipe_id),
        "summary": str(item.get("summary") or item.get("purpose") or ""),
        "kind": str(item.get("kind") or item.get("runtime_class") or "recipe"),
        "entry_script": entry_script,
        "schema_file": schema_file,
        "source_kind": "recipe_registry",
        "source_path": source_path,
        "source_exists": True,
        "entry_script_exists": _source_exists(root, entry_script),
        "runtime_class": item.get("runtime_class"),
        "benchmark_policy": item.get("benchmark_policy"),
        "default_visible": item.get("default_visible"),
        "enabled": item.get("enabled", True),
        **_contract_fields(item),
    }


def _from_config(root: Path, suite_id: str, config_rel: str = "mcp_server/config.yaml") -> tuple[list[dict[str, Any]], list[str], list[str]]:
    config_path = root / config_rel
    if not config_path.is_file():
        return [], [], [f"missing config: {config_path}"]
    config = _load_yaml(config_path)
    recipes = [
        _recipe_from_workflow(root, item)
        for item in config.get("workflows") or []
        if isinstance(item, dict) and str(item.get("id") or item.get("workflow_id") or "").strip()
    ]
    for recipe in recipes:
        recipe["suite"] = suite_id
    return recipes, [config_rel], []


def _from_yaml_registry(root: Path, suite_id: str, registry_rel: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    registry_path = root / registry_rel
    if not registry_path.is_file():
        return [], [], [f"missing registry: {registry_path}"]
    registry = _load_yaml(registry_path)
    recipes = [
        _recipe_from_registry_item(root, item, source_path=registry_rel)
        for item in registry.get("recipes") or []
        if isinstance(item, dict) and str(item.get("id") or item.get("recipe_id") or item.get("workflow_id") or "").strip()
    ]
    for recipe in recipes:
        recipe["suite"] = suite_id
    return recipes, [registry_rel], []


def _dedupe_recipes(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for recipe in recipes:
        recipe_id = str(recipe.get("id") or recipe.get("recipe_id") or "").strip()
        if not recipe_id:
            continue
        existing = by_id.get(recipe_id)
        if existing is None:
            by_id[recipe_id] = recipe
            continue
        if existing.get("source_kind") == "workflow_config" and recipe.get("source_kind") == "recipe_registry":
            by_id[recipe_id] = {**existing, **recipe, "schema_file": existing.get("schema_file") or recipe.get("schema_file")}
        else:
            existing.update({key: value for key, value in recipe.items() if value not in (None, "", [])})
    return sorted(by_id.values(), key=lambda item: str(item.get("id") or ""))


def list_suite_recipes(suite_id: str) -> dict[str, Any]:
    suite_id = str(suite_id or "").strip().lower()
    root = suite_root(suite_id)
    if root is None:
        return {
            "schema": "morphic.suite_recipe_inventory/v0",
            "suite": suite_id,
            "label": suite_id,
            "available": False,
            "recipes": [],
            "source_files": [],
            "errors": [f"unknown suite: {suite_id}"],
        }
    if not root.is_dir():
        return {
            "schema": "morphic.suite_recipe_inventory/v0",
            "suite": suite_id,
            "label": SUITE_LABELS.get(suite_id, suite_id),
            "suite_root": str(root),
            "available": False,
            "recipes": [],
            "source_files": [],
            "errors": [f"suite root not found: {root}"],
        }

    errors: list[str] = []
    source_files: list[str] = []
    recipes: list[dict[str, Any]] = []
    if suite_id == "star":
        payload = list_star_workflows(root)
        if payload.get("error"):
            errors.append(str(payload.get("message") or payload.get("code") or "STAR workflow discovery failed"))
        recipes.extend(_recipe_from_workflow(root, item) for item in payload.get("workflows") or [] if isinstance(item, dict))
        source_files.append("mcp_server/config.yaml")
    elif suite_id == "chromap":
        config_recipes, config_sources, config_errors = _from_config(root, suite_id)
        registry_recipes, registry_sources, registry_errors = _from_yaml_registry(root, suite_id, "mcp_server/recipes/registry.yaml")
        recipes.extend(config_recipes)
        recipes.extend(registry_recipes)
        source_files.extend(config_sources + registry_sources)
        errors.extend(config_errors + registry_errors)
    elif suite_id == "multiomics":
        config_recipes, config_sources, _ = _from_config(root, suite_id)
        native_recipes, native_sources, native_errors = _from_yaml_registry(root, suite_id, "mcp_server/recipes/native.yaml")
        recipes.extend(config_recipes)
        recipes.extend(native_recipes)
        source_files.extend(config_sources + native_sources)
        errors.extend(native_errors)

    for recipe in recipes:
        recipe["suite"] = suite_id
    recipes = _dedupe_recipes(recipes)
    return {
        "schema": "morphic.suite_recipe_inventory/v0",
        "suite": suite_id,
        "label": SUITE_LABELS.get(suite_id, suite_id),
        "suite_root": str(root),
        "available": True,
        "recipe_count": len(recipes),
        "recipes": recipes,
        "source_files": sorted(set(source_files)),
        "errors": errors,
    }


def discover_suite_inventory() -> dict[str, Any]:
    suites = [list_suite_recipes(suite_id) for suite_id in ("star", "chromap", "multiomics")]
    return {
        "schema": "morphic.suite_inventory/v0",
        "suites": suites,
        "suite_count": len(suites),
        "available_suite_count": sum(1 for suite in suites if suite.get("available")),
    }
