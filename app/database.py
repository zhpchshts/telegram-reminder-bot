import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import DB_PATH
from app.constants import (
    MAX_ACTIVE_REMINDERS_PER_CHAT,
    MESSAGE_DELETION_DELAY,
    REMINDER_COLUMNS,
    REMINDER_KIND_TEXT,
    SCHEMA_MIGRATIONS,
)

UTC = timezone.utc
WEATHER_LOCATION_CACHE_RETENTION = timedelta(days=30)


class ActiveReminderLimitError(ValueError):
    pass


class ReminderIdempotencyConflictError(ValueError):
    pass


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
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
                connection.execute(
                    f"ALTER TABLE reminders ADD COLUMN {column_definition}"
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
            "completion_callback_message_id": (
                "completion_callback_message_id INTEGER"
            ),
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

        migration_now_utc = format_utc_datetime(datetime.now(timezone.utc))
        connection.execute(
            """
            UPDATE reminders
            SET delivery_tracking_started_at_utc = ?
            WHERE delivery_tracking_started_at_utc IS NULL
            """,
            (migration_now_utc,),
        )


def _cancel_pending_reminder_delivery_occurrences(
    connection: sqlite3.Connection,
    *,
    reminder_id: int,
    now_utc: str,
) -> None:
    connection.execute(
        """
        UPDATE reminder_delivery_occurrences
        SET status = 'cancelled', claim_token = NULL, claimed_at_utc = NULL,
            next_attempt_at_utc = NULL, updated_at_utc = ?
        WHERE reminder_id = ? AND status = 'pending'
        """,
        (now_utc, reminder_id),
    )


def _delete_prepared_weather_reports_for_reminder(
    connection: sqlite3.Connection,
    *,
    reminder_id: int,
) -> None:
    connection.execute(
        "DELETE FROM weather_report_cache WHERE reminder_id = ?",
        (reminder_id,),
    )


def _create_reminder_in_db(
    *,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str = REMINDER_KIND_TEXT,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone: str | None = None,
    delete_after_two_days: bool = False,
    requires_completion: bool = False,
    repeat_interval_minutes: int | None = None,
    client_request_id: str | None = None,
    client_request_hash: str | None = None,
) -> tuple[int, bool, str | None]:
    now = datetime.now().isoformat(timespec="seconds")
    delivery_tracking_started_at_utc = format_utc_datetime(datetime.now(UTC))

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        if client_request_id is not None:
            existing = connection.execute(
                """
                SELECT id, client_request_hash, client_request_status
                FROM reminders
                WHERE chat_id = ? AND client_request_id = ?
                """,
                (chat_id, client_request_id),
            ).fetchone()
            if existing is not None:
                if existing["client_request_hash"] != client_request_hash:
                    raise ReminderIdempotencyConflictError(
                        "Ключ повторного запроса уже использован для других данных."
                    )
                return (
                    int(existing["id"]),
                    False,
                    (
                        str(existing["client_request_status"])
                        if existing["client_request_status"] is not None
                        else None
                    ),
                )

        active_count = connection.execute(
            """
            SELECT COUNT(*) AS active_count
            FROM reminders
            WHERE chat_id = ? AND status = 'active'
            """,
            (chat_id,),
        ).fetchone()
        if int(active_count["active_count"]) >= MAX_ACTIVE_REMINDERS_PER_CHAT:
            raise ActiveReminderLimitError(
                "Достигнут лимит активных напоминаний для этого чата."
            )

        cursor = connection.execute(
            """
            INSERT INTO reminders (
                chat_id,
                text,
                reminder_kind,
                schedule_type,
                status,
                start_at,
                interval_days,
                interval_weeks,
                day_of_week,
                month_week_number,
                month_day,
                timezone,
                delete_after_two_days,
                requires_completion,
                repeat_interval_minutes,
                revision,
                delivery_tracking_started_at_utc,
                last_handled_scheduled_for_utc,
                client_request_id,
                client_request_hash,
                client_request_status,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, NULL,
                ?, ?, ?, ?
            )
            """,
            (
                chat_id,
                reminder_text,
                reminder_kind,
                schedule_type,
                "active",
                start_at.isoformat(timespec="seconds"),
                interval_days,
                interval_weeks,
                day_of_week,
                month_week_number,
                month_day,
                timezone,
                int(delete_after_two_days),
                int(requires_completion),
                repeat_interval_minutes if requires_completion else None,
                delivery_tracking_started_at_utc,
                client_request_id,
                client_request_hash,
                "pending" if client_request_id is not None else None,
                now,
            ),
        )

        return (
            int(cursor.lastrowid),
            True,
            "pending" if client_request_id is not None else None,
        )


def create_reminder_in_db(
    *,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str = REMINDER_KIND_TEXT,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone: str | None = None,
    delete_after_two_days: bool = False,
    requires_completion: bool = False,
    repeat_interval_minutes: int | None = None,
) -> int:
    reminder_id, _was_created, _request_status = _create_reminder_in_db(
        chat_id=chat_id,
        reminder_text=reminder_text,
        reminder_kind=reminder_kind,
        schedule_type=schedule_type,
        start_at=start_at,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
        month_day=month_day,
        timezone=timezone,
        delete_after_two_days=delete_after_two_days,
        requires_completion=requires_completion,
        repeat_interval_minutes=repeat_interval_minutes,
    )
    return reminder_id


def create_reminder_idempotently_in_db(
    *,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str = REMINDER_KIND_TEXT,
    schedule_type: str,
    start_at: datetime,
    client_request_id: str,
    client_request_hash: str,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone: str | None = None,
    delete_after_two_days: bool = False,
    requires_completion: bool = False,
    repeat_interval_minutes: int | None = None,
) -> tuple[int, bool, str | None]:
    return _create_reminder_in_db(
        chat_id=chat_id,
        reminder_text=reminder_text,
        reminder_kind=reminder_kind,
        schedule_type=schedule_type,
        start_at=start_at,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
        month_day=month_day,
        timezone=timezone,
        delete_after_two_days=delete_after_two_days,
        requires_completion=requires_completion,
        repeat_interval_minutes=repeat_interval_minutes,
        client_request_id=client_request_id,
        client_request_hash=client_request_hash,
    )


def get_reminder_idempotency_record(
    *,
    chat_id: int,
    client_request_id: str,
    client_request_hash: str,
) -> dict[str, Any] | None:
    with get_connection() as connection:
        existing = connection.execute(
            """
            SELECT id, client_request_hash, client_request_status,
                   status AS reminder_status, revision
            FROM reminders
            WHERE chat_id = ? AND client_request_id = ?
            """,
            (chat_id, client_request_id),
        ).fetchone()

    if existing is None:
        return None
    if existing["client_request_hash"] != client_request_hash:
        raise ReminderIdempotencyConflictError(
            "Ключ повторного запроса уже использован для других данных."
        )
    return {
        "id": int(existing["id"]),
        "client_request_status": existing["client_request_status"],
        "reminder_status": str(existing["reminder_status"]),
        "revision": int(existing["revision"]),
    }


def mark_reminder_idempotency_succeeded(
    *,
    reminder_id: int,
    client_request_id: str,
) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE reminders
            SET client_request_status = 'succeeded'
            WHERE id = ? AND client_request_id = ?
              AND status = 'active'
              AND client_request_status = 'pending'
            """,
            (reminder_id, client_request_id),
        )
    return cursor.rowcount == 1


def delete_terminal_reminder_delivery_occurrences(
    *,
    expired_before: datetime,
    limit: int,
) -> int:
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    expired_before_utc = format_utc_datetime(expired_before)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM reminder_delivery_occurrences
            WHERE id IN (
                SELECT id
                FROM reminder_delivery_occurrences
                WHERE status IN ('sent', 'skipped', 'failed', 'cancelled')
                  AND updated_at_utc < ?
                ORDER BY updated_at_utc, id
                LIMIT ?
            )
            """,
            (expired_before_utc, limit),
        )
    return cursor.rowcount


