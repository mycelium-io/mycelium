#!/bin/bash
# Create the cfn_cp database required by ioc-cfn-svc.
# Runs automatically on first postgres:17-alpine startup.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE cfn_cp'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cfn_cp')\gexec
EOSQL
