"""Hardening tests for SSH argument handling and copy-back extraction."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from morphic_agent.execution import scheduler, ssh


def _loc(**extra):
    metadata = {"remote_host": "node1", "remote_workdir": "/w", **extra}
    return SimpleNamespace(metadata=metadata)


@pytest.mark.parametrize("host", ["-oProxyCommand=x", "a b", "a\nb", "a\x00b"])
def test_remote_ssh_target_rejects_bad_host(host):
    with pytest.raises(ValueError):
        ssh.remote_ssh_target(_loc(remote_host=host))


@pytest.mark.parametrize("user", ["-oProxyCommand=x", "a b", "a\tb"])
def test_remote_ssh_target_rejects_bad_user(user):
    with pytest.raises(ValueError):
        ssh.remote_ssh_target(_loc(remote_user=user))


@pytest.mark.parametrize("host,user", [("node1", None), ("2001:db8::1", "bob"), ("host.example.org", "alice")])
def test_valid_hosts_use_double_dash(host, user):
    extra = {"remote_host": host}
    if user:
        extra["remote_user"] = user
    args = ssh._ssh_args(ssh.remote_ssh_target(_loc(**extra)))
    assert args[-2] == "--"
    assert args[-1] == (f"{user}@{host}" if user else host)


def test_scheduler_ssh_args_validate_and_separate():
    good = scheduler.scheduler_local_target(SimpleNamespace(metadata={"remote_host": "h", "remote_user": "u"}))
    args = scheduler._ssh_args(good)
    assert args[-2:] == ["--", "u@h"]
    bad = scheduler.scheduler_local_target(SimpleNamespace(metadata={"remote_host": "h", "remote_user": "-oProxyCommand=x"}))
    with pytest.raises(ValueError):
        scheduler._ssh_args(bad)


def _tar(*members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


def _file(name, data=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def _other(name, type_, linkname=""):
    info = tarfile.TarInfo(name)
    info.type = type_
    info.linkname = linkname
    return info, None


def test_extract_restores_files_and_dirs(tmp_path):
    dirinfo, _ = _other("./sub", tarfile.DIRTYPE)
    dirinfo.mode = 0o755
    payload = _tar((dirinfo, None), _file("./sub/a.txt", b"hi"))
    ssh._extract_tar(payload, tmp_path / "out")
    assert (tmp_path / "out" / "sub" / "a.txt").read_bytes() == b"hi"


def test_extract_rejects_symlink_write_through(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    payload = _tar(_other("link", tarfile.SYMTYPE, str(victim)), _file("link/f.txt"))
    with pytest.raises(RuntimeError):
        ssh._extract_tar(payload, tmp_path / "out")
    assert list(victim.iterdir()) == []


@pytest.mark.parametrize(
    "member",
    [
        _other("h", tarfile.LNKTYPE, "a"),
        _other("d", tarfile.CHRTYPE),
        _file("/abs.txt"),
        _file("../esc.txt"),
    ],
)
def test_extract_rejects_unsafe_members(tmp_path, member):
    with pytest.raises(RuntimeError):
        ssh._extract_tar(_tar(member), tmp_path / "out")


def test_copy_back_failure_fails_run(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    def fake_run(cmd, **kwargs):
        if "tar -czf" in cmd[-1]:
            return subprocess.CompletedProcess(cmd, 255, b"", b"boom")
        if kwargs.get("text"):
            return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(ssh.subprocess, "run", fake_run)
    result = ssh.run_remote_ssh_bundle(bundle=bundle, location=_loc(), timeout=5)
    assert result["remote_copy_back"]["status"] == "failed"
    assert result["returncode"] != 0


def test_unsafe_archive_fails_run_without_raising(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    bad = _tar(_other("link", tarfile.SYMTYPE, "/tmp"))

    def fake_run(cmd, **kwargs):
        if "tar -czf" in cmd[-1]:
            return subprocess.CompletedProcess(cmd, 0, bad, b"")
        if kwargs.get("text"):
            return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(ssh.subprocess, "run", fake_run)
    result = ssh.run_remote_ssh_bundle(bundle=bundle, location=_loc(), timeout=5)
    assert result["remote_copy_back"]["status"] == "failed"
    assert result["returncode"] != 0


def test_front_tunnel_separates_destination_from_options(monkeypatch):
    from morphic_front import sshtunnel

    with pytest.raises(ValueError):
        sshtunnel.SshTarget(host="-oProxyCommand=x")
    seen = {}

    class _Proc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        return _Proc()

    ports = iter([False, True])
    monkeypatch.setattr(sshtunnel, "_port_open", lambda *a, **k: next(ports, True))
    monkeypatch.setattr(sshtunnel.subprocess, "Popen", fake_popen)
    with sshtunnel.SshTunnel(sshtunnel.SshTarget(host="node1", user="u"), 8000, 8001):
        pass
    assert seen["argv"][-2:] == ["--", "u@node1"]


def _dir(name):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    return info, None


def test_extract_allows_in_tree_relative_symlink(tmp_path):
    payload = _tar(
        _file("work/ab/out.txt"),
        _dir("results"),
        _other("results/out.txt", tarfile.SYMTYPE, "../work/ab/out.txt"),
    )
    ssh._extract_tar(payload, tmp_path / "out")
    assert (tmp_path / "out" / "results" / "out.txt").read_bytes() == (tmp_path / "out" / "work/ab/out.txt").read_bytes()


def test_extract_rejects_escaping_relative_symlink(tmp_path):
    payload = _tar(_other("results/out.txt", tarfile.SYMTYPE, "../../etc/passwd"))
    with pytest.raises(RuntimeError):
        ssh._extract_tar(payload, tmp_path / "out")
