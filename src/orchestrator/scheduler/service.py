from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from orchestrator.config.models import OrchestratorConfig, ScheduleJob
from orchestrator.engine.runner import EngineError, RunEngine
from orchestrator.storage.db import Database
from orchestrator.storage.runs import utcnow


class Scheduler:
    def __init__(self, cfg: OrchestratorConfig, engine: RunEngine | None = None):
        self.cfg = cfg
        self.engine = engine or RunEngine(cfg)
        self.db = self.engine.db
        self.tz = ZoneInfo(cfg.schedule.timezone or cfg.timezone())

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def due_jobs(self, now: datetime | None = None) -> list[tuple[ScheduleJob, datetime]]:
        now = now or self._now()
        due = []
        for job in self.cfg.schedule.jobs:
            if not job.enabled:
                continue
            fire_at = self._next_or_misfire(job, now)
            if fire_at is not None:
                due.append((job, fire_at))
        return due

    def _state(self, job_id: str) -> dict:
        row = self.db.connect().execute(
            "SELECT * FROM scheduler_state WHERE job_id=?", (job_id,)
        ).fetchone()
        return dict(row) if row else {}

    def _save_state(self, job_id: str, last_fire: datetime, next_fire: datetime, status: str) -> None:
        self.db.connect().execute(
            """
            INSERT INTO scheduler_state (job_id, last_fire_at, last_enqueued_at, next_fire_at, last_status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              last_fire_at=excluded.last_fire_at,
              last_enqueued_at=excluded.last_enqueued_at,
              next_fire_at=excluded.next_fire_at,
              last_status=excluded.last_status
            """,
            (job_id, last_fire.isoformat(), utcnow(), next_fire.isoformat(), status),
        )

    def _claimed(self, job_id: str, fire_at: datetime) -> bool:
        conn = self.db.connect()
        try:
            conn.execute(
                "INSERT INTO scheduler_executions (job_id, fire_at) VALUES (?, ?)",
                (job_id, fire_at.replace(second=0, microsecond=0).isoformat()),
            )
            return True
        except Exception:
            return False

    def _next_or_misfire(self, job: ScheduleJob, now: datetime) -> datetime | None:
        cron = croniter(job.cron, now)
        prev = cron.get_prev(datetime)
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=self.tz)
        state = self._state(job.id)
        last = state.get("last_fire_at")
        grace = timedelta(seconds=self.cfg.schedule.misfire_grace_seconds)
        window_start = now - grace
        if last:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=self.tz)
            if prev <= last_dt:
                return None
        if prev <= now and prev >= window_start:
            if last and datetime.fromisoformat(last) >= prev:
                return None
            return prev
        if prev < window_start:
            if job.misfire == "run" and (not last or datetime.fromisoformat(last) < prev):
                return prev
            # skip: mark as consumed without running
            nxt = croniter(job.cron, now).get_next(datetime)
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=self.tz)
            self._save_state(job.id, prev, nxt, "skipped_misfire")
            return None
        return None

    def tick(self) -> list[dict]:
        results = []
        for job, fire_at in self.due_jobs():
            if not self._claimed(job.id, fire_at):
                continue
            nxt = croniter(job.cron, self._now()).get_next(datetime)
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=self.tz)
            try:
                run = self.engine.run_suite(job.suite)
                self.db.connect().execute(
                    "UPDATE scheduler_executions SET run_id=? WHERE job_id=? AND fire_at=?",
                    (run.get("id"), job.id, fire_at.replace(second=0, microsecond=0).isoformat()),
                )
                self._save_state(job.id, fire_at, nxt, run.get("status", "ok"))
                results.append(run)
            except EngineError as exc:
                self._save_state(job.id, fire_at, nxt, f"error:{exc}")
                results.append({"job": job.id, "error": str(exc)})
        return results

    def recover_expired_maintenance(self) -> list[str]:
        recovered = []
        now = datetime.now().astimezone()
        for run in self.engine.store.active_runs():
            deadline = run.get("maintenance_deadline")
            if not deadline:
                continue
            try:
                dl = datetime.fromisoformat(deadline)
            except ValueError:
                continue
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=self.tz)
            if dl < now:
                self.engine.recover(run["id"])
                recovered.append(run["id"])
        return recovered

    def loop_forever(self) -> None:
        import time

        while True:
            self.recover_expired_maintenance()
            self.tick()
            time.sleep(self.cfg.schedule.tick_seconds)
