#!/usr/bin/env bash
set -euo pipefail
umask 077
# One diagnostic public navigation shares the existing import lease and cooldown.
helper=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/server-eis-no-data-public-check.py
flock -w 30 /home/syurai/vibe-seller-state/eis-import.lock sudo -n docker exec -i vibe-seller-api-1 python - "$@" < "$helper"
