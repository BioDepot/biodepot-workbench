"""Structural parser for nf-core-style ``nextflow_schema.json`` files."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


GROUP_SUPPORTED_KEYS = {
    "$comment",
    "$id",
    "$schema",
    "additionalProperties",
    "default",
    "description",
    "fa_icon",
    "properties",
    "required",
    "title",
    "type",
}

PARAM_SUPPORTED_KEYS = {
    "$comment",
    "$ref",
    "default",
    "description",
    "enum",
    "examples",
    "exists",
    "fa_icon",
    "format",
    "help_text",
    "hidden",
    "ignore",
    "items",
    "markdownDescription",
    "maxItems",
    "maxLength",
    "maximum",
    "mimetype",
    "minItems",
    "minLength",
    "minimum",
    "pattern",
    "properties",
    "required",
    "schema",
    "title",
    "type",
    "uniqueItems",
}

TOP_LEVEL_SUPPORTED_KEYS = {
    "$comment",
    "$defs",
    "$id",
    "$schema",
    "additionalProperties",
    "allOf",
    "definitions",
    "description",
    "git_sha",
    "git_url",
    "manifest",
    "name",
    "pipeline",
    "pipeline_name",
    "properties",
    "release",
    "repository",
    "required",
    "title",
    "type",
    "version",
}


@dataclass(frozen=True)
class NfCoreParameter:
    """A flattened top-level Nextflow parameter from an nf-core schema."""

    name: str
    schema: dict[str, Any]
    required: bool
    group_id: str
    group_title: str
    group_description: str
    group_advanced: bool = False
    position: int = 0


@dataclass(frozen=True)
class NfCoreParameterGroup:
    """A parameter group declared by a definition, ``allOf`` entry, or root properties."""

    group_id: str
    title: str
    description: str
    required: tuple[str, ...]
    fields: tuple[str, ...]
    advanced: bool = False
    extras: dict[str, Any] | None = None


@dataclass(frozen=True)
class NfCoreSchema:
    """Parsed representation of a local nf-core parameter schema."""

    raw: dict[str, Any]
    parameters: tuple[NfCoreParameter, ...]
    groups: tuple[NfCoreParameterGroup, ...]
    extras: dict[str, Any]

    def parameter_by_name(self, name: str) -> NfCoreParameter | None:
        for parameter in self.parameters:
            if parameter.name == name:
                return parameter
        return None


def load_nextflow_schema(path: str | Path) -> NfCoreSchema:
    """Load and parse a local ``nextflow_schema.json`` file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_nextflow_schema(payload)


