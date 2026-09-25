from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from orchestrator.config.models import OrchestratorConfig
from orchestrator.http_probe import probe_headers
from orchestrator.lifecycle.base import LifecycleResult, TargetAdapter
from orchestrator.ssh.client import SshClient, SshError


class GenericSshAdapter(TargetAdapter):
    """Configurable remote commands. No hardcoded users, IPs, paths, or service names."""

    def __init__(self, cfg: OrchestratorConfig, ssh: SshClient | None = None, http: httpx.Client | None = None):
        if cfg.target.ssh is None:
            raise ValueError("target.ssh is required for ssh_generic adapter")
        if cfg.target.commands is None:
            raise ValueError("target.commands is required for ssh_generic adapter")
        self.cfg = cfg
        self.ssh = ssh or SshClient(cfg.target.ssh)
        self.http = http or httpx.Client(timeout=cfg.health.timeout_seconds, follow_redirects=True)
        self.commands = cfg.target.commands

    def _render(self, template: str, extra: dict | None = None) -> str:
        ttl = self.cfg.maintenance.ttl_seconds
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        mapping = {
            "ttl_seconds": str(ttl),
            "deadline": deadline,
            "secret": self.cfg.maintenance.secret or "",
            "php_binary": self.cfg.target.php_binary,
            "artisan_path": self.cfg.target.artisan_path or "",
            "remote_workdir": self.cfg.target.remote_workdir or "",
            "mysql_ssl_opts": self.cfg.database_snapshot.resolved_mysql_opts(),
        }
        if extra:
            mapping.update({k: str(v) for k, v in extra.items()})
        # Replace only known {placeholders}. Do not use str.format — bash ${VAR}
        # would raise KeyError or be corrupted.
        out = template
        for key, value in mapping.items():
            out = out.replace("{" + key + "}", value)
        return out

    def check_connection(self) -> LifecycleResult:
        try:
            result = self.ssh.run(self._render(self.commands.check_connection))
            return LifecycleResult(True, result.stdout.strip())
        except SshError as exc:
            return LifecycleResult(False, str(exc), {"stderr": exc.stderr})

    def capture_state(self) -> LifecycleResult:
        try:
            result = self.ssh.run(self._render(self.commands.capture_state))
            data = _try_json(result.stdout)
            return LifecycleResult(True, result.stdout, data)
        except SshError as exc:
            return LifecycleResult(False, str(exc), {"stderr": exc.stderr})

    def enable_maintenance(self, *, ttl_seconds: int | None = None) -> LifecycleResult:
        extra = {"ttl_seconds": ttl_seconds or self.cfg.maintenance.ttl_seconds}
        try:
            result = self.ssh.run(self._render(self.commands.enable_maintenance, extra))
            if self.cfg.maintenance.watchdog_enabled and self.commands.install_watchdog:
                self.ssh.try_run(self._render(self.commands.install_watchdog, extra))
            return LifecycleResult(True, result.stdout)
        except SshError as exc:
            return LifecycleResult(False, str(exc), {"stderr": exc.stderr})

    def verify_maintenance(self) -> LifecycleResult:
        remote_detail = ""
        if self.commands.verify_maintenance:
            try:
                remote = self.ssh.run(self._render(self.commands.verify_maintenance))
                remote_detail = (remote.stdout or "").strip()
            except SshError as exc:
                return LifecycleResult(
                    False,
                    f"verify_maintenance command failed: {exc}",
                    {"stderr": exc.stderr},
                )

        traffic = self.cfg.target.traffic
        public_url = (self.cfg.health.public_url or traffic.public_base_url.rstrip("/") + traffic.health_path)
        test_url = (self.cfg.health.test_url or traffic.test_base_url.rstrip("/") + traffic.health_path)
        public_status = self._status(public_url, public=True)
        test_status = self._status(test_url, public=False)
        public_ok = public_status == traffic.public_expect_status_when_maintenance
        test_ok = test_status == traffic.test_expect_status_when_maintenance
        detail = f"public={public_status} test={test_status}"
        if remote_detail:
            detail = f"{detail}; remote={remote_detail}"
        if not public_ok:
            return LifecycleResult(False, f"public traffic not in expected maintenance state ({detail})")
        if not test_ok:
            return LifecycleResult(
                False,
                f"test traffic is not live during maintenance ({detail}); refusing to run k6 against 503-only path",
            )
        return LifecycleResult(True, detail, {"public": public_status, "test": test_status, "remote": remote_detail})

    def disable_maintenance(self) -> LifecycleResult:
        try:
            result = self.ssh.run(self._render(self.commands.disable_maintenance))
            return LifecycleResult(True, result.stdout)
        except SshError as exc:
            return LifecycleResult(False, str(exc), {"stderr": exc.stderr})

    def verify_live(self) -> LifecycleResult:
        traffic = self.cfg.target.traffic
        public_url = (self.cfg.health.public_url or traffic.public_base_url.rstrip("/") + traffic.health_path)
        status = self._status(public_url, public=True)
        ok = 200 <= status < 300
        return LifecycleResult(ok, f"public={status}", {"public": status})

    def collect_diagnostics(self) -> LifecycleResult:
        blobs: dict[str, str] = {}
        for name, tmpl in {
            "diagnostics": self.commands.collect_diagnostics,
            "php_fpm": self.commands.php_fpm_status,
            "queue": self.commands.queue_status,
            "web": self.commands.web_server_status,
            "database": self.commands.database_status,
            "logs": self.commands.logs,
        }.items():
            if not tmpl:
                continue
            result = self.ssh.try_run(self._render(tmpl))
            blobs[name] = result.stdout or result.stderr
        return LifecycleResult(True, "collected", blobs)

    def backup_database(self) -> LifecycleResult:
        tmpl = self.commands.backup_database
        if not tmpl or not str(tmpl).strip():
            return LifecycleResult(True, "backup_database skipped")
        try:
            result = self.ssh.run(self._render(tmpl))
            return LifecycleResult(True, result.stdout.strip() or "backup_ok")
        except SshError as exc:
            return LifecycleResult(False, str(exc), {"stderr": exc.stderr})

    def restore_database(self) -> LifecycleResult:
        tmpl = self.commands.restore_database
        if not tmpl or not str(tmpl).strip():
            return LifecycleResult(True, "restore_database skipped")
        try:
            result = self.ssh.run(self._render(tmpl))
            return LifecycleResult(True, result.stdout.strip() or "restore_ok")
        except SshError as exc:
            return LifecycleResult(False, str(exc), {"stderr": exc.stderr})

    def database_row_counts(self) -> LifecycleResult:
        tmpl = self.commands.database_row_counts
        if not tmpl or not str(tmpl).strip():
            return LifecycleResult(True, "database_row_counts skipped", {})
        try:
            result = self.ssh.run(self._render(tmpl))
            data = _try_json(result.stdout)
            counts = _normalize_row_counts(data if isinstance(data, dict) else {})
            return LifecycleResult(True, result.stdout.strip(), counts)
        except SshError as exc:
            return LifecycleResult(False, str(exc), {"stderr": exc.stderr})

    def probe_database_snapshot(self) -> LifecycleResult:
        if not self.cfg.database_snapshot.enabled:
            return LifecycleResult(True, "disabled")
        if not self.commands.backup_database or not str(self.commands.backup_database).strip():
            return LifecycleResult(False, "enabled but backup_database command is not configured")
        if not self.commands.restore_database or not str(self.commands.restore_database).strip():
            return LifecycleResult(False, "enabled but restore_database command is not configured")
        workdir = self.cfg.target.remote_workdir or "."
        ssl_opts = self.cfg.database_snapshot.resolved_mysql_opts()
        # Shell uses $VAR (not ${VAR}) for remote DB_* from the API .env.
        # SSL flags come from the orchestrator (injected below), not the API host.
        script = (
            f"cd {workdir} && set -a && . ./.env && set +a && "
            '{ test -n "$DB_PORT" || DB_PORT=3306; } && '
            "command -v mysqldump >/dev/null || { echo mysqldump_missing; exit 1; } && "
            "command -v mysql >/dev/null || { echo mysql_client_missing; exit 1; } && "
            'test -n "$DB_HOST" && test -n "$DB_DATABASE" && test -n "$DB_USERNAME" || { echo db_env_incomplete; exit 1; } && '
            f'mysql -N -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USERNAME" -p"$DB_PASSWORD" {ssl_opts} "$DB_DATABASE" -e "SELECT 1" >/dev/null && '
            "mysqldump --help >/dev/null && "
            "echo db_snapshot_ok"
        )
        try:
            result = self.ssh.run(script)
            detail = (result.stdout or "").strip() or "db_snapshot_ok"
            return LifecycleResult(True, detail)
        except SshError as exc:
            detail = (exc.stderr or str(exc)).strip()
            # Prefer the remote echo token when present.
            for token in ("mysqldump_missing", "mysql_client_missing", "db_env_incomplete"):
                blob = f"{exc.stdout or ''} {detail}"
                if token in blob:
                    return LifecycleResult(False, token)
            return LifecycleResult(False, detail[:300] or "db_snapshot_probe_failed")

    def _status(self, url: str, *, public: bool) -> int:
        headers = probe_headers(self.cfg.target.traffic, public=public)
        try:
            resp = self.http.get(url, headers=headers)
            return resp.status_code
        except httpx.HTTPError:
            return 0


def _try_json(text: str):
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {"raw": text}


def _normalize_row_counts(data: dict) -> dict:
    out: dict = {}
    for key, value in data.items():
        if key == "raw" or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[key] = int(value)
        elif isinstance(value, str):
            try:
                out[key] = int(float(value))
            except ValueError:
                continue
    return out
