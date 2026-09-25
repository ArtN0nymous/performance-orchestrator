# performance-orchestrator

Reusable platform for automated k6 performance tests. The core never embeds a customer’s URLs, users, or business rules. Those live in a project overlay (YAML + k6 scripts).

**Start here:** [Guía de uso paso a paso](docs/user-guide.md) (configuración, doctor, run, scheduler, checklist).

Pinned runtime: **Python 3.12.8**, **k6 v2.2.0**, **xk6-output-influxdb v0.7.0** (official k6 binary is used if the extension cannot build against k6 2.x).

## What it does

```
preflight → capture state → enable maintenance → verify public 503 AND test traffic live
→ run suite (k6) → diagnostics → disable maintenance → verify live → report
```

Cleanup always runs (`try/finally` + SIGINT/SIGTERM). `orchestrator recover <run-id>` exists for when the runner dies after maintenance is on. The lab target also has a **TTL watchdog** on the server so maintenance cannot stick forever if the orchestrator container disappears.

## Quick start (local lab)

```bash
cp .env.example .env
docker compose --profile local-target --profile observability up -d --build
docker compose exec orchestrator doctor
docker compose exec orchestrator run --suite smoke
```

Reports: Docker volume `orchestrator-data` → `/data/results/<run-id>/report.html`. Grafana: [http://localhost:3000](http://localhost:3000) (lab user/password from `.env.example`).

The local lab is for **platform** validation. It is not a production benchmark (see resource limits in `.env.example`).

## Weekend / scheduler mode

```bash
docker compose --profile local-target --profile observability up -d
# default container command is `scheduler` (in-process, not host cron)
```

Jobs are defined under `schedule.jobs` with IANA timezones (`zoneinfo`). Misfire policy is explicit: `skip` or `run`.

## CLI

```
orchestrator validate
orchestrator doctor
orchestrator list suites
orchestrator list runs
orchestrator run --suite smoke
orchestrator run --test smoke
orchestrator status <run-id>
orchestrator report <run-id>
orchestrator recover <run-id>
orchestrator scheduler
```



## Layout


| Path                     | Role                                                                                   |
| ------------------------ | -------------------------------------------------------------------------------------- |
| `src/orchestrator/`      | Platform core                                                                          |
| `examples/demo-project/` | Lab fixture overlay (Docker target)                                                    |
| `test-definitions/`      | Starting point for a new project overlay (copy it; do not commit customer suites here) |
| `docker/`                | Lab target, payment mock, Prometheus, Grafana                                          |




## Tests

```bash
python3 -m pip install -e ".[dev]"
make test
```



## Documentation

- **[Guía de uso (paso a paso)](docs/user-guide.md)**
- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [Local development](docs/local-development.md)
- [Deployment](docs/deployment.md)
- [Target integration](docs/target-integration.md)
- [Recovery](docs/recovery.md)
- [Security](docs/security.md)
- [Reporting](docs/reporting.md)

