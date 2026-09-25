from orchestrator.reporting.metrics import extract_k6_stats, metric_value


def test_extract_k6_stats_flat_summary_export():
    """k6 --summary-export uses flat metric objects (no nested values)."""
    summary = {
        "metrics": {
            "http_req_duration": {
                "avg": 186.2,
                "med": 163.8,
                "p(90)": 315.3,
                "p(95)": 376.2,
                "p(99)": 500.0,
                "thresholds": {"p(95)<800": {"ok": True}},
            },
            "http_req_failed": {"passes": 100, "fails": 2, "value": 0.016},
            "http_reqs": {"count": 476413, "rate": 226.7},
        }
    }
    stats = extract_k6_stats(summary)
    assert stats["p50"] == 163.8
    assert stats["p90"] == 315.3
    assert stats["p95"] == 376.2
    assert stats["p99"] == 500.0
    assert stats["error_rate"] == 0.016
    assert stats["throughput"] == 226.7
    assert stats["http_reqs"] == 476413
    assert stats["thresholds"][0]["ok"] is True


def test_extract_k6_stats_nested_values():
    summary = {
        "metrics": {
            "http_req_duration": {"values": {"med": 10.0, "p(95)": 30.0, "p(90)": 20.0}},
            "http_req_failed": {"values": {"rate": 0.01}},
            "http_reqs": {"values": {"rate": 50.0, "count": 100}},
        }
    }
    stats = extract_k6_stats(summary)
    assert stats["p95"] == 30.0
    assert stats["error_rate"] == 0.01
    assert stats["throughput"] == 50.0
    assert metric_value(summary, "http_req_duration", "p(95)") == 30.0
