# BioDepot Workbench

BioDepot Workbench is an open-source, browser-based human-agent workbench for
building reproducible bioinformatics analyses. It exposes the same platform
operations through an HTTP API, a browser interface, and a Model Context
Protocol (MCP) server so people and software agents can discover tools, search
workflow graphs, compose plans, review parameters, and materialize executable
bundles through one contract.

This repository contains the public platform kernel:

- the Starlette HTTP API and self-contained browser workbench;
- the FastMCP server and policy metadata for every MCP tool;
- durable conversations, workflow runs, review records, and SQLite/PostgreSQL
  persistence boundaries;
- execution-location contracts for server, caller-managed, remote, and
  scheduler-managed execution;
- module/recipe registries, graph projection, typed graph search, and planning;
- local and remote nf-core metadata harvest, source decomposition, schema
  mapping, bundle rendering, and validation records;
- tests and synthetic fixtures for the public platform behavior.

The Python import namespaces (`morphic_agent` and `morphic_front`) are retained
for compatibility with existing clients. No project data, deployment inventory,
host configuration, credentials, or private execution connector is included.

## Architecture

```text
browser UI ─┐
HTTP API  ──┼─> WorkbenchService ─> planner / graph index / registry
MCP server ─┘          │
                       ├─> durable run + conversation store
                       ├─> nf-core harvest and bundle contracts
                       └─> reviewed execution-location adapters
```

The service layer owns deterministic platform behavior. HTTP and MCP are thin
adapters over that layer, which lets tests compare the contracts exposed to
browser users and agents.

## Install

Python 3.10 or newer is required.

```bash
git clone https://github.com/BioDepot/biodepot-workbench.git
cd biodepot-workbench
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[test]"
```

The optional `backend` extra adds scientific Python packages used by generated
analysis bundles:

```bash
python3 -m pip install -e ".[test,backend]"
```

## Run the browser/API service

```bash
python3 -m uvicorn morphic_agent.api.app:app --host 127.0.0.1 --port 8890
```

Open <http://127.0.0.1:8890/>. By default, state uses a temporary SQLite
database. Set `MORPHIC_AGENT_DATABASE_URL` or `MORPHIC_AGENT_DB` to use an
explicit database.

The application does not ship an authentication-provider or host deployment
configuration. See [the security model](docs/SECURITY_MODEL.md) before placing
the service behind a reverse proxy or enabling execution.

## Run the MCP server

```bash
python3 -m morphic_agent.mcp.server --transport stdio
```

MCP clients can inspect tool annotations to distinguish read-only discovery,
artifact creation, user elicitation, and operations that require explicit human
review. Those annotations improve agent behavior but are not an authorization
boundary; server-side checks remain authoritative.

## nf-core harvest and decomposition

Harvest a local pipeline checkout without executing it:

```bash
python3 scripts/harvest_nfcore_pipeline.py /path/to/pipeline --dry-run
python3 scripts/decompose_nfcore_pipeline.py /path/to/pipeline --strict --summary
```

Remote harvest is metadata-only, bounded by response-size limits, and must be
explicitly requested by the caller.

## Test and audit

```bash
python3 scripts/scrub_public_release.py
python3 -m pytest -q
python3 scripts/count_mcp_tools.py
```

The release-candidate measurements and commands are recorded in
[release validation](docs/RELEASE_VALIDATION.md). Browser tests require the
Playwright Chromium runtime (`python3 -m playwright install chromium`); they
skip with a recorded reason when it is unavailable.

## Design documents

- [Security model](docs/SECURITY_MODEL.md)
- [Conversation design](docs/CONVERSATION_DESIGN.md)
- [Platform positioning](docs/PLATFORM_POSITIONING.md)
- [nf-core source decomposition](docs/NFCORE_DECOMPOSITION.md)
- [Release validation](docs/RELEASE_VALIDATION.md)

## Release and scope

The first public release is `v0.1.0`. [CHANGELOG.md](CHANGELOG.md) describes
its contents.

Deployment files, institutional configuration, access lists, credentials,
private datasets, internal handoffs, and confidential compute integrations are
deliberately out of scope.

## License

[MIT](LICENSE) © 2026 BioDepot.
