#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="${REMINDER_BOT_PROJECT_DIR:-/opt/telegram-reminder-bot}"
BACKUP_DIR="${REMINDER_BOT_BACKUP_DIR:-/opt/telegram-reminder-bot-backups}"
DB_FILE="${REMINDER_BOT_DB_FILE:-$PROJECT_DIR/data/reminders.db}"

if [ ! -f "$DB_FILE" ] || [ ! -s "$DB_FILE" ]; then
  echo "Database file is missing or empty: $DB_FILE" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required to create a verified database backup." >&2
  exit 1
fi

install -d -m 0700 "$BACKUP_DIR"

TIMESTAMP="$(date +'%Y-%m-%d_%H-%M-%S')"
BACKUP_FILE="$BACKUP_DIR/reminders_${TIMESTAMP}_$$.db"
TEMP_BACKUP_FILE="$(mktemp "$BACKUP_DIR/.reminders_$TIMESTAMP.XXXXXX")"

cleanup_temp_backup() {
  if [ -n "$TEMP_BACKUP_FILE" ] && [ -f "$TEMP_BACKUP_FILE" ]; then
    rm -f -- "$TEMP_BACKUP_FILE"
  fi
}
trap cleanup_temp_backup EXIT

sqlite3 "$DB_FILE" ".backup '$TEMP_BACKUP_FILE'"

if [ ! -s "$TEMP_BACKUP_FILE" ]; then
  echo "Backup file is empty: $TEMP_BACKUP_FILE" >&2
  exit 1
fi

INTEGRITY_RESULT="$(sqlite3 "$TEMP_BACKUP_FILE" "PRAGMA quick_check;")"
if [ "$INTEGRITY_RESULT" != "ok" ]; then
  echo "Backup integrity check failed: $TEMP_BACKUP_FILE" >&2
  exit 1
fi

REQUIRED_TABLE_COUNT="$(sqlite3 "$TEMP_BACKUP_FILE" \
  "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name IN ('reminders', 'chat_settings');")"
if [ "$REQUIRED_TABLE_COUNT" != "2" ]; then
  echo "Backup does not contain the required application tables." >&2
  exit 1
fi

mv -- "$TEMP_BACKUP_FILE" "$BACKUP_FILE"
TEMP_BACKUP_FILE=""
trap - EXIT

find "$BACKUP_DIR" -maxdepth 1 -name "reminders_*.db" -type f -mtime +14 -delete

echo "Backup created: $BACKUP_FILE"
