from __future__ import annotations

import json
from typing import Any

# Nested dict keys that are not scalar trend/rate fields in k6 summary-export.
_NON_VALUE_KEYS = frozenset({"thresholds", "type", "contains", "values"})


def _metric_values(summary: dict[str, Any], name: str) -> dict[str, Any]:
    """Return scalar stats for a metric.

    Supports both shapes:
    - Nested (JSON output / older): ``metrics.X.values.{avg,p(95),rate,...}``
    - Flat (``--summary-export``): ``metrics.X.{avg,p(95),value,rate,...}``
    """
    metrics = summary.get("metrics") or {}
    item = metrics.get(name) or {}
    if not isinstance(item, dict):
        return {}
    nested = item.get("values")
    if isinstance(nested, dict) and nested:
        return nested
    return {k: v for k, v in item.items() if k not in _NON_VALUE_KEYS and not isinstance(v, (dict, list))}


def metric_value(summary: dict[str, Any], name: str, stat: str) -> float | None:
    values = _metric_values(summary, name)
    if stat in values:
        try:
            return float(values[stat])
        except (TypeError, ValueError):
            return None
    return None


def extract_k6_stats(summary: dict[str, Any]) -> dict[str, Any]:
    duration = _metric_values(summary, "http_req_duration")
    reqs = _metric_values(summary, "http_reqs")
    failed = _metric_values(summary, "http_req_failed")
    # Trend medians: med or p(50). Rates: rate (Counter/Rate nested) or value (flat Rate).
    error_rate = failed.get("rate")
    if error_rate is None:
        error_rate = failed.get("value")
    return {
        "p50": duration.get("p(50)") if duration.get("p(50)") is not None else duration.get("med"),
        "p90": duration.get("p(90)"),
        "p95": duration.get("p(95)"),
        "p99": duration.get("p(99)"),
        "error_rate": error_rate,
        "throughput": reqs.get("rate"),
        "http_reqs": reqs.get("count"),
        "thresholds": _thresholds(summary),
    }


def _thresholds(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for name, body in (summary.get("metrics") or {}).items():
        if not isinstance(body, dict):
            continue
        th = body.get("thresholds") or {}
        for expr, result in th.items():
            if isinstance(result, dict):
                passed = result.get("ok", True)
                out.append({"metric": name, "threshold": expr, "ok": bool(passed)})
            else:
                out.append({"metric": name, "threshold": expr, "ok": bool(result)})
    return out


def load_json(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
