#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "==> Pulling latest code..."
git pull origin main

echo "==> Building images..."
docker compose build --no-cache frontend
docker compose build backend celery celery-beat

echo "==> Restarting services..."
docker compose up -d --force-recreate frontend backend celery celery-beat

echo "==> Running DB migrations..."
docker compose exec backend alembic upgrade head

echo "==> Done. Status:"
docker compose ps