def update_reminder_in_db(
    *,
    reminder_id: int,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str = REMINDER_KIND_TEXT,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone: str | None = None,
    delete_after_two_days: bool = False,
    requires_completion: bool = False,
    repeat_interval_minutes: int | None = None,
    expected_revision: int | None = None,
) -> bool:
    delivery_tracking_started_at_utc = format_utc_datetime(datetime.now(UTC))

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE reminders
            SET
                text = ?,
                reminder_kind = ?,
                schedule_type = ?,
                start_at = ?,
                interval_days = ?,
                interval_weeks = ?,
                day_of_week = ?,
                month_week_number = ?,
                month_day = ?,
                timezone = ?,
                delete_after_two_days = ?,
                requires_completion = ?,
                repeat_interval_minutes = ?,
                revision = revision + 1,
                delivery_tracking_started_at_utc = ?,
                last_handled_scheduled_for_utc = NULL
            WHERE id = ? AND chat_id = ? AND status = 'active'
              AND (? IS NULL OR revision = ?)
            """,
            (
                reminder_text,
                reminder_kind,
                schedule_type,
                start_at.isoformat(timespec="seconds"),
                interval_days,
                interval_weeks,
                day_of_week,
                month_week_number,
                month_day,
                timezone,
                int(delete_after_two_days),
                int(requires_completion),
                repeat_interval_minutes if requires_completion else None,
                delivery_tracking_started_at_utc,
                reminder_id,
                chat_id,
                expected_revision,
                expected_revision,
            ),
        )
        if cursor.rowcount > 0:
            now_utc = format_utc_datetime(datetime.now(UTC))
            _delete_prepared_weather_reports_for_reminder(
                connection,
                reminder_id=reminder_id,
            )
            _cancel_pending_reminder_delivery_occurrences(
                connection,
                reminder_id=reminder_id,
                now_utc=now_utc,
            )
            _enqueue_cancelled_completion_checkpoints(
                connection,
                reminder_id=reminder_id,
                now=datetime.fromisoformat(now_utc),
            )
            connection.execute(
                """
                UPDATE reminder_completion_occurrences
                SET
                    status = 'cancelled',
                    next_repeat_at_utc = NULL,
                    delivery_claim_token = NULL,
                    delivery_claimed_at_utc = NULL,
                    completion_claim_token = NULL,
                    completion_claimed_at_utc = NULL,
                    completion_next_attempt_at_utc = NULL,
                    updated_at_utc = ?
                WHERE reminder_id = ?
                  AND status IN ('pending', 'active', 'completing')
                """,
                (now_utc, reminder_id),
            )

    return cursor.rowcount > 0


def fetch_active_reminders(
    where_sql: str = "",
    params: tuple[Any, ...] = (),
) -> list[sqlite3.Row]:
    query = f"""
        SELECT {REMINDER_COLUMNS}
        FROM reminders
        WHERE status = 'active'
        {where_sql}
        ORDER BY id ASC
    """

    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def get_active_reminder_from_db(reminder_id: int) -> sqlite3.Row | None:
    reminders = fetch_active_reminders("AND id = ?", (reminder_id,))
    return reminders[0] if reminders else None


def get_active_reminder_for_chat(
    reminder_id: int,
    chat_id: int,
) -> sqlite3.Row | None:
    reminders = fetch_active_reminders(
        "AND id = ? AND chat_id = ?",
        (reminder_id, chat_id),
    )

    return reminders[0] if reminders else None


def get_active_reminders_for_chat(chat_id: int) -> list[sqlite3.Row]:
    return fetch_active_reminders("AND chat_id = ?", (chat_id,))


def get_all_active_reminders() -> list[sqlite3.Row]:
    return fetch_active_reminders()


def count_active_chats() -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT chat_id) AS active_chats_count
            FROM reminders
            WHERE status = 'active'
            """
        ).fetchone()

    return int(row["active_chats_count"])


def set_reminder_status(reminder_id: int, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE reminders
            SET status = ?
            WHERE id = ?
            """,
            (status, reminder_id),
        )


def mark_reminder_as_deleted(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "deleted")


def clear_reminder_idempotency_key(reminder_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE reminders
            SET client_request_id = NULL,
                client_request_hash = NULL,
                client_request_status = NULL
            WHERE id = ?
            """,
            (reminder_id,),
        )


def mark_reminder_as_missed(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "missed")


def mark_reminder_occurrence_handled(
    reminder_id: int,
    scheduled_for_utc: datetime,
    *,
    final_status: str | None = None,
    expected_revision: int | None = None,
) -> bool:
    if final_status not in {None, "sent", "missed"}:
        raise ValueError("final_status must be 'sent', 'missed', or None.")

    scheduled_for = format_utc_datetime(scheduled_for_utc)

    revision_clause = "" if expected_revision is None else "AND revision = ?"
    params: tuple[Any, ...] = (
        scheduled_for,
        final_status,
        reminder_id,
        scheduled_for,
    )
    if expected_revision is not None:
        params += (expected_revision,)

    with get_connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE reminders
            SET
                last_handled_scheduled_for_utc = ?,
                status = COALESCE(?, status)
            WHERE id = ?
              AND status = 'active'
              AND (
                  last_handled_scheduled_for_utc IS NULL
                  OR last_handled_scheduled_for_utc < ?
              )
              {revision_clause}
            """,
            params,
        )

    return cursor.rowcount > 0


def get_reminder_occurrence_handling_state(
    reminder_id: int,
    scheduled_for_utc: datetime,
) -> str:
    scheduled_for = scheduled_for_utc.astimezone(timezone.utc)

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT status, last_handled_scheduled_for_utc
            FROM reminders
            WHERE id = ?
            """,
            (reminder_id,),
        ).fetchone()

    if row is None:
        return "missing"

    last_handled_raw = row["last_handled_scheduled_for_utc"]
    if last_handled_raw is not None:
        last_handled = datetime.fromisoformat(str(last_handled_raw))
        if (
            last_handled.tzinfo is None
            or last_handled.tzinfo.utcoffset(last_handled) is None
        ):
            last_handled = last_handled.replace(tzinfo=timezone.utc)

        if last_handled.astimezone(timezone.utc) >= scheduled_for:
            return "already_handled"

    if row["status"] != "active":
        return "inactive"

    return "unhandled"


def get_chat_timezone(chat_id: int) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT timezone
            FROM chat_settings
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()

    if not row:
        return None

    return str(row["timezone"])


def set_chat_timezone(chat_id: int, timezone: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_settings (
                chat_id,
                timezone,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                timezone = excluded.timezone,
                updated_at = excluded.updated_at
            """,
            (
                chat_id,
                timezone,
                now,
                now,
            ),
        )


def get_cached_weather_location(location_key: str) -> dict[str, Any] | None:
    fresh_since = format_utc_datetime(
        datetime.now(UTC) - WEATHER_LOCATION_CACHE_RETENTION
    )
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT name, admin1, country, latitude, longitude
            FROM weather_location_cache
            WHERE location_key = ? AND updated_at >= ?
            """,
            (location_key, fresh_since),
        ).fetchone()

    return dict(row) if row else None


def save_cached_weather_location(
    location_key: str,
    location: dict[str, Any],
) -> None:
    now = format_utc_datetime(datetime.now(UTC))

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO weather_location_cache (
                location_key,
                name,
                admin1,
                country,
                latitude,
                longitude,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_key) DO UPDATE SET
                name = excluded.name,
                admin1 = excluded.admin1,
                country = excluded.country,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                updated_at = excluded.updated_at
            """,
            (
                location_key,
                str(location.get("name") or "Населённый пункт"),
                location.get("admin1"),
                location.get("country"),
                float(location["latitude"]),
                float(location["longitude"]),
                now,
            ),
        )


def get_prepared_weather_report(
    reminder_id: int,
    reminder_revision: int,
    reminder_text: str,
    earliest_scheduled_for: datetime,
    latest_scheduled_for: datetime,
) -> dict[str, str] | None:
    earliest_scheduled_for_utc = format_utc_datetime(earliest_scheduled_for)
    latest_scheduled_for_utc = format_utc_datetime(latest_scheduled_for)

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT cache.scheduled_for_utc, cache.report_html
            FROM weather_report_cache AS cache
            JOIN reminders AS reminder ON reminder.id = cache.reminder_id
            WHERE cache.reminder_id = ?
              AND cache.reminder_revision = ?
              AND reminder.revision = ?
              AND reminder.status = 'active'
              AND cache.reminder_text = ?
              AND cache.scheduled_for_utc >= ?
              AND cache.scheduled_for_utc <= ?
            ORDER BY cache.scheduled_for_utc DESC
            LIMIT 1
            """,
            (
                reminder_id,
                reminder_revision,
                reminder_revision,
                reminder_text,
                earliest_scheduled_for_utc,
                latest_scheduled_for_utc,
            ),
        ).fetchone()

    if row is None:
        return None

    return {
        "scheduled_for_utc": str(row["scheduled_for_utc"]),
        "report_html": str(row["report_html"]),
    }


