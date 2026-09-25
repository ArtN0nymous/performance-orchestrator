from __future__ import annotations

from datetime import datetime, timezone

from orchestrator.storage.db import Database

RUN_STATES = (
    "scheduled",
    "preparing",
    "maintenance",
    "running",
    "collecting",
    "cleanup",
    "completed",
    "failed",
    "aborted",
    "recovery_required",
)

TRANSITIONS = {
    "scheduled": {"preparing", "aborted", "failed"},
    "preparing": {"maintenance", "running", "cleanup", "failed", "aborted", "recovery_required"},
    "maintenance": {"running", "cleanup", "failed", "aborted", "recovery_required"},
    "running": {"collecting", "cleanup", "failed", "aborted", "recovery_required"},
    "collecting": {"cleanup", "failed", "aborted", "recovery_required"},
    "cleanup": {"completed", "failed", "aborted", "recovery_required"},
    "completed": set(),
    "failed": {"cleanup", "recovery_required"},
    "aborted": {"cleanup", "recovery_required"},
    "recovery_required": {"cleanup", "completed", "failed"},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class InvalidTransition(Exception):
    pass


class RunStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, run_id: str, *, suite: str | None, test: str | None, artifacts_dir: str, status: str = "scheduled") -> None:
        now = utcnow()
        self.db.connect().execute(
            """
            INSERT INTO runs (id, suite, test, status, created_at, updated_at, artifacts_dir)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, suite, test, status, now, now, artifacts_dir),
        )
        self.event(run_id, "run created")

    def get(self, run_id: str) -> dict | None:
        row = self.db.connect().execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50) -> list[dict]:
        rows = self.db.connect().execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def set_status(self, run_id: str, status: str, *, error: str | None = None, force: bool = False) -> None:
        current = self.get(run_id)
        if not current:
            raise KeyError(run_id)
        if not force and status not in TRANSITIONS.get(current["status"], set()) and status != current["status"]:
            raise InvalidTransition(f"{current['status']} -> {status}")
        now = utcnow()
        started = current["started_at"] or (now if status in {"preparing", "running"} else None)
        finished = now if status in {"completed", "failed", "aborted"} else current["finished_at"]
        self.db.connect().execute(
            """
            UPDATE runs SET status=?, updated_at=?, error=COALESCE(?, error), started_at=?, finished_at=?
            WHERE id=?
            """,
            (status, now, error, started, finished, run_id),
        )
        self.event(run_id, f"status={status}" + (f" error={error}" if error else ""))

    def set_deadline(self, run_id: str, deadline_iso: str | None) -> None:
        self.db.connect().execute(
            "UPDATE runs SET maintenance_deadline=?, updated_at=? WHERE id=?",
            (deadline_iso, utcnow(), run_id),
        )

    def set_pid(self, run_id: str, pid: int | None) -> None:
        self.db.connect().execute("UPDATE runs SET pid=?, updated_at=? WHERE id=?", (pid, utcnow(), run_id))

    def event(self, run_id: str, message: str, level: str = "info") -> None:
        self.db.connect().execute(
            "INSERT INTO run_events (run_id, ts, level, message) VALUES (?, ?, ?, ?)",
            (run_id, utcnow(), level, message),
        )

    def events(self, run_id: str) -> list[dict]:
        rows = self.db.connect().execute(
            "SELECT * FROM run_events WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def add_test(self, run_id: str, test_id: str, status: str, summary_json: str | None = None, error: str | None = None) -> None:
        now = utcnow()
        self.db.connect().execute(
            """
            INSERT INTO run_tests (run_id, test_id, status, started_at, finished_at, summary_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, test_id, status, now, now, summary_json, error),
        )

    def tests(self, run_id: str) -> list[dict]:
        rows = self.db.connect().execute(
            "SELECT * FROM run_tests WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def active_runs(self) -> list[dict]:
        rows = self.db.connect().execute(
            """
            SELECT * FROM runs WHERE status NOT IN ('completed','failed','aborted')
            """
        ).fetchall()
        return [dict(r) for r in rows]
