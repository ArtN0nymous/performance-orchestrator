# Architecture

```
                    +------------------+
                    |  orchestrator    |
                    |  CLI / scheduler |
                    +--+-----+---------+
                       |     |
              SQLite   |     | OpenSSH (StrictHostKeyChecking=yes)
              /data    |     v
                       |  +--+------------------+
                       |  | target adapter      |
                       |  | ssh_generic|laravel |
                       |  +----------+----------+
                       |             | artisan down / flag file / stub env
                       v             v
              results/<run-id>/   public URL 503  OR  API live (stub)
              k6 summary+json     test URL still 200
                       |
          optional     v
     Prometheus <--- safety abort
     InfluxDB   <--- k6 --out xk6-influxdb
     Grafana
```

## Separation of concerns

1. **Core** (`src/orchestrator`) — CLI, engine, scheduler, SSH, safety, reports.
2. **Target definition** — `target:` YAML (host, user, commands, traffic split).
3. **k6 scenarios** — `k6/scenarios/` executors (`constant-vus`, `ramping-vus`, `constant-arrival-rate`, `per-vu-iterations`, `shared-iterations`). `externally-controlled` is rejected.
4. **Flows** — `k6/flows/` reusable HTTP sequences.
5. **Thresholds** — per-test YAML, injected as `THRESHOLDS_JSON`.
6. **Suites** — ordered test lists, `continue_on_failure`, `depends_on`.
7. **Secrets** — `${ENV}`, `file:` paths, Docker `/run/secrets`. Never baked into the image.

A new project is a new overlay directory + `ORCHESTRATOR_CONFIG`. No core fork.

## Run states

`scheduled → preparing → maintenance → running → collecting → cleanup → completed`
Failures: `failed`, `aborted`, `recovery_required`. SQLite lock enforces `max_concurrent_runs` (default 1).

## Traffic split

k6 **always** uses `traffic.test_base_url`. Public users use `traffic.public_base_url`.
`verify_maintenance()` refuses to start k6 if the test URL looks like maintenance (503/502).

Two supported window styles:

1. **Hard maintenance (public 503):** distinct test URL or a real bypass so k6 is not 503-only.
2. **Stub-live (API stays 200):** CRM/push isolated via env flag; same public/test URL is allowed when `public_expect_status_when_maintenance` is 2xx.

Lab implementation: nginx `:80` returns 503 when the maintenance flag file exists; `:8088` always proxies the app.

Laravel note: vanilla `PreventRequestsDuringMaintenance` does not honor a custom header unless you add it. Prefer a second vhost, secret cookie/path, or stub-live mode.

## Payments / stub window

Lab: sandbox `payment-mock` + fixture `/payments` scenarios.

A project overlay (external directory, not this repo) typically:

- Toggle `EXTERNAL_API_STUB_ENABLED` (or your equivalent) via SSH `.env` + `config:clear`
- Access-token header name is configurable (`ACCESS_TOKEN_HEADER`)
- Payment-provider test credentials remain a server-side ops swap (`sk_test_` / etc.)
- Default expectation while “in maintenance”: HTTP 200 on public and test URLs
