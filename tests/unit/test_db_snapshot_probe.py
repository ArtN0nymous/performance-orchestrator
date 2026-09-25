from orchestrator.config.models import DatabaseSnapshotConfig
from orchestrator.lifecycle.base import LifecycleResult
from orchestrator.lifecycle.ssh_generic import GenericSshAdapter
from orchestrator.ssh.client import SshError


class _Cfg:
    def __init__(self, *, snapshot: DatabaseSnapshotConfig | None = None):
        self.database_snapshot = snapshot or DatabaseSnapshotConfig(enabled=True, disable_ssl=True)

    class maintenance:
        ttl_seconds = 60
        secret = None

    class target:
        remote_workdir = "/var/www"
        php_binary = "php"
        artisan_path = "artisan"
        ssh = object()
        commands = type(
            "C",
            (),
            {
                "backup_database": "echo backup",
                "restore_database": "echo restore",
                "database_row_counts": None,
                "check_connection": "true",
                "capture_state": "echo {}",
                "enable_maintenance": "true",
                "disable_maintenance": "true",
                "verify_maintenance": None,
                "verify_live": None,
                "collect_diagnostics": "true",
            },
        )()

    class health:
        timeout_seconds = 5.0


class _FakeSsh:
    def __init__(self, *, fail_token: str | None = None, capture: list | None = None):
        self.fail_token = fail_token
        self.capture = capture if capture is not None else []

    def run(self, cmd: str):
        self.capture.append(cmd)
        if self.fail_token:
            raise SshError("remote failed", stdout=self.fail_token, stderr="", returncode=1)
        return type("R", (), {"stdout": "db_snapshot_ok\n", "stderr": "", "returncode": 0})()


def test_probe_database_snapshot_ok():
    adapter = GenericSshAdapter.__new__(GenericSshAdapter)
    adapter.cfg = _Cfg()
    adapter.commands = _Cfg.target.commands
    captured: list[str] = []
    adapter.ssh = _FakeSsh(capture=captured)
    result = GenericSshAdapter.probe_database_snapshot(adapter)
    assert result.ok
    assert "db_snapshot_ok" in result.detail
    assert "--ssl=0" in captured[0]


def test_probe_database_snapshot_mysqldump_missing():
    adapter = GenericSshAdapter.__new__(GenericSshAdapter)
    adapter.cfg = _Cfg()
    adapter.commands = _Cfg.target.commands
    adapter.ssh = _FakeSsh(fail_token="mysqldump_missing")
    result = GenericSshAdapter.probe_database_snapshot(adapter)
    assert not result.ok
    assert result.detail == "mysqldump_missing"


def test_probe_skipped_when_disabled():
    adapter = GenericSshAdapter.__new__(GenericSshAdapter)
    adapter.cfg = _Cfg(snapshot=DatabaseSnapshotConfig(enabled=False))
    adapter.commands = _Cfg.target.commands
    adapter.ssh = _FakeSsh(fail_token="should_not_run")
    result = GenericSshAdapter.probe_database_snapshot(adapter)
    assert result == LifecycleResult(True, "disabled")


def test_render_injects_mysql_ssl_opts_from_orchestrator():
    adapter = GenericSshAdapter.__new__(GenericSshAdapter)
    adapter.cfg = _Cfg(snapshot=DatabaseSnapshotConfig(enabled=True, disable_ssl=True))
    out = GenericSshAdapter._render(
        adapter,
        'cd {remote_workdir} && mysql {mysql_ssl_opts} -e "SELECT 1" && echo {php_binary}',
    )
    assert out.startswith("cd /var/www &&")
    assert "--ssl=0" in out
    assert "echo php" in out


def test_resolved_mysql_opts_override_and_ssl_on():
    assert DatabaseSnapshotConfig(disable_ssl=True).resolved_mysql_opts() == "--ssl=0"
    assert DatabaseSnapshotConfig(disable_ssl=False).resolved_mysql_opts() == ""
    assert (
        DatabaseSnapshotConfig(disable_ssl=True, mysql_opts="--ssl-mode=REQUIRED").resolved_mysql_opts()
        == "--ssl-mode=REQUIRED"
    )
