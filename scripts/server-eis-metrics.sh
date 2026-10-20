#!/usr/bin/env bash
# Sourced only; logger failures must not affect caller stdout/status/leases.
eis_metrics_python="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/server-eis-metrics.py"
eis_metrics_init() {
  eis_metrics_lane=$1
  eis_metrics_operation=$2
  eis_metrics_run=$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null) || eis_metrics_run=
  eis_metric dispatch_start
}
eis_metric() {
  [[ -n ${eis_metrics_run:-} ]] || return 0
  python3 "$eis_metrics_python" local-eis-supplier "$eis_metrics_lane" \
    "$eis_metrics_operation" "$eis_metrics_run" "$1" "${2:-}" "${3:-}" "${4:-}" \
    >/dev/null 2>&1 || true
  return 0
}
