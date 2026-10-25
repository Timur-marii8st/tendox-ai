#!/usr/bin/env bash
# Durable queue; one bounded worker at a time, shared with manual/daily imports.
set -euo pipefail
umask 077
if [[ ${1:-} == run ]]; then
  exec python3 "$(dirname -- "${BASH_SOURCE[0]}")/server-eis-corpus-run.py" "$@"
fi
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
  if [[ -z "$eis_metrics_result" ]]; then
    if [[ "$saved" == 0 ]]; then eis_metrics_result=SUCCESS; else eis_metrics_result=ERROR; fi
  fi
  eis_metric dispatch_finish "$eis_metrics_result" "$saved" "$eis_metrics_signal"
  return "$saved"
}
trap eis_metrics_exit EXIT
operation=${1:-unknown}
case "$operation" in run|plan|extend|status) ;; *) operation=unknown ;; esac
eis_metrics_init corpus "$operation"
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
eis_metric import_wait_start
if ! flock -n 9; then
  eis_metrics_result=BUSY
  echo '{"status":"BLOCKED","reason":"SERVER_IMPORT_BUSY","coverage":"UNKNOWN"}'
  exit 75
fi
eis_metric import_acquired
cd /home/syurai/vibe-seller
if [[ ${1:-} == run ]]; then
  proxy_health=$(sudo -n docker inspect -f '{{.State.Health.Status}}' vibe-seller-eis-proxy-1)
  if [[ "$proxy_health" != healthy ]]; then
    echo '{"status":"BLOCKED","reason":"PROXY_UNAVAILABLE","coverage":"UNKNOWN"}'
    exit 69
  fi
fi
eis_metric work_start
eis_metrics_work_active=1
if sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T --no-deps worker \
  python -m procurement.eis_corpus_cli "$@" \
  --priority-request /var/lib/eis-browser/eis-priority.request \
  --regional-request /var/lib/eis-browser/eis-223-refresh.request \
  --mandatory-fresh-first \
  --company-id local-eis-supplier --actor-id server-corpus-worker; then worker_exit=0; else worker_exit=$?; fi
if [[ "$worker_exit" == 0 ]]; then work_result=SUCCESS; else work_result=ERROR; fi
eis_metric work_finish "$work_result" "$worker_exit"
eis_metrics_work_active=0
exit "$worker_exit"
