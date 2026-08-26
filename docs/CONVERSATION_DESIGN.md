# Conversation design

Workbench conversations are durable, user-owned records around a planner
thread. A user can create, resume, search, rename, archive, restore, and fork a
conversation independently of a browser session. Workflow runs created from a
conversation are linked to it without merging the conversation and execution
lifecycle.

## Identifiers

| Identifier | Lifetime | Responsibility |
| --- | --- | --- |
| `session_id` | One browser or MCP client session | Scope transient client state and generated output |
| `conversation_id` | Until retained data is removed | Own the discussion, turns, planner state, and linked runs |
| `thread_id` | Planner compatibility key | Address persisted turns and planner checkpoints |
| `run_id` | One workflow attempt | Track review, rendering, preflight, execution, and artifacts |

`conversation_id` and `thread_id` currently share a value, but clients should
not assume they have identical semantics forever.

## Ownership

The HTTP adapter passes the authenticated storage identity into the service.
The MCP adapter requires an explicit `user` argument. The repository layer
normalizes the identity and enforces it for get, update, list, fork, and run-link
operations. `anonymous` is suitable only for a single-user or otherwise trusted
local transport.

## HTTP surface

```text
POST  /api/conversations
GET   /api/conversations?status=active&q=bulk&limit=50
GET   /api/conversations/{conversation_id}
PATCH /api/conversations/{conversation_id}
POST  /api/conversations/{conversation_id}/fork
POST  /api/chat
```

Chat accepts `conversation_id` (or the compatibility key `thread_id`). With no
identifier, it creates a conversation. An archived conversation rejects new
turns until restored or forked.

## MCP surface

```text
workbench_create_conversation
workbench_list_conversations
workbench_get_conversation
workbench_update_conversation
workbench_fork_conversation
```

The browser rail exposes the same lifecycle. Opening a conversation restores
turns and linked-run context. Forking can copy turns and planner state while
recording the parent relationship.

## Persistence and migration

Migration `20260719_0004_conversations` creates the conversation and run-link
tables. Existing planner threads are retained and represented as anonymous
conversations so the migration does not discard their history.

## Tests

```bash
python3 -m pytest -q tests/test_conversation_management.py
python3 -m pytest -q tests/test_conversation_management_playwright.py
```

The contract tests cover ownership isolation, archive/restore, forking, durable
resume, run linkage, MCP parity, and the browser management surface.
