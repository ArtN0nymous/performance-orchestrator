# Deployment

## Manual (one-shot)

Point `ORCHESTRATOR_CONFIG` at a production overlay. Mount SSH identity **read-only**, a `known_hosts` file with the real host key, and `/data` as a persistent volume.

```bash
docker compose up -d orchestrator
docker compose exec orchestrator run --suite smoke
```

## Scheduled (weekend)

Default container command is `orchestrator scheduler`. It:

- uses `zoneinfo` / IANA timezones
- stores last fire times in SQLite
- applies misfire `skip` or `run`
- serializes runs with the SQLite lock
- recovers expired maintenance TTL on each tick

No host crontab is required.

## Production notes

- Do not use the lab ed25519 key.
- Populate `known_hosts` offline (`ssh-keyscan` from a trusted network, then mount the file). Lab entrypoint TOFU-scans only when the file is empty.
- Swap Stripe keys to `sk_test_` / `pk_test_` **on the server** before payment suites. Never load-test with live keys.
- Do not aim k6 at the CRM host.
- After the window: `orchestrator recover <run-id>` if status is `recovery_required`, then confirm `artisan up` / live health.

## Adding a new project

1. Copy `test-definitions/` or `examples/demo-project/`.
2. Fill `target.ssh` and `traffic` URLs.
3. Add flows under `k6/flows` and scenarios under `k6/scenarios`.
4. Mount the directory as `/project`.
5. Leave `src/orchestrator` unchanged.
