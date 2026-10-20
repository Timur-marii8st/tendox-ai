#!/usr/bin/env bash
# Retry a bounded completed-date plan; advance only after exact successful receipt.
set -euo pipefail
umask 077
exec 7>/home/syurai/vibe-seller-state/eis-corpus-planner.lock
if ! flock -n 7; then
  echo '{"status":"BLOCKED","reason":"PLANNER_BUSY","company_id":"local-eis-supplier","coverage":"UNKNOWN","source_requests":0}'
  exit 75
fi
helper=/home/syurai/vibe-seller/scripts/server-eis-corpus-plan-state.py
prepared=$(python3 "$helper" due) || { printf '%s\n' "$prepared"; exit 65; }
status=$(printf '%s' "$prepared" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
if [[ "$status" == IDLE ]]; then printf '%s\n' "$prepared"; exit 0; fi
read -r first_day last_day < <(printf '%s' "$prepared" | python3 -c 'import json,sys; v=json.load(sys.stdin); print(v["first_day"],v["last_day"])')
if output=$(/home/syurai/vibe-seller/scripts/server-eis-corpus.sh plan --regions all \
  --from-day "$first_day" --through-day "$last_day" \
  --document-types epNotificationEF2020 epNotificationEZK2020 epNotificationEOK2020 epNotificationCancel epNotificationCancelFailure); then
  python3 "$helper" complete "$prepared" "$output"
else
  saved=$?
  printf '%s\n' "$output"
  exit "$saved"
fi
