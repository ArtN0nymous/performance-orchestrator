# Hardware metrics (CPU / RAM) for capacity reports

The HTML report includes **Server resource peaks** when monitoring is enabled.
Those peaks are sampled from **Prometheus** during each run (not from Influx/Grafana).

## Local Docker (rehearsal)

Stack started by `make ext-up`:

| Component | Role |
|-----------|------|
| **docker-stats-exporter** | CPU/memory per container via Docker API (works on Docker Desktop Mac) |
| **cAdvisor** | Extra container metrics (best on Linux hosts) |
| **Prometheus** | Scrapes exporters; orchestrator queries peaks into the report |
| **Grafana / Influx** | Optional live charts — not required for HTML peaks |

Overlay queries (`.env`):

```env
MONITORING_ENABLED=true
PROMETHEUS_URL=http://prometheus:9090
PROM_CPU_QUERY=docker_container_cpu_cores{name=~".*figap_api_app.*"}
PROM_MEMORY_QUERY=docker_container_memory_working_set_bytes{name=~".*figap_api_app.*"}
```

**Config note:** PromQL contains `{}`. Set `PROM_*` as full values in `.env` —
do not embed them as `${VAR:-default_with_braces}` (Compose and the secret
resolver cut at the first `}`).

## Production (API server)

Mirror the same idea on the real host:

1. Run **node_exporter** (or the cloud metrics agent) on the API server.
2. Run **Prometheus** (orchestrator host or monitoring VM) scraping that exporter.
3. Point the overlay at that Prometheus:

```text
PROM_CPU_QUERY=100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)
PROM_MEMORY_QUERY=node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes
```

4. Keep `MONITORING_ENABLED=true` so peaks land in `report.html`.

You do **not** need Prometheus inside the Laravel app — only an exporter on the
machine under test, and a Prometheus the orchestrator can reach.

## Verify

```bash
unset HEALTH_PATH   # avoid stale shell overrides of .env
make ext-up
make ext-doctor
# expect: [ok] prometheus http://prometheus:9090
curl -s 'http://localhost:9101/metrics' | grep figap_api_app
curl -sG 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=docker_container_memory_working_set_bytes{name=~".*figap_api_app.*"}'
```
