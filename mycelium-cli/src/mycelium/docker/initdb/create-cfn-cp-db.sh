#!/bin/bash
# Create the CFN databases required by ioc-cfn-mgmt-plane-svc.
# Runs automatically on first postgres startup (initdb hook).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE cfn_mgmt'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cfn_mgmt')\gexec

    SELECT 'CREATE DATABASE cfn_cp'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cfn_cp')\gexec
EOSQL
