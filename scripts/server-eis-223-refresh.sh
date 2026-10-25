#!/usr/bin/env bash
# All retained official selector codes, frozen waves, three notice and two event families.
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
      'from pathlib import Path; Path("/var/lib/eis-browser/eis-223-refresh.request").unlink(missing_ok=True)' || true
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
eis_metrics_init 223_refresh refresh
requested_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# One owner of the regional demand marker; do not stack cron waiters.
exec 7>/home/syurai/vibe-seller-state/eis-223-dispatch.lock
if ! flock -n 7; then
  eis_metrics_result=BUSY
  printf '{"status":"BLOCKED","reason":"REGIONAL_DISPATCH_BUSY","attempted":0,"checked_at":"%s"}\n' "$requested_at"
  exit 75
fi
cd /home/syurai/vibe-seller
if ! probe=$(sudo -n docker exec -i vibe-seller-api-1 python - --probe < scripts/server-eis-223-refresh.py); then
  echo '{"status":"BLOCKED","reason":"REGIONAL_PROBE_UNAVAILABLE","attempted":0}'
  exit 69
fi
if ! status=$(printf '%s' "$probe" | python3 -c '
import json,sys
try:
    p=json.load(sys.stdin)
    if p.get("status") not in {"READY","IDLE"} or p.get("source_requests") != 0: sys.exit(1)
    print(p["status"])
except (ValueError,TypeError,AttributeError): sys.exit(1)
'); then
  echo '{"status":"BLOCKED","reason":"REGIONAL_PROBE_INVALID","attempted":0}'
  exit 65
fi
if [[ "$status" == IDLE ]]; then eis_metrics_result=IDLE; printf '%s\n' "$probe"; exit 0; fi
if [[ $(sudo -n docker inspect -f '{{.State.Health.Status}}' vibe-seller-eis-proxy-1) != healthy ]]; then
  echo '{"status":"BLOCKED","reason":"PROXY_UNAVAILABLE","attempted":0}'
  exit 69
fi
# Older READY probes retain their original priority-marker contract.
urgent=$(printf '%s' "$probe" | python3 -c 'import json,sys; print(int(json.load(sys.stdin).get("urgent", True)))')
if [[ "$urgent" == 1 ]]; then
  marker_owned=1
  sudo -n docker exec vibe-seller-api-1 python -c \
    'from pathlib import Path; Path("/var/lib/eis-browser/eis-223-refresh.request").touch()'
fi
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
wait_started=$SECONDS
# wait is a shell builtin: TERM interrupts it and cleanup reaps our waiter.
eis_metric import_wait_start
flock -w 300 9 &
lease_waiter=$!
if ! wait "$lease_waiter"; then
  eis_metrics_result=TIMEOUT
  printf '{"status":"BLOCKED","reason":"SERVER_IMPORT_BUSY","attempted":0,"dispatch_requested_at":"%s","source_lock_wait_seconds":%d}\n' "$requested_at" "$((SECONDS - wait_started))"
  exit 75
fi
lease_waiter=
eis_metric import_acquired
lock_wait_seconds=$((SECONDS - wait_started))
lease_acquired_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
lease_started=$SECONDS
eis_metric work_start
eis_metrics_work_active=1
if output=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm --no-deps \
  -e EIS_223_REGIONAL_ENABLED=1 -e EIS_JOINT_BUDGET_ENABLED=1 \
  -v /home/syurai/vibe-seller/scripts/server-eis-223-refresh.py:/tmp/refresh223.py:ro \
  worker python /tmp/refresh223.py); then exit_code=0; else exit_code=$?; fi
if [[ "$exit_code" == 0 ]]; then work_result=SUCCESS; else work_result=ERROR; fi
eis_metric work_finish "$work_result" "$exit_code"
eis_metrics_work_active=0
printf '%s' "$output" | python3 -c '
import json,sys
try:
    p=json.load(sys.stdin)
    p["source_lock_wait_seconds"]=int(sys.argv[1])
    p["dispatch_requested_at"]=sys.argv[2]
    p["lease_acquired_at"]=sys.argv[3]
    p["worker_finished_at"]=sys.argv[4]
    p["lease_work_seconds"]=int(sys.argv[5])
    print(json.dumps(p))
except (ValueError,TypeError,AttributeError):
    print(json.dumps({"status":"BLOCKED","reason":"REGIONAL_WORKER_OUTPUT_INVALID","attempted":0}))
    sys.exit(65)
' "$lock_wait_seconds" "$requested_at" "$lease_acquired_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$((SECONDS - lease_started))"
exit "$exit_code"
