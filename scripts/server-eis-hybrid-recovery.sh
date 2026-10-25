#!/usr/bin/env bash
set -euo pipefail
umask 077
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
# Bounded hybrid discovery shares existing source leases and quota accounting.
exec 8>/home/syurai/vibe-seller-state/eis-priority.lock
marker_id=$(cat /proc/sys/kernel/random/uuid)
marker_owned=0
cleanup() {
  if [[ "$marker_owned" == 1 ]]; then
    sudo -n docker exec vibe-seller-api-1 python -c '
import sys
from pathlib import Path
p=Path("/var/lib/eis-browser/eis-priority.request")
if not p.is_symlink() and p.is_file() and p.stat().st_size <= 64 and p.read_text() == sys.argv[1]:
 p.unlink()
' "$marker_id" || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! flock -w 300 8; then
  echo '{"status":"UNKNOWN","reason":"PRIORITY_WORKER_BUSY","soap_attempts":0,"coverage":"UNKNOWN"}'
  exit 75
fi
if [[ "$(sudo -n docker inspect -f '{{.State.Health.Status}}' vibe-seller-eis-proxy-1)" != healthy ]]; then
  echo '{"status":"UNKNOWN","reason":"PROXY_UNAVAILABLE","soap_attempts":0,"coverage":"UNKNOWN"}'
  exit 69
fi
if ! sudo -n docker exec vibe-seller-api-1 python -c '
import os,sys
p="/var/lib/eis-browser/eis-priority.request"
try:
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
except FileExistsError:
 raise SystemExit(75)
with os.fdopen(fd,"w") as stream:
 stream.write(sys.argv[1])
' "$marker_id"; then
  echo '{"status":"UNKNOWN","reason":"PRIORITY_MARKER_BUSY","soap_attempts":0,"coverage":"UNKNOWN"}'
  exit 75
fi
marker_owned=1
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
if ! flock -w 300 9; then
  echo '{"status":"UNKNOWN","reason":"SOURCE_BUSY","soap_attempts":0,"coverage":"UNKNOWN"}'
  exit 75
fi
entrypoint=/app/diagnostic/server-eis-hybrid-recovery.py
if [[ "${1:-}" == --all-active ]]; then
  entrypoint=/app/diagnostic/server-eis-active-sweep.py
  shift
fi
# Reuse worker limits/state/proxy and the same global import lease as ordinary lanes.
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T --no-deps --entrypoint python -e EIS_HYBRID_IMPORT_LEASE_HELD=1 -e EIS_RECONCILIATION_SHARE_ENABLED=1 -v "$repo/scripts:/app/diagnostic:ro" worker "$entrypoint" "$@"
