# Reporting

Each run writes `/data/results/<run-id>/`:

- `manifest.json`, `summary.json`, `report.html`, `report.md`, `tests.csv`, `timeline.jsonl`, `resolved-config.yml`
- `tests/<test-id>/summary.json`, `metrics.json`, stdout/stderr
- `server/` connection, diagnostics, initial/final state, maintenance verify

HTML includes run id, suite, per-test status, duration, p50/p90/p95/p99, error rate, throughput, thresholds, resource peaks, timeline, failures, Grafana link.

InfluxDB and Grafana are optional. Local JSON/HTML remain the source of truth.

k6 tags every sample with `testid` and `run_id`.
