#!/bin/sh
# Maintenance flag used by nginx public vhost. Writable by user perf.
# Watchdog: if a TTL file is present and expired, disable maintenance even if the runner died.
set -eu
ACTION="${1:-status}"
FLAG=/shared/maintenance/flag
TTLFILE=/shared/maintenance/ttl

case "$ACTION" in
  enable)
    TTL="${2:-7200}"
    date +%s > "$FLAG"
    echo $(( $(date +%s) + TTL )) > "$TTLFILE"
    # simple watchdog loop in background
    (
      while [ -f "$TTLFILE" ]; do
        now=$(date +%s)
        exp=$(cat "$TTLFILE" 2>/dev/null || echo 0)
        if [ "$now" -ge "$exp" ]; then
          rm -f "$FLAG" "$TTLFILE"
          exit 0
        fi
        sleep 5
      done
    ) >/tmp/maintenance-watchdog.log 2>&1 &
    echo '{"maintenance":true}'
    ;;
  disable)
    rm -f "$FLAG" "$TTLFILE"
    echo '{"maintenance":false}'
    ;;
  status)
    if [ -f "$FLAG" ]; then echo '{"maintenance":true}'; else echo '{"maintenance":false}'; fi
    ;;
  diagnostics)
    echo "=== uptime ==="; uptime || true
    echo "=== mem ==="; free -m || true
    echo "=== disk ==="; df -h || true
    echo "=== maintenance ==="; [ -f "$FLAG" ] && echo on || echo off
    ;;
  *)
    echo "usage: maintenance.sh enable|disable|status|diagnostics [ttl]" >&2
    exit 2
    ;;
esac
