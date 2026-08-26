# Release validation

Release: `v0.1.0`

The measurements below must be produced from this public repository after the
split. They intentionally do not reuse counts from the development repository.

## Commands

```bash
python3 scripts/scrub_public_release.py
python3 -m pytest -q
python3 scripts/count_mcp_tools.py
```

## Candidate measurements

| Measurement | Result |
| --- | --- |
| Public-release scrub | Passed; 169 files checked |
| Collected tests | 172 |
| Test result | 166 passed, 6 skipped, 0 failed |
| Registered MCP tools | 34 |

The skipped tests require optional browser runtimes, external workflow tools,
network access, or an external graph database. They remain collected and state
their enabling condition. No skip was added to hide a public-tree failure.

The measurements were recorded from the public release tree on 2026-08-26.
The release scrub was rerun after review and immediately before creating the
release tag.
