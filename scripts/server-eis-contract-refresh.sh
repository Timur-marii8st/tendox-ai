#!/usr/bin/env bash
# One bounded contract job; preserve the installed importer priorities and quotas.
set -euo pipefail
umask 077
cd /home/syurai/vibe-seller
exec 8>/home/syurai/vibe-seller-state/eis-contract-dispatch.lock
flock -n 8 || exit 75
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
flock -w 30 9 || exit 75
job_name=vibe-seller-contract-history
job_owner=contract-history-managed-v1
job_pid=
# All cleanup runs while FD9 still owns the shared import lease. Only this exact
# labelled ephemeral worker is eligible; an unrelated name collision fails closed.
cleanup_job() {
  local owner listed
  if ! owner=$(sudo -n docker inspect --format '{{ index .Config.Labels "tendox.history.owner" }}' "$job_name" 2>/dev/null); then
    listed=$(sudo -n docker container ls --all --filter "name=^/${job_name}$" --format '{{.Names}}') || return 69
    [[ -z "$listed" ]] && return 0
    return 69
  fi
  [[ "$owner" == "$job_owner" ]] || return 65
  sudo -n docker stop --time 15 "$job_name" >/dev/null || {
    listed=$(sudo -n docker container ls --all --filter "name=^/${job_name}$" --format '{{.Names}}') || return 69
    [[ -z "$listed" ]] && return 0
    return 69
  }
  # --rm normally removes it after stop. Explicit removal is limited to our owned
  # stopped ephemeral container, with no volume deletion.
  if sudo -n docker inspect "$job_name" >/dev/null 2>&1; then
    sudo -n docker rm "$job_name" >/dev/null || return 69
  fi
}
finish() {
  local result=$?
  trap - EXIT INT TERM
  local cleanup_result
  # Stop and reap the only producer before the final engine-side reconciliation;
  # it can otherwise create a container after an earlier absence check.
  if [[ -n "$job_pid" ]]; then
    if [[ $(jobs -pr) == "$job_pid" ]]; then kill -TERM "$job_pid" 2>/dev/null || true; fi
    wait "$job_pid" 2>/dev/null || true
  fi
  while true; do
    if cleanup_job; then break; else cleanup_result=$?; fi
    result=$cleanup_result
    # A foreign name collision is not our container and is never modified.
    [[ "$cleanup_result" == 65 ]] && break
    # Engine uncertainty cannot release the shared lease while our job may live.
    # The pending ledger hold already keeps old financial observations UNKNOWN.
    sleep 2
  done
  exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# A previous client can have disappeared before --rm. Reconcile its exact owned
# container under the lease before starting another job.
cleanup_job
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml \
  -f /home/syurai/vibe-seller-state/eis-contract-history-runtime.yml \
  run --rm --no-deps -T --name "$job_name" \
  --label "tendox.history.owner=$job_owner" \
  -e EIS_CONTRACT_HOST_LEASE_HELD=1 \
  -v /home/syurai/vibe-seller/scripts/server-eis-contract-refresh.py:/tmp/contract-refresh.py:ro \
  worker python /tmp/contract-refresh.py "$@" &
job_pid=$!
wait "$job_pid"
