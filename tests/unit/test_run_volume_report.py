from pathlib import Path

from orchestrator.engine.runner import _db_count_delta, _traffic_totals
from orchestrator.lifecycle.ssh_generic import _normalize_row_counts, _try_json
from orchestrator.reporting.generate import generate_reports


class _FakeArtifacts:
    def __init__(self, root: Path):
        self.root = root
        self.timeline_path = root / "timeline.jsonl"
        self.timeline_path.write_text("", encoding="utf-8")

    def write_text(self, name: str, content: str) -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, name: str, payload) -> Path:
        import json

        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


def test_db_count_delta_and_traffic():
    delta = _db_count_delta({"a": 10, "b": 1}, {"a": 15, "b": 1, "c": 3})
    assert delta["delta"]["a"] == 5
    assert delta["delta"]["b"] == 0
    assert delta["delta"]["c"] == 3
    traffic = _traffic_totals(
        [
            {"stats": {"http_reqs": 100}},
            {"stats": {"http_reqs": 50.0}},
            {"stats": {}},
        ]
    )
    assert traffic["http_reqs"] == 150


def test_normalize_row_counts_from_mysql_json():
    assert _normalize_row_counts(_try_json('{"badge_transactions": 12, "x": "3"}')) == {
        "badge_transactions": 12,
        "x": 3,
    }
    assert _normalize_row_counts(_try_json('noise\n{"a": 1}\n')) == {"a": 1}


def test_report_includes_run_volume(tmp_path: Path):
    class Cfg:
        project = type("P", (), {"name": "figap", "timezone": "America/Mexico_City"})()
        environment = type("E", (), {"name": "load", "timezone": None})()
        monitoring = type("M", (), {"grafana_url": None})()
        schedule = type("S", (), {"timezone": "UTC"})()

        def timezone(self):
            return self.environment.timezone or self.project.timezone or self.schedule.timezone

    arts = _FakeArtifacts(tmp_path)
    paths = generate_reports(
        arts,
        {
            "id": "r1",
            "status": "completed",
            "suite": "full",
            "started_at": "2026-09-25T17:24:27.411621+00:00",
            "finished_at": "2026-09-25T19:34:22.285989+00:00",
        },
        [{"id": "health", "status": "passed", "duration": 1.2, "stats": {
            "http_reqs": 42, "p50": 5, "p90": 8, "p95": 10, "p99": 12,
            "error_rate": 0, "throughput": 20, "thresholds": [],
        }}],
        {"cpu": None, "memory": None, "disk": None, "load": None},
        Cfg(),
        traffic={"http_reqs": 42, "tests": 1},
        db_snapshot={
            "before": {"badge_transactions": 10},
            "after": {"badge_transactions": 18},
            "delta": {"badge_transactions": 8},
        },
    )
    html = Path(paths["html"]).read_text(encoding="utf-8")
    assert "Run volume" in html
    assert "Total HTTP requests" in html
    assert "badge_transactions" in html
    assert "America/Mexico_City" in html
    assert "2026-09-25 11:24:27" in html  # UTC-6
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "Total HTTP requests: 42" in md
    assert "Database rows" in md
    assert "Timezone: `America/Mexico_City`" in md


def test_format_timestamp_converts_zone():
    from orchestrator.reporting.generate import format_timestamp

    out = format_timestamp("2026-09-25T17:24:27+00:00", "America/Mexico_City")
    assert "2026-09-25 11:24:27" in out
    assert "America/Mexico_City" in out
