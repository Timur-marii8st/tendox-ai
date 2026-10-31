#!/usr/bin/env bash
# Bounded discovery; official recovery uses its separate source lease and guards.
set -euo pipefail
umask 077
repo=/home/syurai/vibe-seller
state=/home/syurai/vibe-seller-state/gosplan
cd "$repo"
if [[ ${1:-} == --offline-offset-prepare || ${1:-} == --offline-offset-activate ||
      ${1:-} == --offline-offset-page || ${1:-} == --offline-offset-null ]]; then
  if [[ $# != 2 || ! $2 =~ ^[a-f0-9]{64}$ || ! -f "$state/cycle.lock" ||
        -L "$state/cycle.lock" || ! -f "$state/offset-recovery-plan.json" ||
        -L "$state/offset-recovery-plan.json" ||
        ! -f /home/syurai/vibe-seller-state/eis-import.lock ||
        -L /home/syurai/vibe-seller-state/eis-import.lock ]]; then
    echo '{"status":"UNKNOWN","reason":"OFFSET_OFFLINE_INPUT_INVALID"}'
    exit 64
  fi
  lock_identity=$(stat -c '%d:%i' "$state/cycle.lock")
  import_identity=$(stat -c '%d:%i' /home/syurai/vibe-seller-state/eis-import.lock)
  case $1 in
    --offline-offset-prepare) offset_flag=--offset-prepare-sha256 ;;
    --offline-offset-activate) offset_flag=--offset-activate-sha256 ;;
    --offline-offset-page) offset_flag=--offset-reconcile-page-sha256 ;;
    --offline-offset-null) offset_flag=--offset-reconcile-null-sha256 ;;
  esac
  # The worker itself holds the same inode throughout the offline transaction.
  # Do not take the host lock here: a second open file description would deadlock.
  printf 'services:\n  worker:\n    network_mode: none\n' | \
    sudo -n docker compose -p vibe-seller -f docker-compose.server.yml \
    -f "$state/compose.yml" -f - run --rm -T --no-deps --entrypoint python \
    -e DATABASE_ADMIN_URL= -e DATABASE_URL= -e EIS_GETDOCS_IP_TOKEN= -e GOSPLAN_API_KEY= \
    -v "$state/cycle.lock:/run/gosplan/cycle.lock" \
    -v /home/syurai/vibe-seller-state/eis-import.lock:/run/gosplan/eis-import.lock \
    -v "$state/offset-recovery-plan.json:/run/gosplan/offset-recovery-plan.json:ro" \
    worker /app/gosplan/server-gosplan-resolve-legacy-hold.py "$offset_flag" "$2" \
    --lock-identity "$lock_identity" --import-lock-identity "$import_identity"
  exit $?
fi
exec 7>"$state/cycle.lock"
if ! flock -n 7; then
  echo '{"status":"UNKNOWN","reason":"CYCLE_BUSY"}'
  exit 75
fi
for law in 44 223; do
  if result=$(timeout 180 sudo -n docker compose -p vibe-seller -f docker-compose.server.yml \
    -f "$state/compose.yml" run --rm -T --no-deps --entrypoint python \
    -e DATABASE_ADMIN_URL= -e EIS_GETDOCS_IP_TOKEN= \
    -v "$state/key:/run/secrets/gosplan-key:ro" \
    worker /app/gosplan/server-gosplan-discovery.py --law "$law"); then
    printf '%s\n' "$result"
  else
    printf '%s\n' "$result"
    exit 1
  fi
  # The active split belongs to one law.  Do not query the other law or launch
  # official recovery while its global provider hold is still being resolved.
  if printf '%s' "$result" | python3 -c '
import json,sys
a=json.load(sys.stdin)
sys.exit(0 if a.get("status") == "UNKNOWN" and a.get("reason") == "OFFSET_RECOVERY" and a.get("candidate") is None else 1)
'; then
    exit 0
  fi
  if number=$(printf '%s' "$result" | python3 -c '
import json,re,sys
law=sys.argv[1]
a=json.load(sys.stdin)
n=a.get("candidate")
if a.get("status") != "STOPPED" or a.get("law") != law or a.get("recovery_eligible") is not True or not isinstance(n,str) or not re.fullmatch(r"\d{19}" if law == "44" else r"\d{11}",n):
 sys.exit(1)
print(n)
' "$law"); then
    # The wrapper repeats priority, capacity, budget and fresh-snapshot checks
    # under the shared import lease; the discovery result is advisory only.
    if ! "$state/server-gosplan-recovery.sh" --law "$law" --number "$number"; then
      printf '{"status":"UNKNOWN","reason":"RECOVERY_NOT_SYNCED","law":"%s"}\n' "$law"
    fi
  fi
done
