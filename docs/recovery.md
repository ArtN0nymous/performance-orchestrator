# Recovery

## `orchestrator recover <run-id>`

Loads the run from SQLite, SSHs `disable_maintenance`, verifies public live, writes `server/recovery-*.txt`, sets status to `completed` or leaves `recovery_required`.

## Maintenance TTL / watchdog

- Orchestrator stores `maintenance_deadline` on the run.
- Scheduler ticks call `recover_expired_maintenance()`.
- Lab target: `maintenance.sh enable <ttl>` starts a background loop on the **target** that deletes the flag when TTL expires — this still works if the orchestrator container is killed.

## Limitations (no remote systemd assumed)

If the target has no watchdog script, no cron, and no TTL helper, and the runner is destroyed **before** cleanup, maintenance can remain enabled until a human or `recover` runs. The platform cannot invent a supervisor on a host it does not control. Configure `commands.install_watchdog` for production (for example a user-level `systemd --user` timer, if allowed).

SIGINT/SIGTERM on the orchestrator attempt cleanup in `finally` before exit. `SIGKILL` cannot be handled; rely on TTL/watchdog.
