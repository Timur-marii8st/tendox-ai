#!/usr/bin/env bash
# Offline source artifact and tenant READ ONLY snapshot; never print raw XML.
set -euo pipefail
umask 077
helper=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/server-eis-no-data-evidence-report.py
sudo -n docker exec -i vibe-seller-api-1 python - "$@" < "$helper"
