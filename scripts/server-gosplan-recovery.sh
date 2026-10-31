#!/usr/bin/env bash
# One official EIS source turn; the container retains the import lease itself.
set -euo pipefail
umask 077
repo=/home/syurai/vibe-seller
override=/home/syurai/vibe-seller-state/gosplan/compose.yml
priority_lock=/home/syurai/vibe-seller-state/eis-priority.lock
import_lock=/home/syurai/vibe-seller-state/eis-import.lock

if [[ ${1:-} != --priority-internal ]]; then
  # flock is a dedicated supervisor, not an fd held only by the launcher.
  exec flock -w 300 "$priority_lock" "$0" --priority-internal "$@"
fi
shift
cd "$repo"
if [[ ! -f "$import_lock" || -L "$import_lock" ]]; then
  echo '{"status":"UNKNOWN","reason":"IMPORT_LEASE_UNAVAILABLE"}'
  exit 75
fi
if [[ $(sudo -n docker inspect -f '{{.State.Health.Status}}' vibe-seller-eis-proxy-1) != healthy ]]; then
  echo '{"status":"UNKNOWN","reason":"PROXY_UNAVAILABLE"}'
  exit 69
fi
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
if ! sudo -n docker exec vibe-seller-api-1 python -c '
import os,sys
p="/var/lib/eis-browser/eis-priority.request"
fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as stream: stream.write(sys.argv[1])
' "$marker_id"; then
  echo '{"status":"UNKNOWN","reason":"PRIORITY_MARKER_BUSY"}'
  exit 75
fi
marker_owned=1
# The container locks the very same host inode. It keeps the lease even if the
# entire host launcher process group dies while the container keeps running.
# A stale priority marker after SIGKILL fails closed and needs reconciliation.
trap '' INT TERM
if ! sudo -n docker compose -p vibe-seller \
  -f docker-compose.server.yml -f "$override" run --rm -T --no-deps \
  -v "$import_lock:/run/eis-import.lock" \
  --entrypoint flock -e DATABASE_ADMIN_URL= -e GOSPLAN_IMPORT_LEASE_HELD=1 \
  -e EIS_RECONCILIATION_SHARE_ENABLED=1 worker -w 300 /run/eis-import.lock \
  python /app/gosplan/server-gosplan-recovery.py "$@"; then
  echo '{"status":"UNKNOWN","reason":"WORKER_OR_LEASE_FAILED"}'
  exit 1
fi
