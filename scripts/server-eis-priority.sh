#!/usr/bin/env bash
# Serialized freshness intent makes the backfill yield after its atomic window.
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
operation=fresh
[[ ${1:-} == --smoke ]] && operation=smoke
eis_metrics_init priority "$operation"
# Coalesce cron ticks while one freshness owner waits behind documents/deploy.
# No probe or marker belongs to us until the shared priority lock is acquired.
trap 'eis_metrics_signal=INT; eis_metrics_result=INTERRUPTED; exit 130' INT
trap 'eis_metrics_signal=TERM; eis_metrics_result=INTERRUPTED; exit 143' TERM
exec 7>/home/syurai/vibe-seller-state/eis-freshness-dispatch.lock
if ! flock -n 7; then
  eis_metrics_result=BUSY
  echo '{"status":"BLOCKED","reason":"FRESHNESS_DISPATCH_BUSY","coverage":"UNKNOWN"}'
  exit 75
fi
exec 8>/home/syurai/vibe-seller-state/eis-priority.lock
flock -w 300 8 &
lease_waiter=$!
if ! wait "$lease_waiter"; then
  eis_metrics_result=TIMEOUT
  echo '{"status":"BLOCKED","reason":"PRIORITY_LOCK_TIMEOUT","coverage":"UNKNOWN"}'
  exit 75
fi
lease_waiter=
cd /home/syurai/vibe-seller
regions=${EIS_FRESHNESS_REGIONS:-official}
urgent=1
# Custom CLI scope/budgets and --smoke bypass the default-scope probe. The
# worker still validates them under the import lock; never infer a false IDLE.
if [[ $# == 0 ]]; then
  probe=$(sudo -n docker exec vibe-seller-api-1 python -m procurement.eis_freshness_dispatch_cli \
    --company-id local-eis-supplier --regions "$regions" --checkpointed --mandatory-only) || { printf '%s\n' "$probe"; exit 69; }
  status=$(printf '%s' "$probe" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  if [[ "$status" != READY ]]; then
    case "$status" in
      IDLE) eis_metrics_result=IDLE ;;
      BLOCKED) eis_metrics_result=ERROR ;;
      *) eis_metrics_result=UNKNOWN ;;
    esac
    printf '%s\n' "$probe"
    exit 0
  fi
  # Older READY probes retain their original priority-marker contract.
  urgent=$(printf '%s' "$probe" | python3 -c 'import json,sys; print(int(json.load(sys.stdin).get("urgent_due", 1) > 0))')
fi
proxy_health=$(sudo -n docker inspect -f '{{.State.Health.Status}}' vibe-seller-eis-proxy-1)
if [[ "$proxy_health" != healthy ]]; then
  echo '{"status":"BLOCKED","reason":"PROXY_UNAVAILABLE","coverage":"UNKNOWN"}'
  exit 69
fi
if [[ "$urgent" == 1 ]]; then
  marker_owned=1
  sudo -n docker exec vibe-seller-api-1 python -c \
    'from pathlib import Path; Path("/var/lib/eis-browser/eis-priority.request").touch()'
fi
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
eis_metric import_wait_start
flock -w 300 9 &
lease_waiter=$!
if ! wait "$lease_waiter"; then
  eis_metrics_result=TIMEOUT
  echo '{"status":"BLOCKED","reason":"SERVER_IMPORT_BUSY","coverage":"UNKNOWN"}'
  exit 75
fi
lease_waiter=
trap - INT TERM
eis_metric import_acquired
if [[ ${1:-} == --smoke ]]; then
  eis_metric work_start
  eis_metrics_work_active=1
  if sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T --no-deps \
    -v /home/syurai/vibe-seller/scripts:/app/scripts:ro worker \
    python /app/scripts/server-eis-freshness-smoke.py; then worker_exit=0; else worker_exit=$?; fi
  if [[ "$worker_exit" == 0 ]]; then work_result=SUCCESS; else work_result=ERROR; fi
  eis_metric work_finish "$work_result" "$worker_exit"
  eis_metrics_work_active=0
  exit "$worker_exit"
fi
# Shared turns: twelve bounded180s44 turns plus six180s223 turns each hour.
eis_metric work_start
eis_metrics_work_active=1
if sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T --no-deps -e EIS_JOINT_BUDGET_ENABLED=1 worker \
  python -m procurement.eis_corpus_cli fresh --regions "$regions" \
  --checkpointed --mandatory-only --max-windows 60 --max-seconds 180 --max-database-gib 100 --min-free-gib 40 \
  --company-id local-eis-supplier --actor-id server-freshness-worker "$@"; then worker_exit=0; else worker_exit=$?; fi
if [[ "$worker_exit" == 0 ]]; then work_result=SUCCESS; else work_result=ERROR; fi
eis_metric work_finish "$work_result" "$worker_exit"
eis_metrics_work_active=0
exit "$worker_exit"
