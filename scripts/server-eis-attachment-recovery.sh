#!/usr/bin/env bash
# Explicit obsolete-parser repair; never scheduled automatically.
set -euo pipefail
umask 077
action=${1:-status}
windows=${2:-3}
if [[ $# -gt 2 || ! "$windows" =~ ^[1-3]$ || ( "$action" != status && "$action" != run ) ]]; then
  echo '{"status":"BLOCKED","reason":"RECOVERY_ARGUMENT_INVALID","coverage":"UNKNOWN"}'
  exit 64
fi
cd /home/syurai/vibe-seller
if [[ "$action" == status ]]; then
  sudo -n docker exec vibe-seller-api-1 python -m procurement.eis_corpus_cli attachment-recovery-status \
    --company-id local-eis-supplier --actor-id server-attachment-recovery --max-windows "$windows"
  exit $?
fi
exec 8>/home/syurai/vibe-seller-state/eis-priority.lock
lease_waiter=
marker_owned=0
cleanup() {
  if [[ -n "$lease_waiter" ]]; then
    kill "$lease_waiter" 2>/dev/null || true
    wait "$lease_waiter" 2>/dev/null || true
  fi
  if [[ "$marker_owned" == 1 ]]; then
    sudo -n docker exec vibe-seller-api-1 python -c \
      'from pathlib import Path; Path("/var/lib/eis-browser/eis-priority.request").unlink(missing_ok=True)' || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
flock -w 300 8 &
lease_waiter=$!
if ! wait "$lease_waiter"; then
  echo '{"status":"BLOCKED","reason":"PRIORITY_WORKER_BUSY","coverage":"UNKNOWN"}'
  exit 75
fi
lease_waiter=
proxy_health=$(sudo -n docker inspect -f '{{.State.Health.Status}}' vibe-seller-eis-proxy-1)
if [[ "$proxy_health" != healthy ]]; then
  echo '{"status":"BLOCKED","reason":"PROXY_UNAVAILABLE","coverage":"UNKNOWN"}'
  exit 69
fi
marker_owned=1
sudo -n docker exec vibe-seller-api-1 python -c \
  'from pathlib import Path; Path("/var/lib/eis-browser/eis-priority.request").touch()'
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
flock -w 300 9 &
lease_waiter=$!
if ! wait "$lease_waiter"; then
  echo '{"status":"BLOCKED","reason":"SERVER_IMPORT_BUSY","coverage":"UNKNOWN"}'
  exit 75
fi
lease_waiter=
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T --no-deps worker \
  python -m procurement.eis_corpus_cli attachment-recovery --max-windows "$windows" \
  --max-seconds 600 --max-database-gib 100 --min-free-gib 40 \
  --company-id local-eis-supplier --actor-id server-attachment-recovery
