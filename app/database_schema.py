import sqlite3

from app.constants import SCHEMA_MIGRATIONS


def initialize_database_schema(
    connection: sqlite3.Connection,
    *,
    migration_now_utc: str,
) -> None:
    connection.execute(
        """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                reminder_kind TEXT NOT NULL DEFAULT 'text',
                schedule_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                start_at TEXT NOT NULL,
                interval_days INTEGER,
                interval_weeks INTEGER,
                day_of_week TEXT,
                month_week_number INTEGER,
                month_day INTEGER,
                timezone TEXT,
                delete_after_two_days INTEGER NOT NULL DEFAULT 0,
                requires_completion INTEGER NOT NULL DEFAULT 0,
                repeat_interval_minutes INTEGER,
                revision INTEGER NOT NULL DEFAULT 1,
                delivery_tracking_started_at_utc TEXT,
                last_handled_scheduled_for_utc TEXT,
                client_request_id TEXT,
                client_request_hash TEXT,
                client_request_status TEXT,
                created_at TEXT NOT NULL
            )
            """
    )

    connection.execute(
        """
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                timezone TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
    )
    connection.execute(
        """
            CREATE TABLE IF NOT EXISTS weather_location_cache (
                location_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                admin1 TEXT,
                country TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
    )
    connection.execute(
        """
            CREATE TABLE IF NOT EXISTS weather_report_cache (
                reminder_id INTEGER NOT NULL,
                reminder_revision INTEGER NOT NULL,
                scheduled_for_utc TEXT NOT NULL,
                reminder_text TEXT NOT NULL,
                report_html TEXT NOT NULL,
                prepared_at_utc TEXT NOT NULL,
                PRIMARY KEY (reminder_id, scheduled_for_utc)
            )
            """
    )
    connection.execute(
        """
            CREATE TABLE IF NOT EXISTS reminder_completion_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reminder_id INTEGER NOT NULL,
                reminder_revision INTEGER NOT NULL DEFAULT 1,
                chat_id INTEGER NOT NULL,
                scheduled_for_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                rendered_text TEXT NOT NULL,
                current_message_id INTEGER,
                current_message_sent_at_utc TEXT,
                next_repeat_at_utc TEXT,
                repeat_attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                delivery_claim_token TEXT,
                delivery_claimed_at_utc TEXT,
                completed_at_utc TEXT,
                completed_by_user_id INTEGER,
                completed_by_display_name TEXT,
                completion_claim_token TEXT,
                completion_claimed_at_utc TEXT,
                completion_next_attempt_at_utc TEXT,
                completion_attempts INTEGER NOT NULL DEFAULT 0,
                completion_last_error TEXT,
                completion_delivery_status TEXT,
                completion_message_id INTEGER,
                completion_message_sent_at_utc TEXT,
                completion_callback_message_id INTEGER,
                completion_callback_message_sent_at_utc TEXT,
                superseded_at_utc TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                UNIQUE(reminder_id, reminder_revision, scheduled_for_utc)
            )
            """
    )
    connection.execute(
        """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_reminder_completion_occurrences_one_active
            ON reminder_completion_occurrences(reminder_id)
            WHERE status = 'active'
            """
    )
    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS
                idx_reminder_completion_occurrences_due
            ON reminder_completion_occurrences(status, next_repeat_at_utc, id)
            """
    )
    connection.execute(
        """
            CREATE TABLE IF NOT EXISTS reminder_delivery_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reminder_id INTEGER NOT NULL,
                reminder_revision INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                scheduled_for_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                delivery_attempts INTEGER NOT NULL DEFAULT 0,
                claim_token TEXT,
                claimed_at_utc TEXT,
                next_attempt_at_utc TEXT,
                last_error TEXT,
                message_id INTEGER,
                message_sent_at_utc TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                UNIQUE(reminder_id, reminder_revision, scheduled_for_utc)
            )
            """
    )
    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS idx_reminder_delivery_occurrences_due
            ON reminder_delivery_occurrences(
                status,
                next_attempt_at_utc,
                claimed_at_utc,
                id
            )
            """
    )
    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS idx_reminder_delivery_occurrences_retention
            ON reminder_delivery_occurrences(status, updated_at_utc, id)
            """
    )
    connection.execute(
        """
            CREATE TABLE IF NOT EXISTS reminder_message_deletion_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reminder_id INTEGER,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sent_at_utc TEXT NOT NULL,
                delete_at_utc TEXT NOT NULL,
                delete_attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at_utc TEXT NOT NULL,
                last_error TEXT,
                UNIQUE(chat_id, message_id)
            )
            """
    )
    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS
                idx_reminder_message_deletion_queue_next_attempt
            ON reminder_message_deletion_queue(next_attempt_at_utc, id)
            """
    )
    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS
                idx_reminder_message_deletion_queue_delete_at
            ON reminder_message_deletion_queue(delete_at_utc, id)
            """
    )
    weather_report_cache_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(weather_report_cache)"
        ).fetchall()
    }

    if "reminder_text" not in weather_report_cache_columns:
        connection.execute(
            """
                ALTER TABLE weather_report_cache
                ADD COLUMN reminder_text TEXT NOT NULL DEFAULT ''
                """
        )
        connection.execute("DELETE FROM weather_report_cache")

    if "reminder_revision" not in weather_report_cache_columns:
        connection.execute(
            """
                ALTER TABLE weather_report_cache
                ADD COLUMN reminder_revision INTEGER NOT NULL DEFAULT 0
                """
        )
        # Prepared reports are derived data. A legacy row cannot be tied
        # safely to the current reminder revision, so invalidate it.
        connection.execute("DELETE FROM weather_report_cache")

    # Legacy cache timestamps were naive local times and cannot be compared
    # safely with the UTC TTL. This table is derived data, so invalidate
    # only those legacy rows during the additive migration.
    connection.execute(
        """
            DELETE FROM weather_location_cache
            WHERE length(updated_at) <= 19
            """
    )
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(reminders)").fetchall()
    }

    for column_name, column_definition in SCHEMA_MIGRATIONS.items():
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE reminders ADD COLUMN {column_definition}")

    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS idx_reminders_active_weather
            ON reminders(id)
            WHERE status = 'active' AND reminder_kind = 'weather'
            """
    )

    connection.execute(
        """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reminders_client_request
            ON reminders(chat_id, client_request_id)
            WHERE client_request_id IS NOT NULL
            """
    )
    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS idx_reminders_chat_status
            ON reminders(chat_id, status, id)
            """
    )

    completion_occurrence_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(reminder_completion_occurrences)"
        ).fetchall()
    }
    if "reminder_revision" not in completion_occurrence_columns:
        connection.execute(
            """
                ALTER TABLE reminder_completion_occurrences
                ADD COLUMN reminder_revision INTEGER NOT NULL DEFAULT 1
                """
        )

    completion_migrations = {
        "completion_claim_token": "completion_claim_token TEXT",
        "completion_claimed_at_utc": "completion_claimed_at_utc TEXT",
        "completion_next_attempt_at_utc": ("completion_next_attempt_at_utc TEXT"),
        "completion_attempts": ("completion_attempts INTEGER NOT NULL DEFAULT 0"),
        "completion_last_error": "completion_last_error TEXT",
        "completion_delivery_status": "completion_delivery_status TEXT",
        "completion_message_id": "completion_message_id INTEGER",
        "completion_message_sent_at_utc": ("completion_message_sent_at_utc TEXT"),
        "completion_callback_message_id": ("completion_callback_message_id INTEGER"),
        "completion_callback_message_sent_at_utc": (
            "completion_callback_message_sent_at_utc TEXT"
        ),
    }
    for column_name, column_definition in completion_migrations.items():
        if column_name not in completion_occurrence_columns:
            connection.execute(
                "ALTER TABLE reminder_completion_occurrences "
                f"ADD COLUMN {column_definition}"
            )

    connection.execute(
        """
            CREATE INDEX IF NOT EXISTS
                idx_reminder_completion_occurrences_completion_due
            ON reminder_completion_occurrences(
                status,
                completion_next_attempt_at_utc,
                completion_claimed_at_utc,
                id
            )
            """
    )

    connection.execute(
        """
            UPDATE reminders
            SET delivery_tracking_started_at_utc = ?
            WHERE delivery_tracking_started_at_utc IS NULL
            """,
        (migration_now_utc,),
    )
