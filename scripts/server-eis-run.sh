#!/usr/bin/env bash
# Один серверный импорт; общий lock защищает оба выбранных региона.
set -euo pipefail
umask 077
region=${1:?region is required}
shift
[[ "$region" =~ ^[0-9]{1,2}$ ]]
exec 9>/home/syurai/vibe-seller-state/eis-import.lock
if ! flock -n 9; then
  echo '{"status":"BLOCKED","reason":"SERVER_IMPORT_BUSY","coverage":"UNKNOWN"}'
  exit 75
fi
cd /home/syurai/vibe-seller
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm worker \
  syurai-eis-backfill --company-id local-eis-supplier --actor-id server-worker \
  --region "$region" "$@"
