#!/bin/sh
set -e

# No database migrations — the store is markdown files + a local JSONL index
# (SLIM-native rebuild). The backend reindexes from the files on startup.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
