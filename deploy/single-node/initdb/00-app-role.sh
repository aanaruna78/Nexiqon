#!/bin/bash
# First start only: extensions, and the application role. The application role does not own the
# tables, so FORCE ROW LEVEL SECURITY applies to it (ADR 0005).
set -euo pipefail
psql -v ON_ERROR_STOP=1 -v app_password="$NEXIQON_APP_DB_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE ROLE nexiqon_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE nexiqon TO nexiqon_app;
EOSQL
