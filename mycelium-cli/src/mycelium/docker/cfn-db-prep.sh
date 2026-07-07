#!/bin/bash
# CFN database preparation — runs on EVERY `up` (as the cfn-db-init one-shot
# service), unlike initdb/create-cfn-cp-db.sh which only runs on a fresh volume.
#
# It closes two upgrade-path gaps that crash the CFN stack when the postgres
# volume predates 2.0.0:
#
#   1. Databases missing. `docker-entrypoint-initdb.d` only runs on an empty
#      data dir, so an install that upgrades INTO the cfn profile never gets
#      cfn_mgmt / cfn_cp / ioc-graph-db created. We create them idempotently.
#
#   2. Incompatible python-era cfn_mgmt. The old python CFN mgmt-plane stamped
#      cfn_mgmt's alembic_version up to 0008 with a DIFFERENT schema that has no
#      `agent` table. The Go mgmt-plane shares the 0001..0008 revision numbers,
#      so alembic thinks it is caught up, jumps to 0009, and
#      `CREATE INDEX ... ON agent` crash-loops the container. cfn_mgmt holds
#      only control-plane metadata (workspaces / MAS / agents), which mycelium
#      re-provisions, so we reset it and let the Go mgmt-plane migrate cleanly.
#      (A fresh cfn_mgmt has no alembic_version yet, so this never fires on a
#      new install.)
set -euo pipefail

PGHOST="${CFN_DB_PREP_HOST:-mycelium-db}"
PGUSER="${CFN_DB_USER:-postgres}"
export PGPASSWORD="${MYCELIUM_DB_PASSWORD:-password}"
PSQL="psql -v ON_ERROR_STOP=1 -h ${PGHOST} -U ${PGUSER}"

echo "cfn-db-init: ensuring CFN databases exist on ${PGHOST}"
$PSQL -d postgres <<-'SQL'
    SELECT 'CREATE DATABASE cfn_mgmt'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cfn_mgmt')\gexec
    SELECT 'CREATE DATABASE cfn_cp'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cfn_cp')\gexec
    SELECT 'CREATE DATABASE "ioc-graph-db"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ioc-graph-db')\gexec
SQL
$PSQL -d "ioc-graph-db" -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# Reset an incompatible pre-2.0.0 cfn_mgmt: alembic_version present (migrated by
# some mgmt-plane) but the Go schema's `agent` table absent (python-era schema).
incompatible=$($PSQL -d cfn_mgmt -tAc "
    SELECT CASE
        WHEN to_regclass('public.alembic_version') IS NOT NULL
         AND to_regclass('public.agent') IS NULL
        THEN 1 ELSE 0 END")

if [ "${incompatible//[[:space:]]/}" = "1" ]; then
    ver=$($PSQL -d cfn_mgmt -tAc "SELECT version_num FROM alembic_version LIMIT 1" || echo "?")
    echo "cfn-db-init: cfn_mgmt is at a pre-2.0.0 (python CFN) schema" \
         "(alembic ${ver//[[:space:]]/}, no 'agent' table) — resetting so the Go" \
         "mgmt-plane can migrate from scratch. Control-plane metadata is recreatable."
    $PSQL -d postgres -c 'DROP DATABASE cfn_mgmt WITH (FORCE);'
    $PSQL -d postgres -c 'CREATE DATABASE cfn_mgmt;'
    echo "cfn-db-init: cfn_mgmt reset."
else
    echo "cfn-db-init: cfn_mgmt schema is compatible (or fresh); no reset needed."
fi

echo "cfn-db-init: done."
