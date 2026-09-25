from pathlib import Path
from unittest.mock import patch

import yaml

from orchestrator.config.loader import load_config
from orchestrator.engine.runner import RunEngine
from orchestrator.k6.runner import K6Result
from orchestrator.lifecycle.base import LifecycleResult, TargetAdapter


class OkAdapter(TargetAdapter):
    def check_connection(self):
        return LifecycleResult(True, "ok")

    def capture_state(self):
        return LifecycleResult(True, "{}", {"os": "lab"})

    def enable_maintenance(self, *, ttl_seconds=None):
        return LifecycleResult(True, "on")

    def verify_maintenance(self):
        return LifecycleResult(True, "public=503 test=200", {"public": 503, "test": 200})

    def disable_maintenance(self):
        return LifecycleResult(True, "off")

    def verify_live(self):
        return LifecycleResult(True, "public=200")

    def collect_diagnostics(self):
        return LifecycleResult(True, "ok", {"web": "nginx"})


def test_vertical_slice_artifacts(tmp_path):
    cfg_path = tmp_path / "o.yml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "lab"},
                "target": {
                    "type": "none",
                    "traffic": {"public_base_url": "http://p", "test_base_url": "http://t", "health_path": "/health"},
                },
                "maintenance": {"enabled": True},
                "storage": {"sqlite_path": str(tmp_path / "o.db"), "results_dir": str(tmp_path / "results")},
                "suites": {"smoke": {"tests": ["smoke"]}},
                "tests": {
                    "smoke": {
                        "script": "s.js",
                        "params": {"executor": "constant-vus", "vus": 1, "duration": "1s"},
                    }
                },
            }
        )
    )
    engine = RunEngine(load_config(cfg_path))
    with patch("orchestrator.engine.runner.build_adapter", return_value=OkAdapter()):
        with patch.object(engine.k6, "run", return_value=K6Result(0, "", "", {"metrics": {}}, 0.4, False)):
            with patch("orchestrator.engine.runner._http_ok", return_value=True):
                run = engine.run_suite("smoke")
    assert run["status"] == "completed"
    root = Path(run["artifacts_dir"])
    for name in ("manifest.json", "summary.json", "report.html", "timeline.jsonl", "resolved-config.yml"):
        assert (root / name).exists()
    assert (root / "server" / "state-initial.json").exists()
    rec = engine.recover(run["id"])
    assert rec["status"] in {"completed", "recovery_required"}