def delete_expired_weather_location_cache(
    *,
    expired_before: datetime,
    limit: int,
) -> int:
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    expired_before_utc = format_utc_datetime(expired_before)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM weather_location_cache
            WHERE location_key IN (
                SELECT location_key
                FROM weather_location_cache
                WHERE updated_at < ?
                ORDER BY updated_at, location_key
                LIMIT ?
            )
            """,
            (expired_before_utc, limit),
        )
    return cursor.rowcount


def save_prepared_weather_report(
    reminder_id: int,
    reminder_revision: int,
    scheduled_for: datetime,
    reminder_text: str,
    report_html: str,
) -> bool:
    scheduled_for_utc = format_utc_datetime(scheduled_for)
    prepared_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            INSERT INTO weather_report_cache (
                reminder_id,
                reminder_revision,
                scheduled_for_utc,
                reminder_text,
                report_html,
                prepared_at_utc
            )
            SELECT ?, ?, ?, ?, ?, ?
            FROM reminders
            WHERE id = ? AND status = 'active' AND revision = ?
            ON CONFLICT(reminder_id, scheduled_for_utc) DO UPDATE SET
                reminder_revision = excluded.reminder_revision,
                reminder_text = excluded.reminder_text,
                report_html = excluded.report_html,
                prepared_at_utc = excluded.prepared_at_utc
            WHERE excluded.reminder_revision >= weather_report_cache.reminder_revision
            """,
            (
                reminder_id,
                reminder_revision,
                scheduled_for_utc,
                reminder_text,
                report_html,
                prepared_at_utc,
                reminder_id,
                reminder_revision,
            ),
        )
        return cursor.rowcount == 1


def delete_prepared_weather_report(
    reminder_id: int,
    reminder_revision: int,
    scheduled_for_utc: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM weather_report_cache
            WHERE reminder_id = ?
              AND reminder_revision = ?
              AND scheduled_for_utc = ?
            """,
            (
                reminder_id,
                reminder_revision,
                scheduled_for_utc,
            ),
        )


def delete_expired_prepared_weather_reports(now: datetime) -> None:
    now_utc = format_utc_datetime(now)

    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM weather_report_cache
            WHERE scheduled_for_utc < ?
            """,
            (now_utc,),
        )


def format_utc_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("Datetime must include a timezone.")

    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


REMINDER_DELIVERY_OCCURRENCE_COLUMNS = """
    id,
    reminder_id,
    reminder_revision,
    chat_id,
    scheduled_for_utc,
    status,
    delivery_attempts,
    claim_token,
    claimed_at_utc,
    next_attempt_at_utc,
    last_error,
    message_id,
    message_sent_at_utc,
    created_at_utc,
    updated_at_utc
"""


def claim_reminder_delivery_occurrence(
    *,
    reminder_id: int,
    expected_revision: int,
    scheduled_for_utc: datetime,
    claim_token: str,
    now: datetime,
    stale_before: datetime,
    max_attempts: int,
    occurrence_id: int | None = None,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be greater than or equal to 1.")

    scheduled_for = format_utc_datetime(scheduled_for_utc)
    now_utc = format_utc_datetime(now)
    stale_before_utc = format_utc_datetime(stale_before)

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        reminder = connection.execute(
            """
            SELECT id, chat_id, status, schedule_type, requires_completion,
                   revision, last_handled_scheduled_for_utc
            FROM reminders
            WHERE id = ?
            """,
            (reminder_id,),
        ).fetchone()
        occurrence_where = """
            reminder_id = ? AND reminder_revision = ? AND scheduled_for_utc = ?
        """
        occurrence_params: tuple[Any, ...] = (
            reminder_id,
            expected_revision,
            scheduled_for,
        )
        if occurrence_id is not None:
            occurrence_where += " AND id = ?"
            occurrence_params += (occurrence_id,)
        occurrence = connection.execute(
            f"""
            SELECT {REMINDER_DELIVERY_OCCURRENCE_COLUMNS}
            FROM reminder_delivery_occurrences
            WHERE {occurrence_where}
            """,
            occurrence_params,
        ).fetchone()

        if reminder is None or int(reminder["revision"]) != expected_revision:
            if occurrence is not None and occurrence["status"] == "pending":
                connection.execute(
                    """
                    UPDATE reminder_delivery_occurrences
                    SET status = 'cancelled', claim_token = NULL,
                        claimed_at_utc = NULL, next_attempt_at_utc = NULL,
                        updated_at_utc = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now_utc, occurrence["id"]),
                )
            return {"outcome": "stale_revision"}

        watermark = reminder["last_handled_scheduled_for_utc"]
        if watermark is not None and str(watermark) >= scheduled_for:
            if occurrence is not None and occurrence["status"] == "pending":
                connection.execute(
                    """
                    UPDATE reminder_delivery_occurrences
                    SET status = 'sent', claim_token = NULL,
                        claimed_at_utc = NULL, next_attempt_at_utc = NULL,
                        updated_at_utc = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now_utc, occurrence["id"]),
                )
            return {"outcome": "already_handled"}

        parent_is_active = bool(
            reminder["status"] == "active"
            and int(reminder["requires_completion"] or 0) == 0
        )
        if not parent_is_active:
            if occurrence is not None and occurrence["status"] == "pending":
                connection.execute(
                    """
                    UPDATE reminder_delivery_occurrences
                    SET status = 'cancelled', claim_token = NULL,
                        claimed_at_utc = NULL, next_attempt_at_utc = NULL,
                        updated_at_utc = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now_utc, occurrence["id"]),
                )
            return {"outcome": "inactive"}

        if occurrence_id is not None and occurrence is None:
            return {"outcome": "stale_occurrence"}

        if occurrence is not None:
            status = str(occurrence["status"])
            if status in {"sent", "skipped", "failed"}:
                return {"outcome": "already_handled", "occurrence": occurrence}
            if status != "pending":
                return {"outcome": "inactive", "occurrence": occurrence}

            retry_at = occurrence["next_attempt_at_utc"]
            if retry_at is not None and str(retry_at) > now_utc:
                return {"outcome": "retry_scheduled", "occurrence": occurrence}

            attempts = int(occurrence["delivery_attempts"] or 0)
            retry_is_due = retry_at is not None and str(retry_at) <= now_utc
            claim_is_fresh = bool(
                occurrence["claim_token"]
                and occurrence["claimed_at_utc"]
                and str(occurrence["claimed_at_utc"]) > stale_before_utc
            )
            if claim_is_fresh and not retry_is_due:
                return {"outcome": "delivery_in_progress", "occurrence": occurrence}

            if attempts >= max_attempts:
                connection.execute(
                    """
                    UPDATE reminder_delivery_occurrences
                    SET status = 'failed', claim_token = NULL,
                        claimed_at_utc = NULL, next_attempt_at_utc = NULL,
                        last_error = COALESCE(last_error, 'delivery attempts exhausted'),
                        updated_at_utc = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now_utc, occurrence["id"]),
                )
                _advance_reminder_watermark(
                    connection,
                    reminder_id=reminder_id,
                    scheduled_for_utc=scheduled_for,
                    mark_once_sent=False,
                    expected_revision=expected_revision,
                    once_status="missed",
                )
                return {"outcome": "attempts_exhausted"}

            cursor = connection.execute(
                """
                UPDATE reminder_delivery_occurrences
                SET claim_token = ?, claimed_at_utc = ?,
                    next_attempt_at_utc = NULL,
                    delivery_attempts = delivery_attempts + 1,
                    updated_at_utc = ?
                WHERE id = ? AND status = 'pending'
                """,
                (claim_token, now_utc, now_utc, occurrence["id"]),
            )
            if cursor.rowcount != 1:
                return {"outcome": "inactive"}
            return {
                "outcome": "claimed",
                "occurrence_id": int(occurrence["id"]),
                "delivery_attempts": attempts + 1,
                "is_recovery": bool(occurrence["claim_token"]),
            }

        cursor = connection.execute(
            """
            INSERT INTO reminder_delivery_occurrences (
                reminder_id, reminder_revision, chat_id, scheduled_for_utc,
                status, delivery_attempts, claim_token, claimed_at_utc,
                created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, 'pending', 1, ?, ?, ?, ?)
            """,
            (
                reminder_id,
                expected_revision,
                reminder["chat_id"],
                scheduled_for,
                claim_token,
                now_utc,
                now_utc,
                now_utc,
            ),
        )
        return {
            "outcome": "claimed",
            "occurrence_id": int(cursor.lastrowid),
            "delivery_attempts": 1,
            "is_recovery": False,
        }


def finalize_reminder_delivery_occurrence(
    *,
    occurrence_id: int,
    claim_token: str,
    outcome: str,
    message_id: int | None = None,
    message_sent_at: datetime | None = None,
) -> bool:
    if outcome not in {"sent", "skipped"}:
        raise ValueError("outcome must be 'sent' or 'skipped'.")
    if (message_id is None) != (message_sent_at is None):
        raise ValueError("message_id and message_sent_at must be provided together.")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE reminder_delivery_occurrences
            SET status = ?, claim_token = NULL, claimed_at_utc = NULL,
                next_attempt_at_utc = NULL, last_error = NULL,
                message_id = ?, message_sent_at_utc = ?, updated_at_utc = ?
            WHERE id = ? AND status = 'pending' AND claim_token = ?
            """,
            (
                outcome,
                message_id,
                (
                    format_utc_datetime(message_sent_at)
                    if message_sent_at is not None
                    else None
                ),
                format_utc_datetime(datetime.now(UTC)),
                occurrence_id,
                claim_token,
            ),
        )
        return cursor.rowcount == 1


def refresh_reminder_delivery_claim(
    *,
    occurrence_id: int,
    claim_token: str,
    now: datetime,
) -> bool:
    now_utc = format_utc_datetime(now)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE reminder_delivery_occurrences
            SET claimed_at_utc = ?, updated_at_utc = ?
            WHERE id = ? AND status = 'pending' AND claim_token = ?
            """,
            (now_utc, now_utc, occurrence_id, claim_token),
        )
    return cursor.rowcount == 1


