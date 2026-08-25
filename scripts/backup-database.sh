#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/telegram-reminder-bot"
BACKUP_DIR="/opt/telegram-reminder-bot-backups"
DB_FILE="$PROJECT_DIR/reminders.db"

if [ ! -f "$DB_FILE" ]; then
  echo "Database file not found: $DB_FILE"
  exit 0
fi

TIMESTAMP="$(date +'%Y-%m-%d_%H-%M-%S')"
BACKUP_FILE="$BACKUP_DIR/reminders_$TIMESTAMP.db"

sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'"

find "$BACKUP_DIR" -maxdepth 1 -name "reminders_*.db" -type f -mtime +14 -delete

echo "Backup created: $BACKUP_FILE"
