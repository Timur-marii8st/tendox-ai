#!/usr/bin/env bash
# Operator-only, source-free READ ONLY snapshot. Raw responses stay private.
set -euo pipefail
umask 077
helper=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/server-eis-no-data-store-report.py
sudo -n docker exec -i vibe-seller-api-1 python - "$@" < "$helper"
