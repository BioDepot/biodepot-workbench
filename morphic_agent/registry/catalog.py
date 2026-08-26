"""Module catalog loader — Postgres-shaped read API over the seed JSON registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from morphic_agent.content.paths import module_catalog_path
from morphic_agent.registry.store import AgentStore
from morphic_agent.suites.module_import import suite_recipe_graphs_from_modules, suite_recipe_module_catalog


def _default_catalog_path() -> Path:
    return module_catalog_path()


def _validate_module(module: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    module_id = str(module.get("module_id") or f"index:{index}")
    if not module.get("module_id"):
        errors.append(f"{module_id}: missing module_id")
    if not module.get("title"):
        errors.append(f"{module_id}: missing title")
    if not isinstance(module.get("runtime"), dict):
        errors.append(f"{module_id}: runtime must be an object")
    for field in ("inputs", "outputs"):
        for item_index, item in enumerate(module.get(field) or []):
            if not isinstance(item, dict):
                errors.append(f"{module_id}: {field}[{item_index}] must be an object")
                continue
            if not item.get("name") or not item.get("artifact_type"):
                errors.append(f"{module_id}: {field}[{item_index}] needs name and artifact_type")
    return errors


class ModuleCatalog:
  def __init__(
      self,
      catalog_path: str | Path | None = None,
      *,
      store: AgentStore | None = None,
      import_suite_recipes: bool = True,
  ) -> None:
      self.catalog_path = Path(catalog_path or _default_catalog_path())
      self.store = store
      self._payload = self._load()
      self.import_manifest: dict[str, Any] | None = None
      self.suite_import_manifest: dict[str, Any] | None = None
      self.suite_graph_import_manifest: dict[str, Any] | None = None
      self.compatibility_import_manifest: dict[str, Any] | None = None
      if self.store is not None and not self._payload.get("errors"):
          self.import_manifest = self.store.import_module_catalog(self._payload, source_path=self.catalog_path)
          if import_suite_recipes:
              reserved = {
                  str(module.get("module_id") or "")
                  for module in self._payload.get("modules") or []
                  if isinstance(module, dict) and module.get("module_id")
              }
              suite_payload = suite_recipe_module_catalog(reserved_module_ids=reserved)
              if suite_payload.get("modules"):
                  self.suite_import_manifest = self.store.import_module_catalog(
                      suite_payload,
                      source_path="suite-recipes://star-chromap-multiomics",
                  )
                  graph_count = 0
                  for graph in suite_recipe_graphs_from_modules(suite_payload["modules"]):
                      self.store.record_subgraph(graph, version="suite-recipe")
                      graph_count += 1
                  self.suite_graph_import_manifest = {
                      "schema": "morphic.suite_recipe_graph_import/v0",
                      "graph_count": graph_count,
                  }
          self.compatibility_import_manifest = self.store.rebuild_compatibility_edges()

  def _load(self) -> dict[str, Any]:
      try:
          payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
      except (OSError, json.JSONDecodeError) as exc:
          return {
              "schema": "morphic.module_catalog/v0",
              "modules": [],
              "errors": [{"path": str(self.catalog_path), "message": str(exc)}],
          }
      modules = payload.get("modules") if isinstance(payload.get("modules"), list) else []
      errors: list[str] = []
      normalized: list[dict[str, Any]] = []
      seen: set[str] = set()
      for index, module in enumerate(modules):
          if not isinstance(module, dict):
              errors.append(f"index:{index}: module must be an object")
              continue
          module_id = str(module.get("module_id") or "")
          if module_id in seen:
              errors.append(f"{module_id}: duplicate module_id")
              continue
          seen.add(module_id)
          errors.extend(_validate_module(module, index))
          normalized.append(module)
      return {
          "schema": str(payload.get("schema") or "morphic.module_catalog/v0"),
          "modules": normalized,
          "errors": errors,
      }

  def reload(self) -> None:
      self._payload = self._load()

  def list_modules(self, query: str = "", filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
      if self.store is not None:
          return [self.summarize(module) for module in self.store.list_module_contracts(query, filters)]
      filters = filters or {}
      needle = query.lower().strip()
      capability = str(filters.get("capability") or "").lower().strip()
      out: list[dict[str, Any]] = []
      for module in self._payload["modules"]:
          haystack = " ".join(
              [
                  str(module.get("module_id") or ""),
                  str(module.get("title") or ""),
                  str(module.get("description") or ""),
                  " ".join(module.get("capabilities") or []),
                  json.dumps(module.get("runtime") or {}, sort_keys=True),
                  json.dumps(module.get("suite_recipe") or {}, sort_keys=True),
              ]
          ).lower()
          if needle and needle not in haystack:
              continue
          if capability and capability not in haystack:
              continue
          out.append(self.summarize(module))
      return out

  def get_module(self, module_id: str) -> dict[str, Any] | None:
      if self.store is not None:
          return self.store.get_module_contract(module_id)
      for module in self._payload["modules"]:
          if str(module.get("module_id") or "") == module_id:
              return module
      return None

  @staticmethod
  def summarize(module: dict[str, Any]) -> dict[str, Any]:
      return {
          "module_id": module.get("module_id"),
          "title": module.get("title"),
          "capabilities": module.get("capabilities") or [],
          "input_artifact_types": [
              item.get("artifact_type") for item in module.get("inputs") or [] if isinstance(item, dict)
          ],
          "output_artifact_types": [
              item.get("artifact_type") for item in module.get("outputs") or [] if isinstance(item, dict)
          ],
          "runtime": module.get("runtime") or {},
          "first_class_workbench_recipe": bool(module.get("first_class_workbench_recipe")),
          "recipe_family": module.get("recipe_family"),
          "assay_profile": module.get("assay_profile"),
          "modalities": module.get("modalities") or [],
          "dataset_scope": module.get("dataset_scope"),
          "execution_policy": module.get("execution_policy") or {},
          "confidence_tier": module.get("confidence_tier"),
          "evidence": module.get("evidence") or [],
      }

  def modules_by_id(self, module_ids: list[str]) -> dict[str, dict[str, Any]]:
      out: dict[str, dict[str, Any]] = {}
      for module_id in module_ids:
          module = self.get_module(module_id)
          if module:
              out[module_id] = module
      return out
