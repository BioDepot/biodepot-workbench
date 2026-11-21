"""Guard against imports that only resolve through another checkout."""

from __future__ import annotations

import ast
import socket
import stat
import sys
from pathlib import Path

import pytest

import morphic_front
from morphic_front import sshtunnel
from morphic_front.sshtunnel import SshTarget, SshTunnel

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("morphic_front", "morphic_agent")


def _module_exists(parts: list[str]) -> bool:
    path = ROOT.joinpath(*parts)
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _imported_modules(path: Path) -> list[tuple[int, list[str]]]:
    relative = path.relative_to(ROOT).with_suffix("")
    package = list(relative.parts[:-1])
    found: list[tuple[int, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name.split(".")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                found.append((node.lineno, base + (node.module.split(".") if node.module else [])))
            elif node.module:
                found.append((node.lineno, node.module.split(".")))
    return [(line, parts) for line, parts in found if parts and parts[0] in PACKAGES]


def test_every_internal_import_resolves_inside_this_repository():
    missing = [
        f"{path.relative_to(ROOT)}:{line}: {'.'.join(parts)}"
        for package in PACKAGES
        for path in sorted((ROOT / package).rglob("*.py"))
        for line, parts in _imported_modules(path)
        if not _module_exists(parts)
    ]
    assert missing == []


def test_sshtunnel_is_loaded_from_this_package():
    assert Path(sshtunnel.__file__).parent == Path(morphic_front.__file__).parent


@pytest.mark.parametrize("field_name", ["host", "user"])
@pytest.mark.parametrize("value", ["-oProxyCommand=touch", "two words", ""])
def test_ssh_target_rejects_values_ssh_could_misparse(field_name, value):
    kwargs = {"host": "example.org", field_name: value}
    with pytest.raises(ValueError):
        SshTarget(**kwargs)


def _install_fake_ssh(tmp_path: Path, monkeypatch, body: str) -> None:
    script = tmp_path / "ssh"
    script.write_text(f"#!{sys.executable}\nimport socket, sys, time\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path(sys.executable).parent}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_tunnel_reports_ssh_error_when_it_exits_early(tmp_path, monkeypatch):
    _install_fake_ssh(tmp_path, monkeypatch, "sys.stderr.write('permission denied')\nsys.exit(255)")
    tunnel = SshTunnel(SshTarget(host="example.org"), remote_port=9, local_port=_free_port())
    with pytest.raises(RuntimeError, match="permission denied"):
        tunnel.__enter__()
    assert tunnel._proc is None
    assert tunnel._stderr is None


def test_tunnel_starts_and_stops_ssh(tmp_path, monkeypatch):
    body = """
local_port = int(sys.argv[sys.argv.index("-L") + 1].split(":")[0])
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", local_port))
server.listen()
time.sleep(60)
"""
    _install_fake_ssh(tmp_path, monkeypatch, body)
    port = _free_port()
    with SshTunnel(SshTarget(host="example.org"), remote_port=9, local_port=port) as tunnel:
        process = tunnel._proc
        assert tunnel.local_url == f"http://127.0.0.1:{port}"
        assert process is not None and process.poll() is None
    assert process.poll() is not None
    assert tunnel._proc is None