def reschedule_reminder_delivery_occurrence(
    *,
    occurrence_id: int,
    claim_token: str,
    next_attempt_at: datetime,
    last_error: str,
) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE reminder_delivery_occurrences
            SET claim_token = NULL, claimed_at_utc = NULL,
                next_attempt_at_utc = ?, last_error = ?, updated_at_utc = ?
            WHERE id = ? AND status = 'pending' AND claim_token = ?
            """,
            (
                format_utc_datetime(next_attempt_at),
                last_error[:1000],
                format_utc_datetime(datetime.now(UTC)),
                occurrence_id,
                claim_token,
            ),
        )
        return cursor.rowcount == 1


def fail_reminder_delivery_occurrence(
    *,
    occurrence_id: int,
    claim_token: str,
    last_error: str,
) -> bool:
    now_utc = format_utc_datetime(datetime.now(UTC))
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            f"""
            SELECT {REMINDER_DELIVERY_OCCURRENCE_COLUMNS}
            FROM reminder_delivery_occurrences
            WHERE id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        if occurrence is None:
            return False
        cursor = connection.execute(
            """
            UPDATE reminder_delivery_occurrences
            SET status = 'failed', claim_token = NULL, claimed_at_utc = NULL,
                next_attempt_at_utc = NULL, last_error = ?, updated_at_utc = ?
            WHERE id = ? AND status = 'pending' AND claim_token = ?
            """,
            (last_error[:1000], now_utc, occurrence_id, claim_token),
        )
        if cursor.rowcount != 1:
            return False
        _advance_reminder_watermark(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
            mark_once_sent=False,
            expected_revision=int(occurrence["reminder_revision"]),
            once_status="missed",
        )
        return True


def cancel_reminder_delivery_occurrence(occurrence_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE reminder_delivery_occurrences
            SET status = 'cancelled', claim_token = NULL, claimed_at_utc = NULL,
                next_attempt_at_utc = NULL, updated_at_utc = ?
            WHERE id = ? AND status = 'pending'
            """,
            (format_utc_datetime(datetime.now(UTC)), occurrence_id),
        )
        return cursor.rowcount == 1


def get_due_reminder_delivery_occurrences(
    *,
    now: datetime,
    stale_before: datetime,
    limit: int,
) -> list[sqlite3.Row]:
    now_utc = format_utc_datetime(now)
    stale_before_utc = format_utc_datetime(stale_before)
    with get_connection() as connection:
        return connection.execute(
            f"""
            SELECT {REMINDER_DELIVERY_OCCURRENCE_COLUMNS}
            FROM reminder_delivery_occurrences
            WHERE status = 'pending' AND (
                (next_attempt_at_utc IS NOT NULL AND next_attempt_at_utc <= ?)
                OR (
                    next_attempt_at_utc IS NULL
                    AND claim_token IS NULL
                )
                OR (
                    next_attempt_at_utc IS NULL
                    AND claim_token IS NOT NULL
                    AND (claimed_at_utc IS NULL OR claimed_at_utc <= ?)
                )
            )
            ORDER BY COALESCE(
                next_attempt_at_utc,
                claimed_at_utc,
                created_at_utc
            ), id
            LIMIT ?
            """,
            (now_utc, stale_before_utc, limit),
        ).fetchall()


def _enqueue_reminder_message_deletion(
    connection: sqlite3.Connection,
    *,
    reminder_id: int | None,
    chat_id: int,
    message_id: int,
    sent_at: datetime,
    delete_at: datetime,
) -> bool:
    sent_at_utc = format_utc_datetime(sent_at)
    delete_at_utc = format_utc_datetime(delete_at)

    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO reminder_message_deletion_queue (
            reminder_id,
            chat_id,
            message_id,
            sent_at_utc,
            delete_at_utc,
            delete_attempts,
            next_attempt_at_utc,
            last_error
        )
        VALUES (?, ?, ?, ?, ?, 0, ?, NULL)
        """,
        (
            reminder_id,
            chat_id,
            message_id,
            sent_at_utc,
            delete_at_utc,
            delete_at_utc,
        ),
    )

    return cursor.rowcount > 0


def _enqueue_cancelled_completion_checkpoints(
    connection: sqlite3.Connection,
    *,
    reminder_id: int,
    now: datetime,
) -> None:
    rows = connection.execute(
        """
        SELECT chat_id, completion_message_id, completion_message_sent_at_utc
        FROM reminder_completion_occurrences
        WHERE reminder_id = ? AND status = 'completing'
          AND completion_message_id IS NOT NULL
          AND completion_message_sent_at_utc IS NOT NULL
        """,
        (reminder_id,),
    ).fetchall()
    for row in rows:
        _enqueue_reminder_message_deletion(
            connection,
            reminder_id=reminder_id,
            chat_id=int(row["chat_id"]),
            message_id=int(row["completion_message_id"]),
            sent_at=datetime.fromisoformat(str(row["completion_message_sent_at_utc"])),
            delete_at=now,
        )


def enqueue_reminder_message_deletion(
    *,
    reminder_id: int | None,
    chat_id: int,
    message_id: int,
    sent_at: datetime,
    delete_at: datetime,
) -> bool:
    with get_connection() as connection:
        return _enqueue_reminder_message_deletion(
            connection,
            reminder_id=reminder_id,
            chat_id=chat_id,
            message_id=message_id,
            sent_at=sent_at,
            delete_at=delete_at,
        )


def get_due_reminder_message_deletions(
    now: datetime,
    *,
    limit: int,
) -> list[sqlite3.Row]:
    now_utc = format_utc_datetime(now)

    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                reminder_id,
                chat_id,
                message_id,
                sent_at_utc,
                delete_at_utc,
                delete_attempts,
                next_attempt_at_utc,
                last_error
            FROM reminder_message_deletion_queue
            WHERE next_attempt_at_utc <= ?
            ORDER BY next_attempt_at_utc ASC, id ASC
            LIMIT ?
            """,
            (now_utc, limit),
        ).fetchall()


def delete_reminder_message_deletion(queue_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM reminder_message_deletion_queue
            WHERE id = ?
            """,
            (queue_id,),
        )


def reschedule_reminder_message_deletion(
    *,
    queue_id: int,
    delete_attempts: int,
    next_attempt_at: datetime,
    last_error: str,
) -> None:
    next_attempt_at_utc = format_utc_datetime(next_attempt_at)

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE reminder_message_deletion_queue
            SET
                delete_attempts = ?,
                next_attempt_at_utc = ?,
                last_error = ?
            WHERE id = ?
            """,
            (
                delete_attempts,
                next_attempt_at_utc,
                last_error,
                queue_id,
            ),
        )


COMPLETION_OCCURRENCE_COLUMNS = """
    id,
    reminder_id,
    reminder_revision,
    chat_id,
    scheduled_for_utc,
    status,
    rendered_text,
    current_message_id,
    current_message_sent_at_utc,
    next_repeat_at_utc,
    repeat_attempts,
    last_error,
    delivery_claim_token,
    delivery_claimed_at_utc,
    completed_at_utc,
    completed_by_user_id,
    completed_by_display_name,
    completion_claim_token,
    completion_claimed_at_utc,
    completion_next_attempt_at_utc,
    completion_attempts,
    completion_last_error,
    completion_delivery_status,
    completion_message_id,
    completion_message_sent_at_utc,
    completion_callback_message_id,
    completion_callback_message_sent_at_utc,
    superseded_at_utc,
    created_at_utc,
    updated_at_utc
