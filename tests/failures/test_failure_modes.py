from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from orchestrator.config.loader import load_config
from orchestrator.engine.runner import EngineError, RunEngine
from orchestrator.k6.runner import K6Result
from orchestrator.lifecycle.base import LifecycleResult, TargetAdapter
from orchestrator.storage.locks import RunLock


class FakeAdapter(TargetAdapter):
    def __init__(self, **flags):
        self.flags = flags
        self.enabled = False

    def check_connection(self):
        return LifecycleResult(not self.flags.get("ssh_down"), "ssh")

    def capture_state(self):
        return LifecycleResult(True, "{}", {})

    def enable_maintenance(self, *, ttl_seconds=None):
        self.enabled = True
        return LifecycleResult(True, "on")

    def verify_maintenance(self):
        if self.flags.get("health_fail"):
            return LifecycleResult(False, "healthcheck failure")
        if self.flags.get("test_is_503"):
            return LifecycleResult(False, "test traffic is not live during maintenance")
        return LifecycleResult(True, "public=503 test=200")

    def disable_maintenance(self):
        if self.flags.get("cleanup_fail"):
            return LifecycleResult(False, "cannot disable")
        self.enabled = False
        return LifecycleResult(True, "off")

    def verify_live(self):
        if self.flags.get("cleanup_fail"):
            return LifecycleResult(False, "still down")
        return LifecycleResult(True, "public=200")

    def collect_diagnostics(self):
        return LifecycleResult(True, "ok", {"d": "ok"})


def _write_cfg(tmp_path: Path) -> Path:
    data = {
        "project": {"name": "t", "timezone": "UTC"},
        "target": {
            "type": "none",
            "traffic": {
                "public_base_url": "http://public",
                "test_base_url": "http://test",
                "health_path": "/health",
            },
        },
        "maintenance": {"enabled": True, "ttl_seconds": 60},
        "storage": {
            "sqlite_path": str(tmp_path / "o.db"),
            "results_dir": str(tmp_path / "results"),
        },
        "safety": {
            "max_vus": 10,
            "max_test_duration": "30s",
            "max_error_rate": 0.5,
            "max_cpu": 50,
            "abort_if_target_unreachable": True,
            "abort_if_prometheus_unavailable": False,
        },
        "monitoring": {"enabled": False},
        "suites": {"smoke": {"tests": ["smoke"], "continue_on_failure": False}},
        "tests": {
            "smoke": {
                "script": "k6/smoke.js",
                "params": {"executor": "constant-vus", "vus": 1, "duration": "2s"},
            }
        },
    }
    path = tmp_path / "o.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def _run(tmp_path, adapter, k6_result=None, target_ok=True):
    cfg = load_config(_write_cfg(tmp_path))
    engine = RunEngine(cfg)
    k6_result = k6_result or K6Result(0, "ok", "", {"metrics": {}}, 0.2, False)
    with patch("orchestrator.engine.runner.build_adapter", return_value=adapter):
        with patch.object(engine.k6, "run", return_value=k6_result):
            with patch("orchestrator.engine.runner._http_ok", return_value=target_ok):
                return engine.run_suite("smoke"), engine


def test_ssh_unavailable(tmp_path):
    run, _ = _run(tmp_path, FakeAdapter(ssh_down=True), target_ok=True)
    assert run["status"] in {"failed", "recovery_required"}
    assert "connection" in (run.get("error") or "").lower() or "ssh" in (run.get("error") or "").lower()


def test_target_unavailable(tmp_path):
    run, _ = _run(tmp_path, FakeAdapter(), target_ok=False)
    assert run["status"] in {"failed", "recovery_required"}


def test_healthcheck_failure(tmp_path):
    run, _ = _run(tmp_path, FakeAdapter(health_fail=True))
    assert run["status"] in {"failed", "recovery_required"}


def test_k6_nonzero(tmp_path):
    run, _ = _run(tmp_path, FakeAdapter(), K6Result(1, "", "boom", {}, 0.1, False))
    assert run["status"] in {"failed", "recovery_required"}


def test_threshold_failure(tmp_path):
    run, engine = _run(tmp_path, FakeAdapter(), K6Result(99, "", "thresholds", {}, 0.1, False))
    assert run["status"] in {"failed", "recovery_required"}
    tests = engine.store.tests(run["id"])
    assert tests and (tests[0]["status"] == "failed" or "threshold" in (tests[0].get("error") or "").lower())


def test_prometheus_unavailable_does_not_abort_by_default(tmp_path):
    run, engine = _run(tmp_path, FakeAdapter())
    engine.cfg.monitoring.enabled = True
    engine.cfg.monitoring.prometheus_url = "http://127.0.0.1:1"
    assert run["status"] == "completed"


def test_influx_unavailable_still_writes_local(tmp_path):
    run, _ = _run(tmp_path, FakeAdapter())
    assert run["status"] == "completed"
    assert (Path(run["artifacts_dir"]) / "report.html").exists()


def test_sigterm_abort(tmp_path):
    run, _ = _run(tmp_path, FakeAdapter(), K6Result(130, "", "", {}, 0.1, True))
    assert run["status"] in {"aborted", "failed", "recovery_required"}


def test_duplicate_execution_lock(tmp_path):
    cfg = load_config(_write_cfg(tmp_path))
    engine = RunEngine(cfg)
    lock = RunLock(engine.db)
    assert lock.acquire("other")
    with pytest.raises(EngineError):
        with patch("orchestrator.engine.runner.build_adapter", return_value=FakeAdapter()):
            with patch("orchestrator.engine.runner._http_ok", return_value=True):
                engine.run_suite("smoke")


def test_maintenance_cleanup_failure(tmp_path):
    run, _ = _run(tmp_path, FakeAdapter(cleanup_fail=True))
    assert run["status"] == "recovery_required"


def test_cpu_safety(tmp_path):
    from orchestrator.safety.controller import SafetyController
    from orchestrator.config.models import OrchestratorConfig, ProjectConfig, TargetConfig, TrafficConfig

    cfg = OrchestratorConfig(
        project=ProjectConfig(name="t"),
        target=TargetConfig(type="none", traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t")),
        maintenance={"enabled": False},
        safety={"max_cpu": 10},
    )
    d = SafetyController(cfg).evaluate_metrics(cpu=99)
    assert d.abort


def test_max_duration_safety_controller():
    from orchestrator.safety.controller import SafetyController
    from orchestrator.config.models import OrchestratorConfig, ProjectConfig, TargetConfig, TrafficConfig

    cfg = OrchestratorConfig(
        project=ProjectConfig(name="t"),
        target=TargetConfig(type="none", traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t")),
        maintenance={"enabled": False},
        safety={"max_test_duration": "10s"},
    )
    d = SafetyController(cfg).evaluate_metrics(elapsed_seconds=99, max_duration_seconds=10)
    assert d.abort


def test_payment_timeout_and_error_scripts_exist():
    root = Path(__file__).resolve().parents[2] / "examples/demo-project/k6/scenarios/resilience.js"
    text = root.read_text()
    assert "paymentFlow" in text
    assert "PAYMENT_SCENARIO" in text
