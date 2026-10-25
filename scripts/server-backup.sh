#!/usr/bin/env bash
# Same scheduled entrypoint; creation, verification and retention share one lock.
set -euo pipefail
umask 077
exec python3 "$(dirname -- "${BASH_SOURCE[0]}")/server-backup.py"
