#!/bin/sh
set -eu
mkdir -p /data/results /ssh
CONFIG="${ORCHESTRATOR_CONFIG:-/project/orchestrator.yml}"

if [ -f /keys/lab_ed25519 ]; then
  cp /keys/lab_ed25519 /data/lab_ed25519
  chmod 600 /data/lab_ed25519
fi

# Trust-on-first-use for TARGET_SSH_HOST, then StrictHostKeyChecking=yes.
# Hashed known_hosts entries do not contain the hostname plaintext, so we track
# the active host in a marker and refresh keys when the target changes.
if [ -n "${TARGET_SSH_HOST:-}" ]; then
  KH="${KNOWN_HOSTS_FILE:-/data/known_hosts}"
  MARKER="/data/known_hosts.target"
  WANT="${TARGET_SSH_HOST}:${TARGET_SSH_PORT:-22}"
  mkdir -p "$(dirname "$KH")"
  NEED_SCAN=1
  if [ -s "$KH" ] && [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$WANT" ]; then
    NEED_SCAN=0
  fi
  if [ "$NEED_SCAN" = "1" ]; then
    : >"$KH"
    for i in $(seq 1 30); do
      if ssh-keyscan -p "${TARGET_SSH_PORT:-22}" -H "$TARGET_SSH_HOST" >>"$KH" 2>/dev/null; then
        if [ -s "$KH" ]; then
          printf '%s\n' "$WANT" >"$MARKER"
          break
        fi
      fi
      sleep 2
    done
  fi
fi

if [ "${1:-}" = "scheduler" ] || [ "${1:-}" = "orchestrator" ]; then
  exec orchestrator --config "$CONFIG" scheduler
fi
exec orchestrator --config "$CONFIG" "$@"