"""


def get_reminder_from_db(reminder_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            f"SELECT {REMINDER_COLUMNS} FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()


def _advance_reminder_watermark(
    connection: sqlite3.Connection,
    *,
    reminder_id: int,
    scheduled_for_utc: str,
    mark_once_sent: bool = False,
    expected_revision: int | None = None,
    once_status: str | None = None,
) -> bool:
    if once_status not in {None, "sent", "missed"}:
        raise ValueError("once_status must be 'sent', 'missed', or None.")

    revision_clause = "" if expected_revision is None else "AND revision = ?"
    params: tuple[Any, ...] = (
        scheduled_for_utc,
        scheduled_for_utc,
        once_status,
        once_status,
        int(mark_once_sent),
        reminder_id,
    )
    if expected_revision is not None:
        params += (expected_revision,)

    cursor = connection.execute(
        f"""
        UPDATE reminders
        SET
            last_handled_scheduled_for_utc = CASE
                WHEN last_handled_scheduled_for_utc IS NULL
                  OR last_handled_scheduled_for_utc < ?
                THEN ?
                ELSE last_handled_scheduled_for_utc
            END,
            status = CASE
                WHEN schedule_type = 'once' AND ? IS NOT NULL THEN ?
                WHEN ? AND schedule_type = 'once' THEN 'sent'
                ELSE status
            END
        WHERE id = ?
          {revision_clause}
        """,
        params,
    )
    return cursor.rowcount == 1


def _is_completion_occurrence_obsolete(
    reminder: sqlite3.Row,
    scheduled_for_utc: str,
) -> bool:
    watermark = reminder["last_handled_scheduled_for_utc"]
    return watermark is not None and scheduled_for_utc < str(watermark)


def _supersede_completion_occurrence(
    connection: sqlite3.Connection,
    *,
    occurrence_id: int,
    now_utc: str,
) -> None:
    connection.execute(
        """
        UPDATE reminder_completion_occurrences
        SET status = 'superseded', superseded_at_utc = ?,
            next_repeat_at_utc = NULL, delivery_claim_token = NULL,
            delivery_claimed_at_utc = NULL, updated_at_utc = ?
        WHERE id = ? AND status IN ('pending', 'active')
        """,
        (now_utc, now_utc, occurrence_id),
    )


def _supersede_older_pending_completion_occurrences(
    connection: sqlite3.Connection,
    *,
    reminder_id: int,
    reminder_revision: int,
    scheduled_for_utc: str,
    exclude_occurrence_id: int,
    now_utc: str,
) -> None:
    connection.execute(
        """
        UPDATE reminder_completion_occurrences
        SET status = 'superseded', superseded_at_utc = ?,
            next_repeat_at_utc = NULL, delivery_claim_token = NULL,
            delivery_claimed_at_utc = NULL, updated_at_utc = ?
        WHERE reminder_id = ? AND reminder_revision = ?
          AND scheduled_for_utc < ? AND id != ? AND status = 'pending'
        """,
        (
            now_utc,
            now_utc,
            reminder_id,
            reminder_revision,
            scheduled_for_utc,
            exclude_occurrence_id,
        ),
    )


def claim_completion_occurrence_delivery(
    *,
    reminder_id: int,
    expected_revision: int,
    occurrence_id: int | None = None,
    scheduled_for_utc: datetime,
    rendered_text: str,
    claim_token: str,
    now: datetime,
    stale_before: datetime,
) -> dict[str, Any]:
    scheduled_for = format_utc_datetime(scheduled_for_utc)
    now_utc = format_utc_datetime(now)
    stale_before_utc = format_utc_datetime(stale_before)

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        reminder = connection.execute(
            """
            SELECT id, chat_id, status, schedule_type, requires_completion,
                   repeat_interval_minutes, revision,
                   last_handled_scheduled_for_utc
            FROM reminders
            WHERE id = ?
            """,
            (reminder_id,),
        ).fetchone()
        occurrence_where = """
            reminder_id = ? AND reminder_revision = ? AND scheduled_for_utc = ?
        """
        occurrence_params: tuple[Any, ...] = (
            reminder_id,
            expected_revision,
            scheduled_for,
        )
        if occurrence_id is not None:
            occurrence_where += " AND id = ?"
            occurrence_params += (occurrence_id,)
        occurrence = connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE {occurrence_where}
            """,
            occurrence_params,
        ).fetchone()

        if reminder is None or int(reminder["revision"]) != expected_revision:
            return {"outcome": "stale_revision"}
        if occurrence_id is not None and occurrence is None:
            return {"outcome": "stale_occurrence"}
        if _is_completion_occurrence_obsolete(reminder, scheduled_for):
            if occurrence is not None:
                _supersede_completion_occurrence(
                    connection,
                    occurrence_id=int(occurrence["id"]),
                    now_utc=now_utc,
                )
            return {"outcome": "obsolete"}

        if occurrence is not None:
            status = str(occurrence["status"])
            if status == "completed":
                _advance_reminder_watermark(
                    connection,
                    reminder_id=reminder_id,
                    scheduled_for_utc=scheduled_for,
                    mark_once_sent=True,
                )
                return {"outcome": "already_completed", "occurrence": occurrence}

            parent_is_active = bool(
                reminder is not None
                and reminder["status"] == "active"
                and int(reminder["requires_completion"] or 0) == 1
            )
            if status == "active":
                if not parent_is_active:
                    return {"outcome": "inconsistent", "occurrence": occurrence}
                _advance_reminder_watermark(
                    connection,
                    reminder_id=reminder_id,
                    scheduled_for_utc=scheduled_for,
                )
                return {"outcome": "already_delivered", "occurrence": occurrence}

            if status != "pending":
                return {
                    "outcome": "inconsistent" if parent_is_active else "inactive",
                    "occurrence": occurrence,
                }

            if not parent_is_active:
                connection.execute(
                    """
                    UPDATE reminder_completion_occurrences
                    SET status = 'cancelled', delivery_claim_token = NULL,
                        delivery_claimed_at_utc = NULL, next_repeat_at_utc = NULL,
                        updated_at_utc = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (now_utc, occurrence["id"]),
                )
                return {"outcome": "inactive", "occurrence": occurrence}

            if occurrence["current_message_id"] is not None:
                _supersede_older_pending_completion_occurrences(
                    connection,
                    reminder_id=reminder_id,
                    reminder_revision=expected_revision,
                    scheduled_for_utc=scheduled_for,
                    exclude_occurrence_id=int(occurrence["id"]),
                    now_utc=now_utc,
                )
                previous = connection.execute(
                    f"""
                    SELECT {COMPLETION_OCCURRENCE_COLUMNS}
                    FROM reminder_completion_occurrences
                    WHERE reminder_id = ? AND status = 'active' AND id != ?
                    """,
                    (reminder_id, occurrence["id"]),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE reminder_completion_occurrences
                    SET status = 'superseded', superseded_at_utc = ?,
                        next_repeat_at_utc = NULL, updated_at_utc = ?
                    WHERE reminder_id = ? AND status = 'active' AND id != ?
                    """,
                    (now_utc, now_utc, reminder_id, occurrence["id"]),
                )
                sent_at_raw = occurrence["current_message_sent_at_utc"] or now_utc
                sent_at = datetime.fromisoformat(str(sent_at_raw))
                interval = int(reminder["repeat_interval_minutes"])
                next_repeat = format_utc_datetime(sent_at + timedelta(minutes=interval))
                connection.execute(
                    """
                    UPDATE reminder_completion_occurrences
                    SET status = 'active', next_repeat_at_utc = ?,
                        delivery_claim_token = NULL, delivery_claimed_at_utc = NULL,
                        updated_at_utc = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (next_repeat, now_utc, occurrence["id"]),
                )
                _advance_reminder_watermark(
                    connection,
                    reminder_id=reminder_id,
                    scheduled_for_utc=scheduled_for,
                )
                return {
                    "outcome": "recovered",
                    "occurrence_id": int(occurrence["id"]),
                    "previous": previous,
                }

            retry_at = occurrence["next_repeat_at_utc"]
            if retry_at is not None and str(retry_at) > now_utc:
                return {"outcome": "retry_scheduled", "occurrence": occurrence}
            claim_is_fresh = bool(
                occurrence["delivery_claim_token"]
                and occurrence["delivery_claimed_at_utc"]
                and str(occurrence["delivery_claimed_at_utc"]) > stale_before_utc
            )
            retry_is_due = retry_at is not None and str(retry_at) <= now_utc
            if claim_is_fresh and not retry_is_due:
                return {"outcome": "delivery_in_progress", "occurrence": occurrence}

            connection.execute(
                """
                UPDATE reminder_completion_occurrences
                SET delivery_claim_token = ?, delivery_claimed_at_utc = ?,
                    next_repeat_at_utc = NULL, rendered_text = ?, updated_at_utc = ?
                WHERE id = ? AND status = 'pending'
                """,
                (claim_token, now_utc, rendered_text, now_utc, occurrence["id"]),
            )
            return {
                "outcome": "claimed",
                "occurrence_id": int(occurrence["id"]),
                "is_recovery": True,
            }

        if (
            reminder is None
            or reminder["status"] != "active"
            or int(reminder["requires_completion"] or 0) != 1
        ):
            return {"outcome": "inactive"}

        cursor = connection.execute(
            """
            INSERT INTO reminder_completion_occurrences (
                reminder_id, reminder_revision, chat_id, scheduled_for_utc,
                status, rendered_text,
                delivery_claim_token, delivery_claimed_at_utc,
                created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                reminder_id,
                expected_revision,
                reminder["chat_id"],
                scheduled_for,
                rendered_text,
                claim_token,
                now_utc,
                now_utc,
                now_utc,
            ),
        )
        return {
            "outcome": "claimed",
            "occurrence_id": int(cursor.lastrowid),
            "is_recovery": False,
        }


