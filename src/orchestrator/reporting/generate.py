from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jinja2 import Environment

from orchestrator.reporting.metrics import extract_k6_stats


def format_timestamp(value: Any, tz_name: str | None) -> str:
    """Render an ISO timestamp in the orchestrator report timezone (falls back to UTC)."""
    if value is None or value == "":
        return "—"
    text = str(value).strip()
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    zone_name = (tz_name or "UTC").strip() or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
        zone_name = "UTC"
    local = dt.astimezone(zone)
    # Include offset so the zone is obvious even when abbreviation is ambiguous.
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} {zone_name} (UTC{local.strftime('%z')})"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Run {{ run.id }}</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 24px; color: #102a43; background: #f0f4f8; }
    h1,h2 { color: #243b53; }
    .card { background: white; border-radius: 12px; padding: 16px 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #d9e2ec; font-size: 14px; vertical-align: top; }
    .ok { color: #147d64; font-weight: 600; }
    .fail { color: #ba2525; font-weight: 600; }
    .muted { color: #627d98; }
    code { background: #e4e7eb; padding: 2px 6px; border-radius: 4px; }
    .metric { display: flex; flex-direction: column; gap: 2px; line-height: 1.25; }
    .metric-round { font-size: 14px; font-variant-numeric: tabular-nums; font-weight: 600; color: #102a43; }
    .metric-exact { font-size: 11px; font-variant-numeric: tabular-nums; color: #829ab1; word-break: break-all; }
    .peaks { display: flex; flex-wrap: wrap; gap: 16px 28px; }
    .peak { min-width: 140px; }
    .peak-label { font-size: 12px; color: #627d98; margin-bottom: 2px; }
  </style>
</head>
<body>
  <h1>Performance run <code>{{ run.id }}</code></h1>
  <div class="card">
    <p><strong>Status:</strong> <span class="{{ 'ok' if run.status == 'completed' else 'fail' }}">{{ run.status }}</span></p>
    <p><strong>Suite:</strong> {{ run.suite or run.test }}</p>
    <p><strong>Project:</strong> {{ project }} / {{ environment }}</p>
    <p><strong>Started:</strong> {{ ts(run.started_at) }} &nbsp; <strong>Finished:</strong> {{ ts(run.finished_at) }}</p>
    <p class="muted">Timestamps shown in <code>{{ report_timezone }}</code> (orchestrator config).</p>
    {% if grafana_url %}<p><a href="{{ grafana_url }}">Open Grafana</a></p>{% endif %}
    {% if run.error %}<p class="fail">{{ run.error }}</p>{% endif %}
  </div>
  <div class="card">
    <h2>Tests</h2>
    <table>
      <thead>
        <tr>
          <th>Test</th><th>Status</th><th>Duration (s)</th>
          <th>p50 (ms)</th><th>p90 (ms)</th><th>p95 (ms)</th><th>p99 (ms)</th>
          <th>Error rate</th><th>Throughput (req/s)</th>
        </tr>
      </thead>
      <tbody>
      {% for t in tests %}
        <tr>
          <td>{{ t.id }}</td>
          <td class="{{ 'ok' if t.status == 'passed' else 'fail' }}">{{ t.status }}</td>
          <td>{{ metric_html(t.duration) }}</td>
          <td>{{ metric_html(t.stats.p50) }}</td>
          <td>{{ metric_html(t.stats.p90) }}</td>
          <td>{{ metric_html(t.stats.p95) }}</td>
          <td>{{ metric_html(t.stats.p99) }}</td>
          <td>{{ metric_html(t.stats.error_rate, as_percent=True) }}</td>
          <td>{{ metric_html(t.stats.throughput) }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Thresholds</h2>
    <table>
      <thead><tr><th>Test</th><th>Metric</th><th>Expression</th><th>Result</th></tr></thead>
      <tbody>
      {% for t in tests %}
        {% for th in t.stats.thresholds %}
          <tr>
            <td>{{ t.id }}</td><td>{{ th.metric }}</td><td><code>{{ th.threshold }}</code></td>
            <td class="{{ 'ok' if th.ok else 'fail' }}">{{ 'pass' if th.ok else 'fail' }}</td>
          </tr>
        {% endfor %}
      {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Server resource peaks</h2>
    <div class="peaks">
      <div class="peak">
        <div class="peak-label">CPU</div>
        {{ metric_html(peaks.cpu) }}
      </div>
      <div class="peak">
        <div class="peak-label">Memory</div>
        {{ metric_html(peaks.memory, as_bytes=True) }}
      </div>
      <div class="peak">
        <div class="peak-label">Disk</div>
        {{ metric_html(peaks.disk) }}
      </div>
      <div class="peak">
        <div class="peak-label">Load</div>
        {{ metric_html(peaks.load) }}
      </div>
    </div>
    <p class="muted">Values are Prometheus samples collected during the run when monitoring is enabled.</p>
  </div>
  <div class="card">
    <h2>Run volume</h2>
    <p><strong>Total HTTP requests (k6):</strong>
      {% if traffic and traffic.http_reqs is not none %}{{ metric_html(traffic.http_reqs) }}{% else %}<span class="muted">—</span>{% endif %}
      <span class="muted">(sum of http_reqs across tests)</span>
    </p>
    {% if db_snapshot and (db_snapshot.delta or db_snapshot.before or db_snapshot.after) %}
    <h3>Database rows (before → after)</h3>
    <p class="muted">Counts on the target before the window and after tests (before restore). Delta ≈ rows created by the run.</p>
    <table>
      <thead><tr><th>Table</th><th>Before</th><th>After</th><th>Delta</th></tr></thead>
      <tbody>
      {% for table in db_snapshot_tables %}
        <tr>
          <td><code>{{ table }}</code></td>
          <td>{{ metric_html(db_snapshot.before.get(table)) }}</td>
          <td>{{ metric_html(db_snapshot.after.get(table)) }}</td>
          <td>{{ metric_html(db_snapshot.delta.get(table)) }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="muted">No DB row counts (set <code>DB_SNAPSHOT_ENABLED=true</code> on the orchestrator and configure <code>database_row_counts</code>).</p>
    {% endif %}
  </div>
  <div class="card">
    <h2>Timeline</h2>
    <table>
      <thead><tr><th>Time</th><th>Event</th><th>Detail</th></tr></thead>
      <tbody>
      {% for ev in timeline %}
        <tr><td>{{ ts(ev.ts) }}</td><td>{{ ev.event }}</td><td class="muted">{{ ev.detail }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Failures</h2>
    {% if failures %}
      <ul>{% for f in failures %}<li class="fail">{{ f }}</li>{% endfor %}</ul>
    {% else %}
      <p class="ok">No recorded failures.</p>
    {% endif %}
  </div>
</body>
</html>
"""


def _exact_str(num: float) -> str:
    """Full-precision display without scientific notation for typical metric ranges."""
    text = format(num, ".15g")
    if "e" in text.lower():
        text = format(num, ".15f").rstrip("0").rstrip(".")
    return text


def format_metric_html(
    value: Any,
    *,
    as_percent: bool = False,
    as_bytes: bool = False,
) -> str:
    """Rounded (≤2 decimals) primary + exact value in smaller muted text."""
    if value is None:
        return '<span class="muted">—</span>'
    try:
        num = float(value)
    except (TypeError, ValueError):
        return f'<span class="metric-round">{value}</span>'

    if as_bytes:
        mib = num / (1024 * 1024)
        rounded = f"{mib:.2f} MiB"
        exact = f"{_exact_str(num)} B"
    elif as_percent:
        rounded = f"{num * 100:.2f}%"
        exact = _exact_str(num)
    else:
        rounded = f"{num:.2f}"
        exact = _exact_str(num)

    return (
        f'<span class="metric">'
        f'<span class="metric-round">{rounded}</span>'
        f'<span class="metric-exact">{exact}</span>'
        f"</span>"
    )


def format_metric_text(value: Any, *, as_percent: bool = False, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if as_percent:
        return f"{num * 100:.{digits}f}%"
    return f"{num:.{digits}f}"


def _parse_timeline(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def generate_reports(
    artifacts,
    run: dict,
    tests: list[dict],
    peaks: dict,
    cfg,
    *,
    traffic: dict | None = None,
    db_snapshot: dict | None = None,
) -> dict[str, str]:
    timeline = _parse_timeline(artifacts.timeline_path)
    failures = [t["error"] for t in tests if t.get("error")]
    if run.get("error"):
        failures.append(run["error"])
    traffic = traffic or _traffic_from_tests(tests)
    db_snapshot = db_snapshot or {}
    db_tables = sorted(
        set((db_snapshot.get("before") or {}))
        | set((db_snapshot.get("after") or {}))
        | set((db_snapshot.get("delta") or {}))
    )
    report_timezone = cfg.timezone()
    context = {
        "run": run,
        "project": cfg.project.name,
        "environment": cfg.environment.name,
        "grafana_url": cfg.monitoring.grafana_url,
        "tests": tests,
        "peaks": peaks or {},
        "timeline": timeline,
        "failures": failures,
        "traffic": traffic,
        "db_snapshot": db_snapshot,
        "db_snapshot_tables": db_tables,
        "report_timezone": report_timezone,
    }
    env = Environment(autoescape=False)
    env.globals["metric_html"] = format_metric_html
    env.globals["ts"] = lambda value: format_timestamp(value, report_timezone)
    html = env.from_string(HTML_TEMPLATE).render(**context)
    artifacts.write_text("report.html", html)
    payload = {
        "run": run,
        "tests": tests,
        "peaks": peaks,
        "timeline": timeline,
        "failures": failures,
        "traffic": traffic,
        "db_snapshot": db_snapshot,
        "report_timezone": report_timezone,
    }
    artifacts.write_json("summary.json", payload)
    md = [
        f"# Run `{run.get('id')}`",
        "",
        f"- Status: **{run.get('status')}**",
        f"- Suite: {run.get('suite') or run.get('test')}",
        f"- Timezone: `{report_timezone}`",
        f"- Started: {format_timestamp(run.get('started_at'), report_timezone)}",
        f"- Finished: {format_timestamp(run.get('finished_at'), report_timezone)}",
        f"- Total HTTP requests: {format_metric_text(traffic.get('http_reqs'))}",
        "",
        "## Tests",
        "",
        "| Test | Status | p95 (ms) | Error rate | Throughput (req/s) | HTTP reqs |",
        "|---|---|---|---|---|---|",
    ]
    for t in tests:
        s = t.get("stats") or {}
        md.append(
            "| {id} | {status} | {p95} | {err} | {rps} | {reqs} |".format(
                id=t.get("id"),
                status=t.get("status"),
                p95=format_metric_text(s.get("p95")),
                err=format_metric_text(s.get("error_rate"), as_percent=True),
                rps=format_metric_text(s.get("throughput")),
                reqs=format_metric_text(s.get("http_reqs"), digits=0) if s.get("http_reqs") is not None else "—",
            )
        )
    if db_tables:
        md += ["", "## Database rows (before → after)", "", "| Table | Before | After | Delta |", "|---|---|---|---|"]
        for table in db_tables:
            md.append(
                "| {t} | {b} | {a} | {d} |".format(
                    t=table,
                    b=format_metric_text((db_snapshot.get("before") or {}).get(table), digits=0),
                    a=format_metric_text((db_snapshot.get("after") or {}).get(table), digits=0),
                    d=format_metric_text((db_snapshot.get("delta") or {}).get(table), digits=0),
                )
            )
    if failures:
        md += ["", "## Failures", ""] + [f"- {f}" for f in failures]
    artifacts.write_text("report.md", "\n".join(md) + "\n")
    csv_path = artifacts.root / "tests.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "status", "p50", "p90", "p95", "p99", "error_rate", "throughput", "http_reqs", "duration"],
        )
        writer.writeheader()
        for t in tests:
            s = t.get("stats") or {}
            writer.writerow(
                {
                    "id": t.get("id"),
                    "status": t.get("status"),
                    "p50": s.get("p50"),
                    "p90": s.get("p90"),
                    "p95": s.get("p95"),
                    "p99": s.get("p99"),
                    "error_rate": s.get("error_rate"),
                    "throughput": s.get("throughput"),
                    "http_reqs": s.get("http_reqs"),
                    "duration": t.get("duration"),
                }
            )
    return {
        "html": str(artifacts.root / "report.html"),
        "json": str(artifacts.root / "summary.json"),
        "markdown": str(artifacts.root / "report.md"),
        "csv": str(csv_path),
    }


def _traffic_from_tests(tests: list[dict]) -> dict:
    http_reqs = 0
    for t in tests:
        n = (t.get("stats") or {}).get("http_reqs")
        if isinstance(n, (int, float)):
            http_reqs += int(n)
    return {"http_reqs": http_reqs, "tests": len(tests)}


def stats_from_summary(summary: dict) -> dict:
    return extract_k6_stats(summary or {})
