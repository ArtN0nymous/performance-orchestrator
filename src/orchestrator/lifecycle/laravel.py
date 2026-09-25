from __future__ import annotations

from orchestrator.config.models import CommandSet, OrchestratorConfig
from orchestrator.lifecycle.ssh_generic import GenericSshAdapter


class LaravelAdapter(GenericSshAdapter):
    """Optional Laravel helpers. Commands remain configurable; nothing is hardcoded."""

    def __init__(self, cfg: OrchestratorConfig, **kwargs):
        php = cfg.target.php_binary or "php"
        artisan = cfg.target.artisan_path or "artisan"
        secret = cfg.maintenance.secret
        down = cfg.target.down_command or (
            f"{php} {artisan} down --retry=60" + (f" --secret={secret}" if secret else "")
        )
        up = cfg.target.up_command or f"{php} {artisan} up"
        defaults = CommandSet(
            check_connection="uname -a && id",
            capture_state=f"test -f {artisan} && echo '{{\"artisan\":true}}' || echo '{{\"artisan\":false}}'",
            enable_maintenance=down,
            disable_maintenance=up,
            collect_diagnostics="df -h; uptime; (ps aux | head -n 40)",
            php_fpm_status="ps aux | grep -E '[p]hp-fpm|[p]hp-cgi' || true",
            queue_status=f"{php} {artisan} queue:monitor 2>/dev/null || ps aux | grep -E '[q]ueue:work|[h]orizon' || true",
            web_server_status="ps aux | grep -E '[n]ginx|[a]pache2|[h]ttpd' || true",
            database_status="ps aux | grep -E '[m]ysqld|[p]ostgres' || true",
            logs="tail -n 200 storage/logs/laravel.log 2>/dev/null || true",
            install_watchdog=None,
        )
        if cfg.target.commands is None:
            cfg.target.commands = defaults
        else:
            merged = defaults.model_dump()
            merged.update({k: v for k, v in cfg.target.commands.model_dump().items() if v is not None})
            cfg.target.commands = CommandSet(**merged)
        super().__init__(cfg, **kwargs)
