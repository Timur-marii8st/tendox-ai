#!/usr/bin/env bash
# Private, verified PostgreSQL snapshot for the server installation.
set -euo pipefail
umask 077

project=/home/syurai/vibe-seller
backup_dir=/home/syurai/vibe-seller-state/backups
mkdir -p "$backup_dir"
cd "$project"
database_size=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d procurement -Atqc 'SELECT pg_database_size(current_database())')
available=$(df -B1 --output=avail "$backup_dir" | tail -n 1 | tr -d '[:space:]')
[[ "$database_size" =~ ^[0-9]+$ && "$available" =~ ^[0-9]+$ ]]
if (( available < database_size + 40 * 1024 * 1024 * 1024 )); then
  echo 'BACKUP_BLOCKED DISK_RESERVE_REACHED'
  exit 75
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
temporary=$(mktemp "$backup_dir/.procurement-${stamp}.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT

sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  pg_dump -U procurement_owner -d procurement -Fc --no-owner > "$temporary"
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  pg_restore -l < "$temporary" > /dev/null
mv -- "$temporary" "$backup_dir/procurement-${stamp}.dump"
trap - EXIT
echo "BACKUP_OK $(date -u +%FT%TZ)"
