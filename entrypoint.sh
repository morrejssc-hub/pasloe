#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting Pasloe server..."
exec uvicorn src.pasloe.app:app --host 0.0.0.0 --port 8000
