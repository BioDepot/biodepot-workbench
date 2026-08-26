"""Deterministic, non-executing decomposition of local nf-core DSL2 sources."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from morphic_agent.harvest.nfcore_mapper import NfCoreHarvestResult

NFCORE_DECOMPOSITION_SCHEMA = "morphic.nfcore_decomposition/v0"
NFCORE_DECOMPOSER_VERSION = "morphic.nfcore_source_index/v0"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_SKIPPED_SOURCE_PARTS = {".git", ".nextflow", "bwb_output", "results", "work"}
_INCLUDE_RE = re.compile(
    r"\binclude\s*\{(?P<symbols>[^{}]*)\}\s*from\s*(?P<quote>['\"])(?P<source>.*?)(?P=quote)",
    re.DOTALL,
)
_DECLARATION_RE = re.compile(r"\b(?P<kind>workflow|process)\s*(?P<name>[A-Za-z_]\w*)?\s*\{")
_FUNCTION_RE = re.compile(r"(?m)^\s*def\s+(?P<name>[A-Za-z_]\w*)\s*\([^)]*\)\s*\{")
_INCLUDE_SYMBOL_RE = re.compile(r"(?P<symbol>[A-Za-z_]\w*)(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?")
_CALL_RE = re.compile(r"(?<![\w.])(?P<name>[A-Za-z_]\w*)\s*\(")


def decompose_nfcore_pipeline(
    pipeline_path: str | Path,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Index declarations and resolvable relationships in a local nf-core checkout.

    The result is a source-level editing index, not a compiled Nextflow DAG. It
    does not execute Nextflow or evaluate params, channels, conditionals, or
    dynamic Groovy expressions.
    """

    root = Path(pipeline_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"nf-core pipeline directory not found: {root}")
    entrypoint = root / "main.nf"
    if not entrypoint.is_file():
        raise FileNotFoundError(f"nf-core entrypoint not found: {entrypoint}")

    modules_registry, registry_warnings = _load_modules_registry(root / "modules.json")
    warnings = list(registry_warnings)
    source_paths = sorted(
        (
            path
            for path in root.rglob("*.nf")
            if path.is_file() and not (_SKIPPED_SOURCE_PARTS & set(path.relative_to(root).parts))
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )

    files: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    analyses: dict[str, dict[str, Any]] = {}
    declaration_nodes: dict[tuple[str, str], str] = {}

    for path in source_paths:
        relative_path = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        if len(raw) > _MAX_SOURCE_BYTES:
            warnings.append(
                {
                    "kind": "source_too_large",
                    "source_path": relative_path,
                    "limit_bytes": _MAX_SOURCE_BYTES,
                }
            )
            continue
        text = raw.decode("utf-8")
        masked = _mask_comments_and_strings(text)
        comments_visible = _mask_comments(text)
        file_id = _stable_id("source", relative_path)
        source_kind, origin = _source_classification(relative_path)
        declarations = _parse_declarations(relative_path, text, masked, source_kind)
        includes = _parse_includes(comments_visible)
        metadata, metadata_warning = _load_component_metadata(path.parent / "meta.yml")
        if metadata_warning:
            warnings.append({**metadata_warning, "source_path": relative_path})

        file_record: dict[str, Any] = {
            "id": file_id,
            "path": relative_path,
            "kind": source_kind,
            "origin": origin,
            "sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}",
            "line_count": text.count("\n") + (0 if not text or text.endswith("\n") else 1),
            "declarations": [_public_declaration(item) for item in declarations],
            "includes": includes,
        }
        if metadata is not None:
            file_record["metadata"] = metadata
        if relative_path in modules_registry:
            file_record["modules_registry"] = modules_registry[relative_path]
        files.append(file_record)
        analyses[relative_path] = {
            "path": path,
            "masked": masked,
            "file": file_record,
            "declarations": declarations,
        }
        nodes.append(
            {
                "id": file_id,
                "kind": source_kind,
                "label": relative_path,
                "source_path": relative_path,
                "origin": origin,
                "editable": True,
                "execution_boundary": False,
            }
        )
        for declaration in declarations:
            declaration_nodes[(relative_path, declaration["name"])] = declaration["id"]
            nodes.append(
                {
                    "id": declaration["id"],
                    "kind": declaration["kind"],
                    "label": declaration["name"],
                    "source_path": relative_path,
                    "source_line": declaration["line"],
                    "origin": origin,
                    "editable": True,
                    "execution_boundary": False,
                }
            )
            edges.append(
                {
                    "source": file_id,
                    "target": declaration["id"],
                    "edge_type": "declares",
                    "source_line": declaration["line"],
                    "confidence": "source_declared",
                }
            )

    unresolved: list[dict[str, Any]] = []
    external_nodes: dict[tuple[str, str], str] = {}
    aliases_by_file: dict[str, dict[str, str]] = {}
    file_dependencies: dict[str, set[str]] = {path: set() for path in analyses}

    for relative_path, analysis in analyses.items():
        aliases: dict[str, str] = {}
        for include in analysis["file"]["includes"]:
            include_source = include["source"]
            resolved_path = _resolve_include(root, analysis["path"], include_source)
            for symbol in include["symbols"]:
                alias = symbol["alias"]
                if include_source.startswith("plugin/"):
                    key = (include_source, symbol["symbol"])
                    target_id = external_nodes.setdefault(
                        key,
                        _stable_id("external", f"{include_source}:{symbol['symbol']}"),
                    )
                    symbol["resolution"] = "external_plugin"
                    symbol["target_id"] = target_id
                    aliases[alias] = target_id
                    continue
                if resolved_path is None:
                    problem = {
                        "kind": "include_source_not_found",
                        "source_path": relative_path,
                        "source_line": include["line"],
                        "include_source": include_source,
                        "symbol": symbol["symbol"],
                        "alias": alias,
                    }
                    unresolved.append(problem)
                    symbol["resolution"] = "unresolved"
                    continue
                target_path = resolved_path.relative_to(root).as_posix()
                file_dependencies[relative_path].add(target_path)
                target_id = declaration_nodes.get((target_path, symbol["symbol"]))
                if target_id is None:
                    problem = {
                        "kind": "include_symbol_not_found",
                        "source_path": relative_path,
                        "source_line": include["line"],
                        "include_source": include_source,
                        "resolved_path": target_path,
                        "symbol": symbol["symbol"],
                        "alias": alias,
                    }
                    unresolved.append(problem)
                    symbol["resolution"] = "unresolved"
                    continue
                symbol["resolution"] = "declaration"
                symbol["target_path"] = target_path
                symbol["target_id"] = target_id
                aliases[alias] = target_id
                edges.append(
                    {
                        "source": analysis["file"]["id"],
                        "target": target_id,
                        "edge_type": "includes",
                        "source_line": include["line"],
                        "symbol": symbol["symbol"],
                        "alias": alias,
                        "include_source": include_source,
                        "confidence": "source_declared",
                    }
                )
        aliases_by_file[relative_path] = aliases

    for (include_source, symbol), node_id in sorted(external_nodes.items()):
        nodes.append(
            {
                "id": node_id,
                "kind": "plugin_symbol",
                "label": symbol,
                "include_source": include_source,
                "origin": "nextflow_plugin",
                "editable": False,
                "execution_boundary": False,
            }
        )
    _add_plugin_include_edges(files, edges)

    for relative_path, analysis in analyses.items():
        local_symbols = {
            declaration["name"]: declaration["id"] for declaration in analysis["declarations"]
        }
        resolvable = {**local_symbols, **aliases_by_file.get(relative_path, {})}
        for declaration in analysis["declarations"]:
            calls = _parse_calls(analysis["masked"], declaration, resolvable)
            public_declaration = next(
                item for item in analysis["file"]["declarations"] if item["id"] == declaration["id"]
            )
            public_declaration["calls"] = calls
            for call in calls:
                edges.append(
                    {
                        "source": declaration["id"],
                        "target": call["target_id"],
                        "edge_type": "invokes",
                        "source_line": call["line"],
                        "symbol": call["symbol"],
                        "confidence": "source_resolved",
                    }
                )

    reachable_files = _reachable_files("main.nf", file_dependencies)
    reachable_source_ids = {item["id"] for item in files if item["path"] in reachable_files}
    reachable_plugin_ids = {
        edge["target"]
        for edge in edges
        if edge.get("edge_type") == "includes" and edge["source"] in reachable_source_ids
    }
    reachable_nodes = {
        node["id"]
        for node in nodes
        if node.get("source_path") in reachable_files
        or (node.get("kind") == "plugin_symbol" and node["id"] in reachable_plugin_ids)
    }
    for node in nodes:
        node["reachable_from_entrypoint"] = node["id"] in reachable_nodes
    for file_record in files:
        file_record["reachable_from_entrypoint"] = file_record["path"] in reachable_files

    nodes.sort(key=lambda item: (str(item.get("source_path") or "~"), int(item.get("source_line") or 0), item["id"]))
    edges.sort(
        key=lambda item: (
            item["source"],
            int(item.get("source_line") or 0),
            item["edge_type"],
            item["target"],
            str(item.get("alias") or ""),
        )
    )
    files.sort(key=lambda item: item["path"])
    unresolved.sort(key=lambda item: (item["source_path"], int(item.get("source_line") or 0), item["symbol"]))

    if strict and unresolved:
        first = unresolved[0]
        raise ValueError(
            f"nf-core decomposition has {len(unresolved)} unresolved includes; "
            f"first: {first['source_path']}:{first['source_line']} {first['symbol']}"
        )

    source_hash = _source_index_hash(files)
    summary = _summary(files, nodes, edges, unresolved, reachable_files)
    status = "decomposed" if not unresolved else "decomposed_with_unresolved_includes"
    return {
        "schema": NFCORE_DECOMPOSITION_SCHEMA,
        "status": status,
        "decomposer": {
            "version": NFCORE_DECOMPOSER_VERSION,
            "method": "static_nextflow_dsl2_source_index",
            "executes_workflow": False,
            "guarantees": [
                "source declarations, include aliases, and source locations are indexed deterministically",
                "module and subworkflow meta.yml are loaded with a safe YAML parser",
                "resolved invocation edges only target symbols declared or included in the same source file",
            ],
            "limitations": [
                "channel dataflow and runtime DAG topology are not inferred",
                "Groovy metaprogramming and dynamic include paths are not evaluated",
                "conditional branches are recorded as source calls, not predicted runtime executions",
            ],
        },
        "pipeline_path": str(root),
        "entrypoint": "main.nf",
        "execution_boundary": {
            "kind": "nfcore_pipeline",
            "source_path": "main.nf",
            "decomposed_components_independently_runnable": False,
        },
        "source_manifest": {
            "source_index_hash": source_hash,
            "source_file_count": len(files),
            **_git_manifest(root),
        },
        "summary": summary,
        "files": files,
        "nodes": nodes,
        "edges": edges,
        "unresolved": unresolved,
        "warnings": warnings,
    }


def attach_nfcore_decomposition(
    harvest: NfCoreHarvestResult,
    decomposition: dict[str, Any],
) -> NfCoreHarvestResult:
    """Attach a source decomposition while preserving the whole-pipeline runtime."""

    graph = copy.deepcopy(harvest.workflow_graph)
    module = copy.deepcopy(harvest.module_contract)
    source_manifest = copy.deepcopy(harvest.source_manifest)
    root_node = copy.deepcopy(graph["nodes"][0])
    root_node["execution_boundary"] = True
    root_node["editable"] = False
    root_node["decomposition_role"] = "runnable_pipeline_wrapper"
    graph["nodes"] = [root_node, *copy.deepcopy(graph.get("nodes", [])[1:])]
    graph["edges"] = copy.deepcopy(graph.get("edges") or [])
    graph["decomposition"] = copy.deepcopy(decomposition)
    graph["lifecycle_state"] = "source_decomposed"
    source_manifest["decomposition_hash"] = decomposition["source_manifest"]["source_index_hash"]
    source_manifest["source_revision"] = decomposition["source_manifest"].get("git_commit")
    local_source_runtime = {
        "source_kind": "local_checkout",
        "local_pipeline_path": decomposition["pipeline_path"],
        "local_source_index_hash": decomposition["source_manifest"]["source_index_hash"],
        "local_source_revision": decomposition["source_manifest"].get("git_commit"),
        "workflow_path_override_env": "NFCORE_WORKFLOW_PATH",
        "default_launch_target": "upstream_pipeline_reference",
    }
    graph["runtime"] = {**(graph.get("runtime") or {}), **local_source_runtime}
    module["runtime"] = {**(module.get("runtime") or {}), **local_source_runtime}
    graph["source_manifest"] = copy.deepcopy(source_manifest)
    module["source_manifest"] = copy.deepcopy(source_manifest)
    module.setdefault("extras", {})["nfcore_decomposition"] = {
        "schema": decomposition.get("schema"),
        "status": decomposition.get("status"),
        "summary": copy.deepcopy(decomposition.get("summary") or {}),
        "source_index_hash": decomposition["source_manifest"]["source_index_hash"],
        "execution_boundary": copy.deepcopy(decomposition.get("execution_boundary") or {}),
    }
    return NfCoreHarvestResult(
        module_contract=module,
        workflow_graph=graph,
        params_schema=harvest.params_schema,
        path_binding_candidates=harvest.path_binding_candidates,
        source_manifest=source_manifest,
        schema=harvest.schema,
    )


def _parse_declarations(
    relative_path: str,
    text: str,
    masked: str,
    source_kind: str,
) -> list[dict[str, Any]]:
    matches: list[tuple[int, re.Match[str], str, str]] = []
    for match in _DECLARATION_RE.finditer(masked):
        kind = match.group("kind")
        name = match.group("name") or "entrypoint"
        if kind == "workflow" and source_kind == "subworkflow_source":
            kind = "subworkflow"
        matches.append((match.start(), match, kind, name))
    for match in _FUNCTION_RE.finditer(masked):
        matches.append((match.start(), match, "function", match.group("name")))
    matches.sort(key=lambda item: item[0])
    declarations: list[dict[str, Any]] = []
    duplicate_counts: dict[tuple[str, str], int] = {}
    for _, match, kind, name in matches:
        open_brace = masked.find("{", match.start(), match.end())
        close_brace = _matching_brace(masked, open_brace)
        if close_brace is None:
            close_brace = len(masked) - 1
        key = (kind, name)
        duplicate_counts[key] = duplicate_counts.get(key, 0) + 1
        identity = f"{relative_path}:{kind}:{name}:{duplicate_counts[key]}"
        declarations.append(
            {
                "id": _stable_id("declaration", identity),
                "kind": kind,
                "name": name,
                "line": _line_number(text, match.start()),
                "end_line": _line_number(text, close_brace),
                "_body_start": open_brace + 1,
                "_body_end": close_brace,
            }
        )
    return declarations


def _public_declaration(declaration: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in declaration.items() if not key.startswith("_")}


def _parse_includes(text: str) -> list[dict[str, Any]]:
    includes: list[dict[str, Any]] = []
    for match in _INCLUDE_RE.finditer(text):
        symbols = []
        for symbol_match in _INCLUDE_SYMBOL_RE.finditer(match.group("symbols")):
            symbol = symbol_match.group("symbol")
            alias = symbol_match.group("alias") or symbol
            symbols.append({"symbol": symbol, "alias": alias})
        if symbols:
            includes.append(
                {
                    "source": match.group("source"),
                    "line": _line_number(text, match.start()),
                    "symbols": symbols,
                }
            )
    return includes


def _parse_calls(masked: str, declaration: dict[str, Any], resolvable: dict[str, str]) -> list[dict[str, Any]]:
    body_start = int(declaration["_body_start"])
    body = masked[body_start : int(declaration["_body_end"])]
    calls: list[dict[str, Any]] = []
    for match in _CALL_RE.finditer(body):
        symbol = match.group("name")
        target_id = resolvable.get(symbol)
        if target_id is None or target_id == declaration["id"]:
            continue
        calls.append(
            {
                "symbol": symbol,
                "target_id": target_id,
                "line": _line_number(masked, body_start + match.start()),
            }
        )
    return calls


def _resolve_include(root: Path, source_path: Path, include_source: str) -> Path | None:
    if include_source.startswith("plugin/"):
        return None
    raw_candidate = source_path.parent / include_source
    candidates = [raw_candidate]
    if raw_candidate.suffix != ".nf":
        candidates.extend([Path(f"{raw_candidate}.nf"), raw_candidate / "main.nf"])
    elif raw_candidate.is_dir():
        candidates.append(raw_candidate / "main.nf")
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
        if resolved.is_dir() and (resolved / "main.nf").is_file():
            return resolved / "main.nf"
    return None


def _add_plugin_include_edges(files: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    existing = {
        (edge["source"], edge.get("source_line"), edge.get("alias"))
        for edge in edges
        if edge.get("edge_type") == "includes"
    }
    for file_record in files:
        for include in file_record["includes"]:
            for symbol in include["symbols"]:
                if symbol.get("resolution") != "external_plugin":
                    continue
                key = (file_record["id"], include["line"], symbol["alias"])
                if key in existing:
                    continue
                edges.append(
                    {
                        "source": file_record["id"],
                        "target": symbol["target_id"],
                        "edge_type": "includes",
                        "source_line": include["line"],
                        "symbol": symbol["symbol"],
                        "alias": symbol["alias"],
                        "include_source": include["source"],
                        "confidence": "source_declared",
                    }
                )


def _source_classification(relative_path: str) -> tuple[str, str]:
    parts = Path(relative_path).parts
    if relative_path == "main.nf":
        return "pipeline_source", "pipeline"
    if parts and parts[0] == "workflows":
        return "workflow_source", "pipeline"
    if parts and parts[0] == "subworkflows":
        return "subworkflow_source", parts[1] if len(parts) > 1 else "pipeline"
    if parts and parts[0] == "modules":
        return "module_source", parts[1] if len(parts) > 1 else "pipeline"
    return "nextflow_source", "pipeline"


def _load_component_metadata(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not path.is_file():
        return None, None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return None, {"kind": "invalid_component_metadata", "metadata_path": path.name, "error": str(exc)}
    if not isinstance(payload, dict):
        return None, {"kind": "invalid_component_metadata", "metadata_path": path.name, "error": "expected a mapping"}
    return json.loads(json.dumps(payload, default=str)), None


def _load_modules_registry(path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if not path.is_file():
        return {}, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, [{"kind": "invalid_modules_json", "path": path.name, "error": str(exc)}]
    registry: dict[str, dict[str, Any]] = {}
    repos = payload.get("repos") if isinstance(payload, dict) else None
    if not isinstance(repos, dict):
        return {}, [{"kind": "unsupported_modules_json", "path": path.name, "error": "repos mapping is absent"}]
    for repository, repository_payload in sorted(repos.items()):
        if not isinstance(repository_payload, dict):
            continue
        for component_type in ("modules", "subworkflows"):
            namespaces = repository_payload.get(component_type)
            if not isinstance(namespaces, dict):
                continue
            for namespace, components in sorted(namespaces.items()):
                if not isinstance(components, dict):
                    continue
                for component_name, component in sorted(components.items()):
                    source_path = f"{component_type}/{namespace}/{component_name}/main.nf"
                    registry[source_path] = {
                        "repository": repository,
                        "namespace": namespace,
                        "component": component_name,
                        **(copy.deepcopy(component) if isinstance(component, dict) else {}),
                    }
    return registry, []


def _mask_comments(text: str) -> str:
    return _mask_lexical(text, mask_strings=False)


def _mask_comments_and_strings(text: str) -> str:
    return _mask_lexical(text, mask_strings=True)


def _mask_lexical(text: str, *, mask_strings: bool) -> str:
    chars = list(text)
    index = 0
    state = "code"
    quote = ""
    while index < len(chars):
        current = chars[index]
        following = chars[index + 1] if index + 1 < len(chars) else ""
        if state == "code":
            if current == "/" and following == "/":
                state = "line_comment"
                chars[index] = chars[index + 1] = " "
                index += 2
                continue
            if current == "/" and following == "*":
                state = "block_comment"
                chars[index] = chars[index + 1] = " "
                index += 2
                continue
            if current in {"'", '"'}:
                quote = current
                triple = text[index : index + 3] == current * 3
                state = "triple_string" if triple else "string"
                if mask_strings:
                    count = 3 if triple else 1
                    for offset in range(count):
                        chars[index + offset] = " "
                    index += count
                    continue
        elif state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                chars[index] = " "
        elif state == "block_comment":
            if current == "*" and following == "/":
                chars[index] = chars[index + 1] = " "
                state = "code"
                index += 2
                continue
            if current != "\n":
                chars[index] = " "
        elif state == "string":
            if mask_strings and current != "\n":
                chars[index] = " "
            if current == "\\":
                if mask_strings and index + 1 < len(chars) and chars[index + 1] != "\n":
                    chars[index + 1] = " "
                index += 2
                continue
            if current == quote:
                state = "code"
        elif state == "triple_string":
            if text[index : index + 3] == quote * 3:
                if mask_strings:
                    chars[index : index + 3] = [" ", " ", " "]
                state = "code"
                index += 3
                continue
            if mask_strings and current != "\n":
                chars[index] = " "
        index += 1
    return "".join(chars)


def _matching_brace(masked: str, open_brace: int) -> int | None:
    if open_brace < 0:
        return None
    depth = 0
    for index in range(open_brace, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _reachable_files(entrypoint: str, dependencies: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    pending = [entrypoint]
    while pending:
        current = pending.pop()
        if current in reachable or current not in dependencies:
            continue
        reachable.add(current)
        pending.extend(sorted(dependencies[current] - reachable, reverse=True))
    return reachable


def _source_index_hash(files: list[dict[str, Any]]) -> str:
    payload = [{"path": item["path"], "sha256": item["sha256"]} for item in files]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _summary(
    files: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    reachable_files: set[str],
) -> dict[str, Any]:
    node_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    for node in nodes:
        node_counts[node["kind"]] = node_counts.get(node["kind"], 0) + 1
    for edge in edges:
        edge_counts[edge["edge_type"]] = edge_counts.get(edge["edge_type"], 0) + 1
    return {
        "source_file_count": len(files),
        "reachable_source_file_count": len(reachable_files),
        "unreachable_source_file_count": len(files) - len(reachable_files),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_counts": dict(sorted(node_counts.items())),
        "edge_counts": dict(sorted(edge_counts.items())),
        "include_count": sum(len(item["symbols"]) for file in files for item in file["includes"]),
        "unresolved_include_count": len(unresolved),
        "metadata_file_count": sum(1 for item in files if "metadata" in item),
    }


def _git_manifest(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        return {}
    commands = {
        "git_commit": ["git", "rev-parse", "HEAD"],
        "git_ref": ["git", "describe", "--tags", "--always"],
        "git_url": ["git", "remote", "get-url", "origin"],
    }
    manifest: dict[str, Any] = {}
    for key, command in commands.items():
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=5, check=False)
        if result.returncode == 0 and result.stdout.strip():
            manifest[key] = result.stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if dirty.returncode == 0:
        manifest["tracked_worktree_dirty"] = bool(dirty.stdout.strip())
    return manifest


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"nfcore_{prefix}_{digest}"
