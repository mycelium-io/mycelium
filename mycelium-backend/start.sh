#!/bin/sh
set -e

echo "[startup] Running database migrations..."
python -m alembic upgrade head
echo "[startup] Migrations complete."

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