def parse_nextflow_schema(payload: dict[str, Any]) -> NfCoreSchema:
    """Flatten an nf-core schema into deterministic groups and parameters.

    The parser handles the common nf-core structure of root ``allOf`` entries
    that reference grouped definitions, then falls back to unreferenced
    definitions and root properties. Unsupported JSON Schema constructs are
    retained in ``extras`` so later phases can interpret them without rereading
    the source file.
    """

    if not isinstance(payload, dict):
        raise TypeError("nextflow_schema.json must decode to a JSON object")

    raw = copy.deepcopy(payload)
    definitions = _definition_maps(raw)
    root_required = set(_string_list(raw.get("required")))
    referenced_definition_ids: set[str] = set()
    unresolved_refs: list[str] = []
    groups: list[NfCoreParameterGroup] = []
    parameters_by_name: dict[str, NfCoreParameter] = {}
    position = 0

    def add_group(group_id: str, group_schema: dict[str, Any]) -> None:
        nonlocal position
        properties = group_schema.get("properties") if isinstance(group_schema.get("properties"), dict) else {}
        if not properties:
            return
        resolved_properties: dict[str, dict[str, Any]] = {}
        for name, property_schema in properties.items():
            if not isinstance(property_schema, dict):
                continue
            resolved = _resolve_property_schema(raw, property_schema, unresolved_refs)
            if isinstance(resolved, dict):
                resolved_properties[str(name)] = resolved
        if not resolved_properties:
            return

        normalized_group_id = normalize_identifier(group_id) or "parameters"
        title = str(group_schema.get("title") or _humanize_identifier(normalized_group_id))
        description = str(group_schema.get("description") or "")
        group_required = tuple(_string_list(group_schema.get("required")))
        advanced = _is_advanced_group(normalized_group_id, title)
        fields: list[str] = []

        for name, property_schema in resolved_properties.items():
            required = (
                name in root_required
                or name in group_required
                or property_schema.get("required") is True
            )
            existing = parameters_by_name.get(name)
            if existing is not None:
                if required and not existing.required:
                    parameters_by_name[name] = replace(existing, required=True)
                fields.append(name)
                continue
            parameters_by_name[name] = NfCoreParameter(
                name=name,
                schema=property_schema,
                required=required,
                group_id=normalized_group_id,
                group_title=title,
                group_description=description,
                group_advanced=advanced,
                position=position,
            )
            fields.append(name)
            position += 1

        if fields:
            groups.append(
                NfCoreParameterGroup(
                    group_id=normalized_group_id,
                    title=title,
                    description=description,
                    required=group_required,
                    fields=tuple(fields),
                    advanced=advanced,
                    extras=_unsupported_keywords(group_schema, GROUP_SUPPORTED_KEYS),
                )
            )

    for index, entry in enumerate(raw.get("allOf") if isinstance(raw.get("allOf"), list) else []):
        if not isinstance(entry, dict):
            continue
        ref = entry.get("$ref")
        if isinstance(ref, str):
            resolved = _resolve_json_pointer(raw, ref)
            if not isinstance(resolved, dict):
                unresolved_refs.append(ref)
                continue
            definition_id = _definition_id_from_ref(ref)
            if definition_id:
                referenced_definition_ids.add(definition_id)
            add_group(definition_id or f"all_of_{index}", resolved)
            continue
        add_group(str(entry.get("title") or f"all_of_{index}"), entry)

    for definition_id, definition_schema in definitions.items():
        if definition_id in referenced_definition_ids:
            continue
        if isinstance(definition_schema, dict):
            add_group(definition_id, definition_schema)

    root_properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    ungrouped_properties = {
        str(name): value
        for name, value in root_properties.items()
        if str(name) not in parameters_by_name and isinstance(value, dict)
    }
    if ungrouped_properties:
        add_group(
            "pipeline_options",
            {
                "title": "Pipeline options",
                "description": "Top-level pipeline parameters.",
                "type": "object",
                "required": sorted(root_required & set(ungrouped_properties)),
                "properties": ungrouped_properties,
            },
        )

    extras = {
        "unsupported_top_level": _unsupported_keywords(raw, TOP_LEVEL_SUPPORTED_KEYS),
        "unresolved_refs": sorted(set(unresolved_refs)),
    }
    return NfCoreSchema(
        raw=raw,
        parameters=tuple(sorted(parameters_by_name.values(), key=lambda item: item.position)),
        groups=tuple(groups),
        extras=extras,
    )


def normalize_identifier(value: Any) -> str:
    """Normalize a source identifier to Workbench-friendly snake case."""

    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return re.sub(r"_+", "_", text)


def _definition_maps(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("definitions", "$defs"):
        value = raw.get(key)
        if isinstance(value, dict):
            out.update({str(name): schema for name, schema in value.items()})
    return out


def _definition_id_from_ref(ref: str) -> str:
    if not ref.startswith("#/"):
        return ""
    parts = [_json_pointer_unescape(part) for part in ref[2:].split("/")]
    if len(parts) >= 2 and parts[0] in {"definitions", "$defs"}:
        return str(parts[1])
    return parts[-1] if parts else ""


def _humanize_identifier(value: str) -> str:
    return str(value or "parameters").replace("_", " ").strip().capitalize()


def _is_advanced_group(group_id: str, title: str) -> bool:
    text = f"{group_id} {title}".lower()
    return any(
        token in text
        for token in (
            "advanced",
            "config",
            "execution",
            "generic",
            "institutional",
            "max_job",
            "process",
            "resource",
        )
    )


def _json_pointer_unescape(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def _resolve_json_pointer(root: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    current: Any = root
    for part in ref[2:].split("/"):
        key = _json_pointer_unescape(part)
        if isinstance(current, dict):
            if key not in current:
                return None
            current = current[key]
            continue
        if isinstance(current, list) and key.isdigit():
            index = int(key)
            if index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def _resolve_property_schema(
    root: dict[str, Any],
    property_schema: dict[str, Any],
    unresolved_refs: list[str],
) -> dict[str, Any]:
    ref = property_schema.get("$ref")
    if not isinstance(ref, str):
        return copy.deepcopy(property_schema)
    resolved = _resolve_json_pointer(root, ref)
    if not isinstance(resolved, dict):
        unresolved_refs.append(ref)
        return copy.deepcopy(property_schema)
    merged = copy.deepcopy(resolved)
    for key, value in property_schema.items():
        if key != "$ref":
            merged[key] = copy.deepcopy(value)
    merged["$ref"] = ref
    return merged


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _unsupported_keywords(schema: dict[str, Any], supported: set[str]) -> dict[str, Any]:
    unsupported = {
        str(key): copy.deepcopy(value)
        for key, value in schema.items()
        if str(key) not in supported
    }
    return dict(sorted(unsupported.items(), key=lambda item: item[0]))
