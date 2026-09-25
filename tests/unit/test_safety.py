from orchestrator.safety.controller import SafetyController, SafetyViolation
from orchestrator.config.models import OrchestratorConfig, ProjectConfig, TargetConfig, TrafficConfig, K6Test, ScenarioParams
import pytest


def _cfg(**safety):
    return OrchestratorConfig(
        project=ProjectConfig(name="t"),
        target=TargetConfig(type="none", traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t")),
        maintenance={"enabled": False},
        safety=safety or {"max_vus": 10, "max_test_duration": "1m", "max_error_rate": 0.2, "max_cpu": 80},
    )


def test_rejects_too_many_vus():
    c = SafetyController(_cfg())
    with pytest.raises(SafetyViolation):
        c.validate_test(K6Test(id="x", script="s.js", params=ScenarioParams(vus=99, duration="10s")))


def test_cpu_abort():
    d = SafetyController(_cfg()).evaluate_metrics(cpu=90)
    assert d.abort
    assert "cpu" in d.reasons[0]


def test_duration_exceeded():
    d = SafetyController(_cfg()).evaluate_metrics(elapsed_seconds=120, max_duration_seconds=60)
    assert d.abort


def test_target_unreachable():
    d = SafetyController(_cfg(abort_if_target_unreachable=True)).evaluate_metrics(target_reachable=False)
    assert d.abort
