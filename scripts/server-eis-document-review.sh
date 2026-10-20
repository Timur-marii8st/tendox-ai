#!/usr/bin/env bash
# Exact internal review capture; source/corpus budgets remain unchanged.
set -euo pipefail
umask 077
cd /home/syurai/vibe-seller
[[ ${1:-} == prepare || ${1:-} == read ]]
if [[ $1 == prepare ]];then
 exec 9>/home/syurai/vibe-seller-state/eis-import.lock
 if ! flock -w 60 9;then echo '{"status":"BLOCKED","reason":"SERVER_IMPORT_BUSY","source_requests":0}';exit 75;fi
fi
timeout --signal=TERM --kill-after=10 60 sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T --no-deps worker python /app/scripts/server-eis-document-review.py "$@"
