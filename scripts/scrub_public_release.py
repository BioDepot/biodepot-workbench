#!/usr/bin/env python3
"""Fail closed when a public release candidate contains private material."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
SKIP_PARTS = {".git", ".pytest_cache", "__pycache__", ".venv", "venv"}
FORBIDDEN_PATH_PARTS = {"deploy", "hosts", "handoffs", "secrets"}
FORBIDDEN_NAME_MARKERS = ("allowlist", "allowed-email", "private-key")

FORBIDDEN_CONTENT = {
    "private absolute path": re.compile(r"/(?:mnt|home)/", re.IGNORECASE),
    "confidential compute integration": re.compile(
        r"(?:bridges-?2|psc[.]edu|zshard|patrick|temporal[-_ ]?slurm)", re.IGNORECASE
    ),
    "internal host or institution": re.compile(
        r"(?:pikachu|bioserver|tacoma[.]uw|uw[.]edu)", re.IGNORECASE
    ),
    "identity-provider configuration": re.compile(
        r"(?:oauth|oidc|allowed[-_ ]?emails?|allowlist)", re.IGNORECASE
    ),
    "private data marker": re.compile(
        r"(?:ucsf|jax[-_ ]?multiome|catatac|GSE[0-9]{5,})", re.IGNORECASE
    ),
    "private key": re.compile(r"BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY"),
    "cloud access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub credential": re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+)"),
    "API credential": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
}


def candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            files.append(path)
        elif path.is_file():
            files.append(path)
    return sorted(files)


def main() -> int:
    findings: list[str] = []
    for path in candidate_files():
        relative = path.relative_to(ROOT)
        lowered_parts = {part.lower() for part in relative.parts}
        if lowered_parts & FORBIDDEN_PATH_PARTS:
            findings.append(f"forbidden path: {relative}")
        if any(marker in relative.name.lower() for marker in FORBIDDEN_NAME_MARKERS):
            findings.append(f"forbidden filename: {relative}")
        if path.is_symlink():
            findings.append(f"symbolic link: {relative}")
            continue
        if path.resolve() == SELF:
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(f"unreadable file: {relative}: {exc}")
            continue
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for label, pattern in FORBIDDEN_CONTENT.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{label}: {relative}:{line}")

    if findings:
        print("Public-release scrub failed:", file=sys.stderr)
        for finding in sorted(set(findings)):
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"Public-release scrub passed ({len(candidate_files())} files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
