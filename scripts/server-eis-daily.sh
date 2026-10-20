#!/usr/bin/env bash
# Завершённые даты двух проверенных типов 44-ФЗ; неизвестные дни остаются gaps.
set -uo pipefail
status=0
echo "DAILY_START $(date -u +%FT%TZ)"
for region in 50 77; do
  for document_type in epNotificationEF2020 epNotificationEZK2020; do
    if ! /home/syurai/vibe-seller/scripts/server-eis-run.sh "$region" \
      --recent-days 3 --utc-offset 3 --document-type "$document_type"; then
      status=2
    fi
  done
done
echo "DAILY_END $(date -u +%FT%TZ) status=$status"
exit "$status"
