#!/usr/bin/env bash
# Tenant read-only diagnostic; credentials stay inside the API container.
set -euo pipefail
umask 077
helper=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/server-eis-ingestion-report.py
sudo -n docker exec -i vibe-seller-api-1 python - "$@" < "$helper"
