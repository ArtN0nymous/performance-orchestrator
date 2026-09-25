from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LifecycleResult:
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


class TargetAdapter(ABC):
    @abstractmethod
    def check_connection(self) -> LifecycleResult: ...

    @abstractmethod
    def capture_state(self) -> LifecycleResult: ...

    @abstractmethod
    def enable_maintenance(self, *, ttl_seconds: int | None = None) -> LifecycleResult: ...

    @abstractmethod
    def verify_maintenance(self) -> LifecycleResult: ...

    @abstractmethod
    def disable_maintenance(self) -> LifecycleResult: ...

    @abstractmethod
    def verify_live(self) -> LifecycleResult: ...

    @abstractmethod
    def collect_diagnostics(self) -> LifecycleResult: ...

    def backup_database(self) -> LifecycleResult:
        return LifecycleResult(True, "backup_database skipped")

    def restore_database(self) -> LifecycleResult:
        return LifecycleResult(True, "restore_database skipped")

    def database_row_counts(self) -> LifecycleResult:
        return LifecycleResult(True, "database_row_counts skipped", {})

    def probe_database_snapshot(self) -> LifecycleResult:
        """Doctor/preflight: verify mysqldump/mysql + DB reachability when snapshot is enabled."""
        return LifecycleResult(True, "db_snapshot probe skipped")
