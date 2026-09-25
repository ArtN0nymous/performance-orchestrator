# Target integration

## Adapter interface

```
check_connection()
capture_state()
enable_maintenance()
verify_maintenance()
disable_maintenance()
verify_live()
collect_diagnostics()
```

### ssh_generic

Every remote action is a string in `target.commands`. Placeholders: `{ttl_seconds}`, `{deadline}`, `{secret}`, `{php_binary}`, `{artisan_path}`, `{remote_workdir}`.

No users, IPs, PHP versions, or unit names are hardcoded.

### laravel (optional)

Defaults to `{php} {artisan} down` / `up` but `down_command` / `up_command` override. Optional diagnostic commands: PHP-FPM, queue workers, nginx/apache, mysql — all over SSH as the configured (possibly unprivileged) user. If a command is not permitted, the diagnostic file records the error; the run still continues.

## Sample: Laravel stub window

Copy `test-definitions/` into an external project folder and adapt:

- Enable/disable an env stub flag (example: `EXTERNAL_API_STUB_ENABLED`) + `php artisan config:clear`
- Expect HTTP 200 on public and test URLs while the stub is on (API stays live)
- Configure health path, public read paths, and access-token header via env
- Prefer stub-live over `artisan down` unless your app has a verified traffic bypass
- Raise API rate limits before high-VU suites

Copy that directory, rename the project, and fill SSH / URL secrets. Do not put customer brand names into the shared generic examples.
