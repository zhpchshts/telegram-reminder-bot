#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/telegram-reminder-bot"
IMAGE_NAME="telegram-reminder-bot:latest"
CONTAINER_NAME="telegram-reminder-bot"

echo "Creating database backup..."
/opt/backup-telegram-reminder-bot.sh

echo "Updating code..."
cd "$PROJECT_DIR"
runuser -u reminderbot -- git pull --ff-only

echo "Building Docker image..."
docker compose build

echo "Running checks inside Docker image..."
docker run --rm -e BOT_TOKEN=dummy "$IMAGE_NAME" ruff format --check .
docker run --rm -e BOT_TOKEN=dummy "$IMAGE_NAME" ruff check .
docker run --rm -e BOT_TOKEN=dummy "$IMAGE_NAME" pytest

echo "Restarting Docker Compose service..."
docker compose up -d --force-recreate

echo "Docker Compose status:"
docker compose ps

echo "Container logs:"
sleep 5
docker logs --tail 80 "$CONTAINER_NAME"

echo "Deploy completed."