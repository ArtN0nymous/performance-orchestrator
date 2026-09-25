from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestrator.config.models import SshConfig


class SshError(Exception):
    def __init__(self, message: str, *, stdout: str = "", stderr: str = "", returncode: int = 1):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@dataclass
class SshResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SshClient:
    """OpenSSH wrapper. Default is StrictHostKeyChecking=yes — never 'no'."""

    def __init__(self, cfg: SshConfig):
        self.cfg = cfg
        if cfg.strict_host_key_checking not in {"yes", "accept-new"}:
            raise SshError("StrictHostKeyChecking=no is not allowed")

    def _base_cmd(self) -> list[str]:
        identity = str(Path(self.cfg.identity_file))
        known = str(Path(self.cfg.known_hosts_file))
        return [
            "ssh",
            "-p",
            str(self.cfg.port),
            "-i",
            identity,
            "-o",
            f"UserKnownHostsFile={known}",
            "-o",
            f"StrictHostKeyChecking={self.cfg.strict_host_key_checking}",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            f"ConnectTimeout={self.cfg.connect_timeout_seconds}",
            "-o",
            "BatchMode=yes",
            f"{self.cfg.user}@{self.cfg.host}",
        ]

    def run(self, remote_command: str, timeout: int = 60) -> SshResult:
        cmd = self._base_cmd() + [remote_command]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SshError("ssh client is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise SshError("ssh timed out", stdout=exc.stdout or "", stderr=exc.stderr or "") from exc
        result = SshResult(proc.returncode, proc.stdout or "", proc.stderr or "")
        if not result.ok:
            raise SshError(
                f"ssh command failed: {remote_command}",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        return result

    def try_run(self, remote_command: str, timeout: int = 60) -> SshResult:
        try:
            return self.run(remote_command, timeout=timeout)
        except SshError as exc:
            return SshResult(exc.returncode, exc.stdout, exc.stderr)

    def quoted(self, command: str) -> str:
        return shlex.quote(command)
