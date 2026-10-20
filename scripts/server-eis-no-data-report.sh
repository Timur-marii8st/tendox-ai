#!/usr/bin/env bash
# No source clients. Tenant/RLS credentials remain inside the API container.
set -euo pipefail
umask 077
helper=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/server-eis-no-data-report.py
sudo -n docker exec -i vibe-seller-api-1 python - "$@" < "$helper"
