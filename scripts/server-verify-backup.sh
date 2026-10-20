#!/usr/bin/env bash
# Prove that the latest private backup restores to an isolated temporary DB.
set -euo pipefail
umask 077

cd /home/syurai/vibe-seller
name=procurement_restore_verify
backup=$(find /home/syurai/vibe-seller-state/backups -maxdepth 1 -type f \
  -name 'procurement-*.dump' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)
test -n "$backup"
existing=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d procurement -Atqc \
  "SELECT count(*) FROM pg_database WHERE datname = '$name'")
test "$existing" = 0
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  createdb -U procurement_owner "$name"
trap 'sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db dropdb -U procurement_owner procurement_restore_verify' EXIT
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  pg_restore -U procurement_owner -d "$name" --no-owner --exit-on-error < "$backup"
count=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d "$name" -Atqc 'SELECT count(*) FROM eis_notice_versions')
test "$count" -ge 1562
targets=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d "$name" -Atqc 'SELECT count(*) FROM eis_sync_targets')
document_jobs=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d "$name" -Atqc 'SELECT count(*) FROM eis_document_jobs')
document_blobs=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d "$name" -Atqc 'SELECT count(*) FROM eis_document_blobs')
bad_blobs=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d "$name" -Atqc \
  "SELECT count(*) FROM eis_document_blobs WHERE sha256 <> encode(sha256(content), 'hex') OR byte_count <> octet_length(content)")
bad_analyses=$(sudo -n docker compose -p vibe-seller -f docker-compose.server.yml exec -T db \
  psql -U procurement_owner -d "$name" -Atqc \
  "SELECT count(*) FROM eis_document_analyses WHERE payload->>'sha256' IS DISTINCT FROM sha256")
test "$bad_blobs" = 0
test "$bad_analyses" = 0
echo "BACKUP_RESTORE_OK versions=$count targets=$targets document_jobs=$document_jobs document_blobs=$document_blobs bad_blobs=$bad_blobs bad_analyses=$bad_analyses"
