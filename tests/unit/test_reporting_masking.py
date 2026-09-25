from pathlib import Path

from orchestrator.artifacts.store import ArtifactStore
from orchestrator.config.models import OrchestratorConfig, ProjectConfig, TargetConfig, TrafficConfig
from orchestrator.reporting.generate import generate_reports
from orchestrator.safety.masking import redact


def test_masking():
    data = {"token": "supersecret", "nested": {"password": "pw"}, "ok": "visible"}
    out = redact(data)
    assert out["token"] == "****"
    assert out["nested"]["password"] == "****"
    assert out["ok"] == "visible"
    assert "Bearer ****" in redact("Authorization Bearer abcdef")


def test_html_report(tmp_path):
    arts = ArtifactStore(str(tmp_path), "run1")
    arts.timeline("preflight", ts="t0", detail="ok")
    cfg = OrchestratorConfig(
        project=ProjectConfig(name="demo"),
        target=TargetConfig(type="none", traffic=TrafficConfig(public_base_url="http://p", test_base_url="http://t")),
        maintenance={"enabled": False},
    )
    generate_reports(
        arts,
        {"id": "run1", "status": "completed", "suite": "smoke", "started_at": "a", "finished_at": "b"},
        [
            {
                "id": "smoke",
                "status": "passed",
                "duration": 1.23456,
                "stats": {
                    "p50": 10,
                    "p90": 20,
                    "p95": 376.2362694,
                    "p99": 40,
                    "error_rate": 0.016204427670949366,
                    "throughput": 226.76203940975128,
                    "thresholds": [{"metric": "http_req_failed", "threshold": "rate<0.1", "ok": True}],
                },
            }
        ],
        {"cpu": 1, "memory": 2, "disk": 3, "load": 4},
        cfg,
    )
    html = (Path(tmp_path) / "run1" / "report.html").read_text()
    assert "run1" in html
    assert "p95" in html
    assert "smoke" in html
    assert 'class="metric-round"' in html
    assert 'class="metric-exact"' in html
    assert "376.24" in html
    assert "1.62%" in html
    assert (Path(tmp_path) / "run1" / "report.md").exists()
    assert (Path(tmp_path) / "run1" / "tests.csv").exists()
