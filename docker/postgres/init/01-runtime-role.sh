#!/bin/sh
set -eu

if [ -z "${APP_DB_PASSWORD:-}" ]; then
  echo "APP_DB_PASSWORD is required" >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=db_name="$POSTGRES_DB" \
  --set=app_password="$APP_DB_PASSWORD" <<-'EOSQL'
DO $body$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'procurement_app') THEN
    CREATE ROLE procurement_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END
$body$;
ALTER ROLE procurement_app PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"db_name" TO procurement_app;
GRANT USAGE ON SCHEMA public TO procurement_app;
EOSQL
