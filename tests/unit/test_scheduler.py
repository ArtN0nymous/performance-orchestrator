from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from orchestrator.config.models import (
    OrchestratorConfig,
    ProjectConfig,
    ScheduleConfig,
    ScheduleJob,
    TargetConfig,
    TrafficConfig,
)
from orchestrator.scheduler.service import Scheduler
from orchestrator.storage.db import Database
from orchestrator.engine.runner import RunEngine


def _cfg(db_path: str) -> OrchestratorConfig:
    return OrchestratorConfig(
        project=ProjectConfig(name="t", timezone="UTC"),
        target=TargetConfig(
            type="none",
            traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t"),
        ),
        maintenance={"enabled": False},
        storage={"sqlite_path": db_path, "results_dir": "/tmp/results-test"},
        schedule=ScheduleConfig(
            timezone="UTC",
            misfire_grace_seconds=3600,
            jobs=[ScheduleJob(id="j1", cron="0 10 * * *", suite="smoke", misfire="skip")],
        ),
        suites={"smoke": {"id": "smoke", "tests": []}},
        tests={},
    )


def test_duplicate_fire_claim(tmp_path):
    db = str(tmp_path / "o.db")
    cfg = _cfg(db)
    sched = Scheduler(cfg, engine=RunEngine(cfg, Database(db)))
    now = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("UTC"))
    job = cfg.schedule.jobs[0]
    assert sched._claimed(job.id, now) is True
    assert sched._claimed(job.id, now) is False


def test_skip_misfire_marks_state(tmp_path):
    db = str(tmp_path / "o.db")
    cfg = _cfg(db)
    cfg.schedule.misfire_grace_seconds = 1
    sched = Scheduler(cfg, engine=RunEngine(cfg, Database(db)))
    now = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    due = sched.due_jobs(now)
    assert due == []
    state = sched._state("j1")
    assert state.get("last_status") == "skipped_misfire"


def test_run_misfire_returns_job(tmp_path):
    db = str(tmp_path / "o.db")
    cfg = _cfg(db)
    cfg.schedule.misfire_grace_seconds = 1
    cfg.schedule.jobs[0].misfire = "run"
    sched = Scheduler(cfg, engine=RunEngine(cfg, Database(db)))
    now = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    due = sched.due_jobs(now)
    assert len(due) == 1
    assert due[0][0].id == "j1"
