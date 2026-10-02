#!/usr/bin/env bash
# Creates the login the MCP Toolbox will use. Its password comes from .env, never from the repo.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v pw="$TOOLBOX_DB_PASSWORD" <<'SQL'
CREATE ROLE toolbox LOGIN PASSWORD :'pw';
SQL
