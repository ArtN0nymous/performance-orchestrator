from unittest.mock import patch

from orchestrator.k6.runner import K6Runner
from orchestrator.config.models import OrchestratorConfig, ProjectConfig, TargetConfig, TrafficConfig, K6Test, ScenarioParams


def test_k6_cmd_tags_and_outputs(tmp_path):
    cfg = OrchestratorConfig(
        project=ProjectConfig(name="t"),
        target=TargetConfig(type="none", traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t")),
        maintenance={"enabled": False},
        storage={"influx": {"enabled": True, "url": "http://influxdb:8086"}},
    )
    runner = K6Runner(cfg)
    runner._outputs = {"json", "xk6-influxdb"}
    test = K6Test(id="smoke", script="k6/smoke.js", params=ScenarioParams(executor="constant-vus", vus=1, duration="5s"))
    cmd = runner.build_cmd(test, "rid", tmp_path)
    assert "--tag" in cmd
    assert "testid=rid" in cmd
    assert "run_id=rid" in cmd
    assert "--summary-export" in cmd
    assert not any(x.startswith("json=") for x in cmd)  # raw JSON off by default
    assert any("xk6-influxdb" in x for x in cmd)
    env = runner.env_for(test, "rid", tmp_path)
    assert env["K6_RUN_ID"] == "rid"
    assert env["BASE_URL"] == "http://t"


def test_k6_raw_json_metrics_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("K6_RAW_JSON_METRICS", "1")
    cfg = OrchestratorConfig(
        project=ProjectConfig(name="t"),
        target=TargetConfig(type="none", traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t")),
        maintenance={"enabled": False},
    )
    runner = K6Runner(cfg)
    runner._outputs = {"json"}
    cmd = runner.build_cmd(
        K6Test(id="smoke", script="k6/smoke.js", params=ScenarioParams(executor="constant-vus", vus=1, duration="5s")),
        "rid",
        tmp_path,
    )
    assert any(x.startswith("json=") for x in cmd)


def test_skips_missing_influx_extension(tmp_path):
    cfg = OrchestratorConfig(
        project=ProjectConfig(name="t"),
        target=TargetConfig(type="none", traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t")),
        maintenance={"enabled": False},
        storage={"influx": {"enabled": True, "url": "http://influxdb:8086"}},
    )
    runner = K6Runner(cfg)
    runner._outputs = {"json", "influxdb"}
    cmd = runner.build_cmd(
        K6Test(id="smoke", script="k6/smoke.js", params=ScenarioParams(executor="constant-vus", vus=1, duration="5s")),
        "rid",
        tmp_path,
    )
    assert not any("xk6-influxdb" in x for x in cmd)