def activate_claimed_completion_occurrence(
    *,
    occurrence_id: int,
    claim_token: str,
    message_id: int,
    sent_at: datetime,
) -> dict[str, Any]:
    sent_at_utc = format_utc_datetime(sent_at)
    now_utc = format_utc_datetime(datetime.now(UTC))

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            f"SELECT {COMPLETION_OCCURRENCE_COLUMNS} FROM reminder_completion_occurrences WHERE id = ?",
            (occurrence_id,),
        ).fetchone()
        if occurrence is None:
            return {"outcome": "missing"}
        if occurrence["status"] == "completed":
            same_message = occurrence["current_message_id"] == message_id
            return {"outcome": "completed_same" if same_message else "completed_other"}
        if occurrence["status"] == "active":
            same_message = occurrence["current_message_id"] == message_id
            return {"outcome": "active_same" if same_message else "active_other"}

        reminder = connection.execute(
            """
            SELECT status, requires_completion, repeat_interval_minutes, revision,
                   last_handled_scheduled_for_utc
            FROM reminders WHERE id = ?
            """,
            (occurrence["reminder_id"],),
        ).fetchone()
        if (
            occurrence["status"] != "pending"
            or occurrence["delivery_claim_token"] != claim_token
            or reminder is None
            or reminder["status"] != "active"
            or int(reminder["requires_completion"] or 0) != 1
            or int(reminder["revision"]) != int(occurrence["reminder_revision"])
        ):
            return {"outcome": "stale"}
        if _is_completion_occurrence_obsolete(
            reminder,
            str(occurrence["scheduled_for_utc"]),
        ):
            _supersede_completion_occurrence(
                connection,
                occurrence_id=occurrence_id,
                now_utc=now_utc,
            )
            return {"outcome": "obsolete"}

        _supersede_older_pending_completion_occurrences(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            reminder_revision=int(occurrence["reminder_revision"]),
            scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
            exclude_occurrence_id=occurrence_id,
            now_utc=now_utc,
        )

        previous = connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE reminder_id = ? AND status = 'active' AND id != ?
            """,
            (occurrence["reminder_id"], occurrence_id),
        ).fetchone()
        connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'superseded', superseded_at_utc = ?,
                next_repeat_at_utc = NULL, updated_at_utc = ?
            WHERE reminder_id = ? AND status = 'active' AND id != ?
            """,
            (now_utc, now_utc, occurrence["reminder_id"], occurrence_id),
        )
        next_repeat = format_utc_datetime(
            sent_at + timedelta(minutes=int(reminder["repeat_interval_minutes"]))
        )
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'active', current_message_id = ?,
                current_message_sent_at_utc = ?, next_repeat_at_utc = ?,
                repeat_attempts = 0, last_error = NULL,
                delivery_claim_token = NULL, delivery_claimed_at_utc = NULL,
                updated_at_utc = ?
            WHERE id = ? AND status = 'pending' AND delivery_claim_token = ?
            """,
            (
                message_id,
                sent_at_utc,
                next_repeat,
                now_utc,
                occurrence_id,
                claim_token,
            ),
        )
        if cursor.rowcount != 1:
            return {"outcome": "stale"}
        _advance_reminder_watermark(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
        )
        return {"outcome": "activated", "previous": previous}


def complete_completion_occurrence(
    *,
    occurrence_id: int,
    chat_id: int,
    callback_message_id: int,
    callback_message_sent_at: datetime | None,
    user_id: int,
    display_name: str,
    completed_at: datetime,
) -> dict[str, Any]:
    completed_at_utc = format_utc_datetime(completed_at)
    message_sent_at_utc = (
        format_utc_datetime(callback_message_sent_at)
        if callback_message_sent_at is not None
        else completed_at_utc
    )
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            f"SELECT {COMPLETION_OCCURRENCE_COLUMNS} FROM reminder_completion_occurrences WHERE id = ?",
            (occurrence_id,),
        ).fetchone()
        if occurrence is None:
            return {"outcome": "missing"}
        if int(occurrence["chat_id"]) != chat_id:
            return {"outcome": "wrong_chat"}
        status = str(occurrence["status"])
        if status == "completed":
            return {"outcome": "already_completed", "occurrence": occurrence}
        if status == "completing":
            return {"outcome": "already_completing", "occurrence": occurrence}
        if status not in {"pending", "active"}:
            return {"outcome": "inactive", "occurrence": occurrence}

        reminder = connection.execute(
            """
            SELECT status, schedule_type, delete_after_two_days,
                   requires_completion, revision,
                   last_handled_scheduled_for_utc
            FROM reminders WHERE id = ?
            """,
            (occurrence["reminder_id"],),
        ).fetchone()
        if (
            reminder is None
            or reminder["status"] != "active"
            or int(reminder["requires_completion"] or 0) != 1
            or int(reminder["revision"]) != int(occurrence["reminder_revision"])
        ):
            return {"outcome": "reminder_inactive", "occurrence": occurrence}
        if _is_completion_occurrence_obsolete(
            reminder,
            str(occurrence["scheduled_for_utc"]),
        ):
            _supersede_completion_occurrence(
                connection,
                occurrence_id=occurrence_id,
                now_utc=completed_at_utc,
            )
            return {"outcome": "obsolete", "occurrence": occurrence}

        _supersede_older_pending_completion_occurrences(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            reminder_revision=int(occurrence["reminder_revision"]),
            scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
            exclude_occurrence_id=occurrence_id,
            now_utc=completed_at_utc,
        )

        previous = None
        if status == "pending":
            previous = connection.execute(
                f"""
                SELECT {COMPLETION_OCCURRENCE_COLUMNS}
                FROM reminder_completion_occurrences
                WHERE reminder_id = ? AND status = 'active' AND id != ?
                """,
                (occurrence["reminder_id"], occurrence_id),
            ).fetchone()
            connection.execute(
                """
                UPDATE reminder_completion_occurrences
                SET status = 'superseded', superseded_at_utc = ?,
                    next_repeat_at_utc = NULL, updated_at_utc = ?
                WHERE reminder_id = ? AND status = 'active' AND id != ?
                """,
                (
                    completed_at_utc,
                    completed_at_utc,
                    occurrence["reminder_id"],
                    occurrence_id,
                ),
            )

        current_message_id = (
            int(occurrence["current_message_id"])
            if occurrence["current_message_id"] is not None
            else callback_message_id
        )
        current_message_sent_at_utc = (
            str(occurrence["current_message_sent_at_utc"])
            if occurrence["current_message_sent_at_utc"] is not None
            else message_sent_at_utc
        )

        if int(reminder["delete_after_two_days"] or 0) == 1:
            cursor = connection.execute(
                """
                UPDATE reminder_completion_occurrences
                SET status = 'completing', current_message_id = ?,
                    current_message_sent_at_utc = ?,
                    next_repeat_at_utc = NULL,
                    delivery_claim_token = NULL,
                    delivery_claimed_at_utc = NULL,
                    completed_at_utc = ?, completed_by_user_id = ?,
                    completed_by_display_name = ?,
                    completion_claim_token = NULL,
                    completion_claimed_at_utc = NULL,
                    completion_next_attempt_at_utc = NULL,
                    completion_attempts = 0,
                    completion_last_error = NULL,
                    completion_delivery_status = 'pending',
                    completion_callback_message_id = ?,
                    completion_callback_message_sent_at_utc = ?,
                    updated_at_utc = ?
                WHERE id = ? AND status IN ('pending', 'active')
                """,
                (
                    current_message_id,
                    current_message_sent_at_utc,
                    completed_at_utc,
                    user_id,
                    display_name,
                    callback_message_id,
                    message_sent_at_utc,
                    completed_at_utc,
                    occurrence_id,
                ),
            )
            if cursor.rowcount != 1:
                return {"outcome": "inactive", "occurrence": occurrence}
            if (
                previous is not None
                and previous["current_message_id"] is not None
                and previous["current_message_sent_at_utc"] is not None
            ):
                _enqueue_reminder_message_deletion(
                    connection,
                    reminder_id=int(occurrence["reminder_id"]),
                    chat_id=int(previous["chat_id"]),
                    message_id=int(previous["current_message_id"]),
                    sent_at=datetime.fromisoformat(
                        str(previous["current_message_sent_at_utc"])
                    ),
                    delete_at=completed_at,
                )
            _advance_reminder_watermark(
                connection,
                reminder_id=int(occurrence["reminder_id"]),
                scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
            )
            return {
                "outcome": "completing",
                "occurrence_id": occurrence_id,
                "chat_id": chat_id,
            }

        connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'completed', current_message_id = ?,
                current_message_sent_at_utc = COALESCE(current_message_sent_at_utc, ?),
                next_repeat_at_utc = NULL, delivery_claim_token = NULL,
                delivery_claimed_at_utc = NULL, completed_at_utc = ?,
                completed_by_user_id = ?, completed_by_display_name = ?,
                updated_at_utc = ?
            WHERE id = ? AND status IN ('pending', 'active')
            """,
            (
                current_message_id,
                message_sent_at_utc,
                completed_at_utc,
                user_id,
                display_name,
                completed_at_utc,
                occurrence_id,
            ),
        )
        _advance_reminder_watermark(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
            mark_once_sent=reminder["schedule_type"] == "once",
        )
        return {
            "outcome": "completed",
            "chat_id": chat_id,
            "message_id": current_message_id,
            "rendered_text": str(occurrence["rendered_text"]),
            "previous": previous,
        }


