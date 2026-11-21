"""SSH port-forwarding for services that are only reachable on a remote host.

`SshTunnel` runs `ssh -N -L` so a service bound to a remote loopback port appears
at `http://127.0.0.1:<local_port>`. Callers then use plain HTTP and do not need to
know whether the service is local or tunnelled.

This module shells out to the system `ssh`. Credentials are an SSH key or agent
plus `user@host`; this code stores no secrets.
"""

from __future__ import annotations

import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import IO


@dataclass
class SshTarget:
    """How to reach a host over SSH."""

    host: str
    user: str | None = None
    port: int = 22
    key_path: str | None = None
    extra_opts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # A value starting with "-" would be parsed by ssh as a command-line option.
        for label, value in (("host", self.host), ("user", self.user)):
            if value is None:
                continue
            if not value or value.startswith("-") or any(char.isspace() for char in value):
                raise ValueError(f"invalid SSH {label}: {value!r}")

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def base_argv(self) -> list[str]:
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if self.port and self.port != 22:
            argv += ["-p", str(self.port)]
        if self.key_path:
            argv += ["-i", self.key_path]
        argv += list(self.extra_opts)
        return argv


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class SshTunnel:
    """Context manager for an `ssh -N -L local:127.0.0.1:remote` port-forward."""

    def __init__(
        self,
        target: SshTarget,
        remote_port: int,
        local_port: int | None = None,
        *,
        startup_timeout: float = 15.0,
    ) -> None:
        self.target = target
        self.remote_port = remote_port
        self.local_port = local_port or remote_port
        self.startup_timeout = startup_timeout
        self._proc: subprocess.Popen | None = None
        self._stderr: IO[bytes] | None = None

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.local_port}"

    def _stderr_text(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.seek(0)
        return self._stderr.read().decode(errors="replace").strip()

    def __enter__(self) -> "SshTunnel":
        if _port_open("127.0.0.1", self.local_port):
            # Something already forwards this port (e.g. a pre-existing tunnel).
            return self
        argv = self.target.base_argv() + [
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-L",
            f"{self.local_port}:127.0.0.1:{self.remote_port}",
            "--",
            self.target.destination,
        ]
        # A file, unlike an undrained pipe, cannot block a long-lived ssh process.
        self._stderr = tempfile.TemporaryFile()
        try:
            self._proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=self._stderr)
        except OSError:
            self.__exit__(None, None, None)
            raise
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                err = self._stderr_text()
                self.__exit__(None, None, None)
                raise RuntimeError(f"ssh tunnel exited early: {err or 'unknown error'}")
            if _port_open("127.0.0.1", self.local_port):
                return self
            time.sleep(0.25)
        self.__exit__(None, None, None)
        raise TimeoutError(f"ssh tunnel to {self.target.destination}:{self.remote_port} did not come up")

    def __exit__(self, *_exc) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None
        if self._stderr is not None:
            self._stderr.close()
            self._stderr = None
