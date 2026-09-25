# Configuration

Root file: `orchestrator.yml` (path via `--config` or `ORCHESTRATOR_CONFIG`).

## Sections

- `project`, `environment` — name + IANA timezone
- `target` — `ssh_generic` | `laravel` | `none`
- `maintenance` — enabled, TTL seconds, optional secret, watchdog
- `health` — URLs, timeout, retries
- `monitoring` — Prometheus/Grafana; core works with `enabled: false`
- `storage` — SQLite, results dir, optional InfluxDB v2
- `safety` — max VUs, duration, error rate, CPU/memory abort
- `schedule` — timezone, jobs (`id`, `cron`, `suite`, `misfire: skip|run`)
- `suites`, `tests`

## Secrets

```yaml
token: ${API_TOKEN}
token_file: file:/run/secrets/api_token
optional: ${MAYBE:-}
```

Docker secrets named like the env var (lowercase file under `/run/secrets`) are also read.

## Safety vs k6

The engine rejects tests with `vus > safety.max_vus` or duration longer than `safety.max_test_duration` before k6 starts. During a run it samples Prometheus (if enabled) and can SIGINT k6.

## k6 environment injected

`K6_RUN_ID`, `TESTID`, `BASE_URL` (test), `PUBLIC_BASE_URL`, `VUS`, `DURATION`, `THRESHOLDS_JSON`, `EXECUTOR`, bypass headers, plus `extra:` map.

Do not put production VU counts in scenario templates. Put them in the project YAML for a specific window.