def claim_completion_publication(
    *,
    occurrence_id: int,
    claim_token: str,
    now: datetime,
    stale_before: datetime,
) -> dict[str, Any]:
    now_utc = format_utc_datetime(now)
    stale_before_utc = format_utc_datetime(stale_before)
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        if occurrence is None:
            return {"outcome": "missing"}
        if occurrence["status"] == "completed":
            return {"outcome": "already_completed", "occurrence": occurrence}
        if occurrence["status"] != "completing":
            return {"outcome": "inactive", "occurrence": occurrence}

        reminder = connection.execute(
            """
            SELECT status, revision
            FROM reminders
            WHERE id = ?
            """,
            (occurrence["reminder_id"],),
        ).fetchone()
        if (
            reminder is None
            or reminder["status"] != "active"
            or int(reminder["revision"]) != int(occurrence["reminder_revision"])
        ):
            return {"outcome": "inactive", "occurrence": occurrence}

        retry_at = occurrence["completion_next_attempt_at_utc"]
        if retry_at is not None and str(retry_at) > now_utc:
            return {"outcome": "retry_scheduled", "occurrence": occurrence}
        claim_is_fresh = bool(
            occurrence["completion_claim_token"]
            and occurrence["completion_claimed_at_utc"]
            and str(occurrence["completion_claimed_at_utc"]) > stale_before_utc
        )
        if claim_is_fresh and occurrence["completion_message_id"] is None:
            return {"outcome": "publication_in_progress", "occurrence": occurrence}

        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET completion_claim_token = ?, completion_claimed_at_utc = ?,
                completion_next_attempt_at_utc = NULL, updated_at_utc = ?
            WHERE id = ? AND status = 'completing'
            """,
            (claim_token, now_utc, now_utc, occurrence_id),
        )
        if cursor.rowcount != 1:
            return {"outcome": "inactive", "occurrence": occurrence}
        claimed = connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        return {"outcome": "claimed", "occurrence": claimed}


def checkpoint_completion_message(
    *,
    occurrence_id: int,
    claim_token: str,
    message_id: int,
    sent_at: datetime,
) -> str:
    sent_at_utc = format_utc_datetime(sent_at)
    now_utc = format_utc_datetime(datetime.now(UTC))
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            """
            SELECT status, completion_claim_token, completion_message_id
            FROM reminder_completion_occurrences
            WHERE id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        if occurrence is None:
            return "missing"
        if occurrence["completion_message_id"] is not None:
            return (
                "checkpointed_same"
                if int(occurrence["completion_message_id"]) == message_id
                else "checkpointed_other"
            )
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET completion_message_id = ?,
                completion_message_sent_at_utc = ?,
                completion_delivery_status = 'sent', updated_at_utc = ?
            WHERE id = ? AND status = 'completing'
              AND completion_claim_token = ?
              AND completion_message_id IS NULL
            """,
            (message_id, sent_at_utc, now_utc, occurrence_id, claim_token),
        )
        return "checkpointed" if cursor.rowcount == 1 else "stale"


def reschedule_completion_publication(
    *,
    occurrence_id: int,
    claim_token: str,
    next_attempt_at: datetime,
    last_error: str,
) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET completion_claim_token = NULL,
                completion_claimed_at_utc = NULL,
                completion_next_attempt_at_utc = ?,
                completion_attempts = completion_attempts + 1,
                completion_last_error = ?, updated_at_utc = ?
            WHERE id = ? AND status = 'completing'
              AND completion_claim_token = ?
            """,
            (
                format_utc_datetime(next_attempt_at),
                last_error[:1000],
                format_utc_datetime(datetime.now(UTC)),
                occurrence_id,
                claim_token,
            ),
        )
        return cursor.rowcount == 1


def _enqueue_occurrence_source_messages(
    connection: sqlite3.Connection,
    occurrence: sqlite3.Row,
    *,
    now: datetime,
    keep_current_until_safe_delay: bool,
) -> None:
    messages: dict[int, tuple[datetime, datetime]] = {}
    current_message_id = occurrence["current_message_id"]
    current_sent_at = occurrence["current_message_sent_at_utc"]
    if current_message_id is not None and current_sent_at is not None:
        sent_at = datetime.fromisoformat(str(current_sent_at))
        delete_at = (
            sent_at + MESSAGE_DELETION_DELAY if keep_current_until_safe_delay else now
        )
        messages[int(current_message_id)] = (sent_at, delete_at)

    callback_message_id = occurrence["completion_callback_message_id"]
    callback_sent_at = occurrence["completion_callback_message_sent_at_utc"]
    if callback_message_id is not None and callback_sent_at is not None:
        callback_id = int(callback_message_id)
        if callback_id not in messages:
            messages[callback_id] = (
                datetime.fromisoformat(str(callback_sent_at)),
                now,
            )

    for message_id, (sent_at, delete_at) in messages.items():
        _enqueue_reminder_message_deletion(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            chat_id=int(occurrence["chat_id"]),
            message_id=message_id,
            sent_at=sent_at,
            delete_at=delete_at,
        )


def finalize_completion_publication(
    *,
    occurrence_id: int,
    claim_token: str,
    now: datetime,
) -> bool:
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        if (
            occurrence is None
            or occurrence["status"] != "completing"
            or occurrence["completion_claim_token"] != claim_token
            or occurrence["completion_message_id"] is None
            or occurrence["completion_message_sent_at_utc"] is None
        ):
            return False
        reminder = connection.execute(
            """
            SELECT status, schedule_type, revision
            FROM reminders WHERE id = ?
            """,
            (occurrence["reminder_id"],),
        ).fetchone()
        if (
            reminder is None
            or reminder["status"] != "active"
            or int(reminder["revision"]) != int(occurrence["reminder_revision"])
        ):
            return False

        _enqueue_occurrence_source_messages(
            connection,
            occurrence,
            now=now,
            keep_current_until_safe_delay=False,
        )
        final_sent_at = datetime.fromisoformat(
            str(occurrence["completion_message_sent_at_utc"])
        )
        _enqueue_reminder_message_deletion(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            chat_id=int(occurrence["chat_id"]),
            message_id=int(occurrence["completion_message_id"]),
            sent_at=final_sent_at,
            delete_at=final_sent_at + MESSAGE_DELETION_DELAY,
        )
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'completed',
                current_message_id = completion_message_id,
                current_message_sent_at_utc = completion_message_sent_at_utc,
                completion_delivery_status = 'sent',
                completion_claim_token = NULL,
                completion_claimed_at_utc = NULL,
                completion_next_attempt_at_utc = NULL,
                completion_last_error = NULL,
                next_repeat_at_utc = NULL,
                delivery_claim_token = NULL,
                delivery_claimed_at_utc = NULL,
                updated_at_utc = ?
            WHERE id = ? AND status = 'completing'
              AND completion_claim_token = ?
            """,
            (format_utc_datetime(now), occurrence_id, claim_token),
        )
        if cursor.rowcount != 1:
            return False
        _advance_reminder_watermark(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
            mark_once_sent=reminder["schedule_type"] == "once",
        )
        return True


def finalize_failed_completion_publication(
    *,
    occurrence_id: int,
    claim_token: str,
    now: datetime,
    last_error: str,
    fallback_succeeded: bool,
) -> bool:
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        if (
            occurrence is None
            or occurrence["status"] != "completing"
            or occurrence["completion_claim_token"] != claim_token
        ):
            return False
        reminder = connection.execute(
            """
            SELECT status, schedule_type, revision
            FROM reminders WHERE id = ?
            """,
            (occurrence["reminder_id"],),
        ).fetchone()
        if (
            reminder is None
            or reminder["status"] != "active"
            or int(reminder["revision"]) != int(occurrence["reminder_revision"])
        ):
            return False

        _enqueue_occurrence_source_messages(
            connection,
            occurrence,
            now=now,
            keep_current_until_safe_delay=fallback_succeeded,
        )
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'completed',
                completion_delivery_status = ?,
                completion_claim_token = NULL,
                completion_claimed_at_utc = NULL,
                completion_next_attempt_at_utc = NULL,
                completion_last_error = ?,
                next_repeat_at_utc = NULL,
                delivery_claim_token = NULL,
                delivery_claimed_at_utc = NULL,
                updated_at_utc = ?
            WHERE id = ? AND status = 'completing'
              AND completion_claim_token = ?
            """,
            (
                "fallback" if fallback_succeeded else "failed",
                last_error[:1000],
                format_utc_datetime(now),
                occurrence_id,
                claim_token,
            ),
        )
        if cursor.rowcount != 1:
            return False
        _advance_reminder_watermark(
            connection,
            reminder_id=int(occurrence["reminder_id"]),
            scheduled_for_utc=str(occurrence["scheduled_for_utc"]),
            mark_once_sent=reminder["schedule_type"] == "once",
        )
        return True


