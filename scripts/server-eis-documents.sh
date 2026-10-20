#!/usr/bin/env bash
# One document per run, serialized with all other official EIS intake.
set -euo pipefail
umask 077
# Optional observability must never become a worker prerequisite.
eis_metric() { :; }
eis_metrics_init() { :; }
eis_metrics_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd 2>/dev/null) || eis_metrics_dir=
if [[ -r "$eis_metrics_dir/server-eis-metrics.sh" ]]; then
  source "$eis_metrics_dir/server-eis-metrics.sh" >/dev/null 2>&1 || true
fi
eis_metrics_result=
eis_metrics_signal=
eis_metrics_work_active=0
marker_owned=0
lease_waiter=
eis_metrics_exit() {
  local saved=$?
  trap - EXIT
  if [[ -n "$lease_waiter" ]]; then
    kill "$lease_waiter" 2>/dev/null || true
    wait "$lease_waiter" 2>/dev/null || true
  fi
  if [[ "$marker_owned" == 1 ]]; then
    sudo -n docker exec vibe-seller-api-1 python -c \
      'from pathlib import Path; Path("/var/lib/eis-browser/eis-priority.request").unlink(missing_ok=True)' || true
  fi
  if [[ -z "$eis_metrics_result" ]]; then
    if [[ "$saved" == 0 ]]; then eis_metrics_result=SUCCESS; else eis_metrics_result=ERROR; fi
  fi
  eis_metric dispatch_finish "$eis_metrics_result" "$saved" "$eis_metrics_signal"
  return "$saved"
}
trap eis_metrics_exit EXIT
trap 'eis_metrics_signal=INT; eis_metrics_result=INTERRUPTED; exit 130' INT
trap 'eis_metrics_signal=TERM; eis_metrics_result=INTERRUPTED; exit 143' TERM
eis_metrics_init documents documents
# Do not stack minute-cron waiters behind the same atomic source window.
exec 7>/home/syurai/vibe-seller-state/eis-document-dispatch.lock
if ! flock -n 7; then
  eis_metrics_result=BUSY
  echo '{"status":"BLOCKED","reason":"DOCUMENT_DISPATCH_BUSY","attempted":0}'
  exit 75
fi
cd /home/syurai/vibe-seller
proxy_health=$(sudo -n docker inspect -f '{{.State.Health.Status}}' vibe-seller-eis-proxy-1)
if [[ "$proxy_health" != healthy ]]; then
  echo '{"status":"BLOCKED","reason":"PROXY_UNAVAILABLE","attempted":0}'
  exit 69
fi
# A cooldown retains the same family's turn; fixed minute parity could starve it.
router_dir=/home/syurai/vibe-seller-state/eis-documents/local-eis-supplier
mkdir -p "$router_dir"
chmod 700 "$router_dir"
family=44
if [[ -f "$router_dir/next-law" ]]; then read -r family < "$router_dir/next-law"; fi
if [[ "$family" != 44 && "$family" != 223 ]]; then
  echo '{"status":"BLOCKED","reason":"DOCUMENT_ROUTER_STATE_INVALID","attempted":0}'
  exit 65
fi
# Probe with the running image: no ephemeral worker/source I/O for an idle queue.
if ! probe=$(sudo -n docker exec vibe-seller-api-1 python -m procurement.eis_document_dispatch_cli \
  --company-id local-eis-supplier --preferred-law "$family"); then
  printf '%s\n' "$probe"
  exit 69
fi
if ! selected=$(printf '%s' "$probe" | python3 -c '
import json,sys
try:
    p=json.load(sys.stdin)
    if p.get("status")=="IDLE" and p.get("law") is None: print("IDLE")
    elif p.get("status")=="READY" and p.get("law") in {"44","223"}: print(p["law"])
    else: sys.exit(1)
except (ValueError,TypeError,AttributeError):sys.exit(1)
'); then
  echo '{"status":"BLOCKED","reason":"DOCUMENT_PROBE_INVALID","attempted":0}'
  exit 65
fi
if [[ "$selected" == IDLE ]]; then eis_metrics_result=IDLE; printf '%s\n' "$probe"; exit 0; fi
family=$selected
# The same lock as freshness/deploy owns the marker. Never remove another owner's
# hint, and let an already running freshness pass complete normally.
exec 8>/home/syurai/vibe-seller-state/eis-priority.lock
if ! flock -n 8; then
  eis_metrics_result=BUSY
  echo '{"status":"BLOCKED","reason":"PRIORITY_WORKER_BUSY","attempted":0}'
  exit 75
fi
marker_owned=1
sudo -n docker exec vibe-seller-api-1 python -c \
  'from pathlib import Path; Path("/var/lib/eis-browser/eis-priority.request").touch()'
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
wait_started=$SECONDS
eis_metric import_wait_start
flock -w 300 9 &
lease_waiter=$!
if ! wait "$lease_waiter"; then
  eis_metrics_result=TIMEOUT
  echo '{"status":"BLOCKED","reason":"SERVER_IMPORT_BUSY","attempted":0}'
  exit 75
fi
lease_waiter=
eis_metric import_acquired
lock_wait_seconds=$((SECONDS - wait_started))
eis_metric work_start
eis_metrics_work_active=1
if [[ "$family" == 223 ]]; then
  if output=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm --no-deps \
    -v /home/syurai/vibe-seller/scripts/server-eis-223-document-worker.py:/tmp/doc223.py:ro \
    worker python /tmp/doc223.py); then exit_code=0; else exit_code=$?; fi
else
  if output=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm --no-deps worker \
    python -m procurement.eis_documents_cli --company-id local-eis-supplier); then
    exit_code=0
  else exit_code=$?; fi
fi
if [[ "$exit_code" == 0 ]]; then work_result=SUCCESS; else work_result=ERROR; fi
eis_metric work_finish "$work_result" "$exit_code"
eis_metrics_work_active=0
printf '%s' "$output" | python3 -c '
import json,sys
try:
    p=json.load(sys.stdin)
    p["dispatch_law"]=sys.argv[1]
    p["source_lock_wait_seconds"]=int(sys.argv[2])
    print(json.dumps(p))
except (ValueError,TypeError,AttributeError):
    print(json.dumps({"status":"BLOCKED","reason":"DOCUMENT_WORKER_OUTPUT_INVALID","attempted":0}))
' "$family" "$lock_wait_seconds"
rotation=$(printf '%s' "$output" | python3 -c '
import json,sys
try:
    report=json.load(sys.stdin)
    known=report.get("status") in {"IDLE","PROCESSED","REANALYZED","BLOCKED","PARTIAL"}
    deferred=report.get("reason") in {"ROBOTS_CRAWL_DELAY","SOURCE_BUSY"}
    print("FLIP" if known and not deferred else "KEEP")
except (ValueError,TypeError,AttributeError):print("KEEP")
')
if [[ "$rotation" == FLIP ]]; then
  if [[ "$family" == 44 ]]; then next_family=223; else next_family=44; fi
  cursor=$(mktemp "$router_dir/.next-law.XXXXXX")
  printf '%s\n' "$next_family" > "$cursor"
  mv -f "$cursor" "$router_dir/next-law"
fi
exit "$exit_code"
