# Local development

The lab is **not** representative of production hardware. Default limits: target-app ~1 CPU / 1GB RAM, target-db ~0.5 CPU / 512MB RAM (override in `.env`).

## Bring-up

```bash
python3 -m pip install -e ".[dev]"
make test
cp .env.example .env
docker compose --profile local-target --profile observability up -d --build
docker compose exec orchestrator doctor
docker compose exec orchestrator run --suite smoke
```

Host ports: public target `18080`, test target `18088`, SSH `12222`, Grafana `3000`, Prometheus `9090`, Influx `8086`, payment-mock `8090`.

## Against an external local API (simulated remote server)

Use when your API runs in **another** Docker Compose stack. Join both to a shared network, enable SSH on the API app (stub toggle), and point the orchestrator via **`.env`** (`ORCHESTRATOR_PROJECT_DIR` = carpeta del overlay, fuera de este repo).

```bash
# 1) Shared network once
docker network create perf-loadtest

# 2) Start your API stack joined to perf-loadtest (with loadtest SSH if applicable)

# 3) In performance-orchestrator/.env set at least:
#    EXTERNAL_TARGET_NETWORK=perf-loadtest
#    TARGET_SSH_HOST=<api_app_container>
#    TARGET_SSH_USER=root
#    PUBLIC_BASE_URL=http://<api_nginx_container>
#    TEST_BASE_URL=http://<api_nginx_container>
#    HEALTH_PATH=/api/health
#    API_ACCESS_KEY=...
#    API_ADMIN_ACCESS_KEY=...

make ext-up
make ext-doctor
make ext-smoke
make ext-full
```

Compose files: `docker-compose.external-target.yml` + `docker-compose.host-data.yml`. Do not enable profile `local-target` at the same time.

### Docker Desktop “readonly database” / disk I/O errors

`make ext-up` bind-mounts orchestrator SQLite, k6 results, Prometheus, Influx and Grafana under `ORCHESTRATOR_HOST_DATA` on the **host** (default `/Volumes/Ramon/docker-data/performance-orchestrator`), not inside `Docker.raw`. That avoids the recurring read-only VM filesystem under load-test I/O.

Still required on this Mac:

1. Keep `/Volumes/Ramon` connected and awake during long runs (`caffeinate -dims` in a side terminal helps).
2. Free space on the **internal** SSD (Docker Desktop metadata still uses it; &lt;~20 Gi free is risky).
3. If the daemon itself reports `read-only file system` on `meta.db`, restart Docker Desktop once; if it keeps happening, reset the Docker disk image (Settings → Troubleshoot → Clean / Delete `Docker.raw`) — the bind-mounted host data survives.

## Profiles

| Profile | Services |
|---------|----------|
| (default) | orchestrator (scheduler) |
| `local-target` | target-nginx, target-app, target-db, payment-mock |
| `observability` | prometheus, influxdb, grafana, cadvisor |
| `chaos` | toxiproxy |

Example:

```bash
docker compose --profile local-target --profile observability --profile chaos up -d
```

## Unit tests without Docker

`make test` runs configuration, scheduler, state, safety, masking, report, k6 command builder, and the 15 failure-mode tests (mocked SSH/k6).
