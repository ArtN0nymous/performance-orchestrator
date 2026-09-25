# Security

- Default SSH: `StrictHostKeyChecking=yes`. `no` is rejected by the client wrapper. `accept-new` is allowed only if you set it explicitly.
- Identity files are copied to `/data` with mode `600`. Mount sources read-only.
- Lab key `docker/target/ssh/lab_ed25519` is **lab-only**. Replace for any real server.
- Secrets: env, Docker secrets, `file:` — not image layers, not HTML reports (keys matching password/token/secret/authorization/api_key/stripe are redacted).
- k6 `BASE_URL` is the **test** URL. Payment scenarios talk to `payment-mock` / Stripe test keys only.
- Request header redaction is configurable via `redaction_keys`.