def get_due_completion_occurrences(
    *,
    now: datetime,
    stale_before: datetime,
    limit: int,
) -> list[sqlite3.Row]:
    now_utc = format_utc_datetime(now)
    stale_before_utc = format_utc_datetime(stale_before)
    with get_connection() as connection:
        return connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE (
                status = 'active'
                AND next_repeat_at_utc IS NOT NULL
                AND next_repeat_at_utc <= ?
            ) OR (
                status = 'pending'
                AND (
                    current_message_id IS NOT NULL
                    OR (
                        next_repeat_at_utc IS NOT NULL
                        AND next_repeat_at_utc <= ?
                    )
                    OR (
                        next_repeat_at_utc IS NULL
                        AND delivery_claim_token IS NOT NULL
                        AND (
                            delivery_claimed_at_utc IS NULL
                            OR delivery_claimed_at_utc <= ?
                        )
                    )
                    OR (
                        next_repeat_at_utc IS NULL
                        AND delivery_claim_token IS NULL
                    )
                )
            ) OR (
                status = 'completing'
                AND (
                    completion_message_id IS NOT NULL
                    OR (
                        completion_next_attempt_at_utc IS NOT NULL
                        AND completion_next_attempt_at_utc <= ?
                    )
                    OR (
                        completion_next_attempt_at_utc IS NULL
                        AND completion_claim_token IS NULL
                    )
                    OR (
                        completion_next_attempt_at_utc IS NULL
                        AND completion_claim_token IS NOT NULL
                        AND (
                            completion_claimed_at_utc IS NULL
                            OR completion_claimed_at_utc <= ?
                        )
                    )
                )
            )
            ORDER BY COALESCE(
                completion_next_attempt_at_utc,
                next_repeat_at_utc,
                completion_claimed_at_utc,
                delivery_claimed_at_utc,
                created_at_utc
            ), id
            LIMIT ?
            """,
            (
                now_utc,
                now_utc,
                stale_before_utc,
                now_utc,
                stale_before_utc,
                limit,
            ),
        ).fetchall()


def get_repeatable_completion_occurrence(
    *,
    occurrence_id: int,
    expected_message_id: int,
) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS},
                   (
                       SELECT repeat_interval_minutes
                       FROM reminders
                       WHERE reminders.id = reminder_completion_occurrences.reminder_id
                   ) AS parent_repeat_interval_minutes
            FROM reminder_completion_occurrences
            WHERE id = ? AND status = 'active' AND current_message_id = ?
              AND EXISTS (
                  SELECT 1 FROM reminders
                  WHERE reminders.id = reminder_completion_occurrences.reminder_id
                    AND reminders.status = 'active'
                    AND reminders.requires_completion = 1
                    AND reminders.revision = reminder_completion_occurrences.reminder_revision
              )
            """,
            (occurrence_id, expected_message_id),
        ).fetchone()


def replace_active_completion_message(
    *,
    occurrence_id: int,
    expected_message_id: int,
    new_message_id: int,
    sent_at: datetime,
    next_repeat_at: datetime,
) -> bool:
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET current_message_id = ?, current_message_sent_at_utc = ?,
                next_repeat_at_utc = ?, repeat_attempts = 0, last_error = NULL,
                updated_at_utc = ?
            WHERE id = ? AND status = 'active' AND current_message_id = ?
              AND EXISTS (
                  SELECT 1 FROM reminders
                  WHERE reminders.id = reminder_completion_occurrences.reminder_id
                    AND reminders.status = 'active'
                    AND reminders.requires_completion = 1
                    AND reminders.revision = reminder_completion_occurrences.reminder_revision
              )
            """,
            (
                new_message_id,
                format_utc_datetime(sent_at),
                format_utc_datetime(next_repeat_at),
                format_utc_datetime(datetime.now(UTC)),
                occurrence_id,
                expected_message_id,
            ),
        )
        return cursor.rowcount == 1


def reschedule_completion_occurrence_after_error(
    *,
    occurrence_id: int,
    expected_status: str,
    expected_message_id: int | None,
    next_attempt_at: datetime,
    attempts: int,
    last_error: str,
) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET next_repeat_at_utc = ?, repeat_attempts = ?, last_error = ?,
                delivery_claim_token = CASE WHEN status = 'pending' THEN NULL ELSE delivery_claim_token END,
                delivery_claimed_at_utc = CASE WHEN status = 'pending' THEN NULL ELSE delivery_claimed_at_utc END,
                updated_at_utc = ?
            WHERE id = ? AND status = ?
              AND (current_message_id = ? OR (current_message_id IS NULL AND ? IS NULL))
            """,
            (
                format_utc_datetime(next_attempt_at),
                attempts,
                last_error[:1000],
                format_utc_datetime(datetime.now(UTC)),
                occurrence_id,
                expected_status,
                expected_message_id,
                expected_message_id,
            ),
        )
        return cursor.rowcount == 1


def fail_completion_occurrence(
    *,
    occurrence_id: int,
    expected_status: str,
    expected_message_id: int | None,
    last_error: str,
) -> bool:
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        occurrence = connection.execute(
            f"""
            SELECT {COMPLETION_OCCURRENCE_COLUMNS}
            FROM reminder_completion_occurrences
            WHERE id = ?
            """,
            (occurrence_id,),
        ).fetchone()
        if occurrence is None:
            return False
        cursor = connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'failed', next_repeat_at_utc = NULL,
                delivery_claim_token = NULL, delivery_claimed_at_utc = NULL,
                last_error = ?, updated_at_utc = ?
            WHERE id = ? AND status = ?
              AND (current_message_id = ? OR (current_message_id IS NULL AND ? IS NULL))
            """,
            (
                last_error[:1000],
                format_utc_datetime(datetime.now(UTC)),
                occurrence_id,
                expected_status,
                expected_message_id,
                expected_message_id,
            ),
        )
        if cursor.rowcount != 1:
            return False

        connection.execute(
            """
            UPDATE reminders
            SET status = 'missed',
                last_handled_scheduled_for_utc = CASE
                    WHEN last_handled_scheduled_for_utc IS NULL
                      OR last_handled_scheduled_for_utc < ?
                    THEN ?
                    ELSE last_handled_scheduled_for_utc
                END
            WHERE id = ? AND status = 'active' AND schedule_type = 'once'
              AND requires_completion = 1 AND revision = ?
            """,
            (
                occurrence["scheduled_for_utc"],
                occurrence["scheduled_for_utc"],
                occurrence["reminder_id"],
                occurrence["reminder_revision"],
            ),
        )
        return True


def delete_active_reminder_for_chat_in_db(
    reminder_id: int,
    chat_id: int,
    *,
    expected_revision: int | None = None,
) -> bool:
    now_utc = format_utc_datetime(datetime.now(UTC))
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE reminders SET status = 'deleted'
            WHERE id = ? AND chat_id = ? AND status = 'active'
              AND (? IS NULL OR revision = ?)
            """,
            (reminder_id, chat_id, expected_revision, expected_revision),
        )
        if cursor.rowcount != 1:
            return False
        _delete_prepared_weather_reports_for_reminder(
            connection,
            reminder_id=reminder_id,
        )
        _cancel_pending_reminder_delivery_occurrences(
            connection,
            reminder_id=reminder_id,
            now_utc=now_utc,
        )
        _enqueue_cancelled_completion_checkpoints(
            connection,
            reminder_id=reminder_id,
            now=datetime.fromisoformat(now_utc),
        )
        connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'cancelled', next_repeat_at_utc = NULL,
                delivery_claim_token = NULL, delivery_claimed_at_utc = NULL,
                completion_claim_token = NULL,
                completion_claimed_at_utc = NULL,
                completion_next_attempt_at_utc = NULL,
                updated_at_utc = ?
            WHERE reminder_id = ?
              AND status IN ('pending', 'active', 'completing')
            """,
            (now_utc, reminder_id),
        )
        return True
