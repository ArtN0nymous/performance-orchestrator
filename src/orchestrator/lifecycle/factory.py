from orchestrator.lifecycle.laravel import LaravelAdapter
from orchestrator.lifecycle.ssh_generic import GenericSshAdapter
from orchestrator.lifecycle.base import LifecycleResult, TargetAdapter


class NoopAdapter(TargetAdapter):
    def check_connection(self) -> LifecycleResult:
        return LifecycleResult(True, "lifecycle disabled")

    def capture_state(self) -> LifecycleResult:
        return LifecycleResult(True, "{}", {})

    def enable_maintenance(self, *, ttl_seconds: int | None = None) -> LifecycleResult:
        return LifecycleResult(True, "skipped")

    def verify_maintenance(self) -> LifecycleResult:
        return LifecycleResult(True, "skipped")

    def disable_maintenance(self) -> LifecycleResult:
        return LifecycleResult(True, "skipped")

    def verify_live(self) -> LifecycleResult:
        return LifecycleResult(True, "skipped")

    def collect_diagnostics(self) -> LifecycleResult:
        return LifecycleResult(True, "skipped", {})

    def probe_database_snapshot(self) -> LifecycleResult:
        return LifecycleResult(True, "lifecycle disabled")


def build_adapter(cfg):
    kind = cfg.target.type
    if kind == "none":
        return NoopAdapter()
    if kind == "laravel":
        return LaravelAdapter(cfg)
    if kind == "ssh_generic":
        return GenericSshAdapter(cfg)
    raise ValueError(f"unknown target type: {kind}")
