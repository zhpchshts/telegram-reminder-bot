import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import DB_PATH
from app.constants import REMINDER_COLUMNS, REMINDER_KIND_TEXT, SCHEMA_MIGRATIONS

UTC = timezone.utc


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
                delivery_tracking_started_at_utc TEXT,
                last_handled_scheduled_for_utc TEXT,
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
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reminders)").fetchall()
        }

        for column_name, column_definition in SCHEMA_MIGRATIONS.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE reminders ADD COLUMN {column_definition}"
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
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    delivery_tracking_started_at_utc = format_utc_datetime(datetime.now(UTC))

    with get_connection() as connection:
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
                delivery_tracking_started_at_utc,
                last_handled_scheduled_for_utc,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
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
                delivery_tracking_started_at_utc,
                now,
            ),
        )

        return int(cursor.lastrowid)


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
) -> bool:
    delivery_tracking_started_at_utc = format_utc_datetime(datetime.now(UTC))

    with get_connection() as connection:
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
                delivery_tracking_started_at_utc = ?,
                last_handled_scheduled_for_utc = NULL
            WHERE id = ? AND chat_id = ? AND status = 'active'
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
                delivery_tracking_started_at_utc,
                reminder_id,
                chat_id,
            ),
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


def mark_reminder_as_sent(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "sent")


def mark_reminder_as_deleted(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "deleted")


def mark_reminder_as_missed(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "missed")


def mark_reminder_occurrence_handled(
    reminder_id: int,
    scheduled_for_utc: datetime,
    *,
    final_status: str | None = None,
) -> bool:
    if final_status not in {None, "sent", "missed"}:
        raise ValueError("final_status must be 'sent', 'missed', or None.")

    scheduled_for = format_utc_datetime(scheduled_for_utc)

    with get_connection() as connection:
        cursor = connection.execute(
            """
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
            """,
            (
                scheduled_for,
                final_status,
                reminder_id,
                scheduled_for,
            ),
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
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT name, admin1, country, latitude, longitude
            FROM weather_location_cache
            WHERE location_key = ?
            """,
            (location_key,),
        ).fetchone()

    return dict(row) if row else None


def save_cached_weather_location(
    location_key: str,
    location: dict[str, Any],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")

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
    reminder_text: str,
    earliest_scheduled_for: datetime,
    latest_scheduled_for: datetime,
) -> dict[str, str] | None:
    earliest_scheduled_for_utc = format_utc_datetime(earliest_scheduled_for)
    latest_scheduled_for_utc = format_utc_datetime(latest_scheduled_for)

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT scheduled_for_utc, report_html
            FROM weather_report_cache
            WHERE reminder_id = ?
              AND reminder_text = ?
              AND scheduled_for_utc >= ?
              AND scheduled_for_utc <= ?
            ORDER BY scheduled_for_utc DESC
            LIMIT 1
            """,
            (
                reminder_id,
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


def save_prepared_weather_report(
    reminder_id: int,
    scheduled_for: datetime,
    reminder_text: str,
    report_html: str,
) -> None:
    scheduled_for_utc = format_utc_datetime(scheduled_for)
    prepared_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO weather_report_cache (
                reminder_id,
                scheduled_for_utc,
                reminder_text,
                report_html,
                prepared_at_utc
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(reminder_id, scheduled_for_utc) DO UPDATE SET
                reminder_text = excluded.reminder_text,
                report_html = excluded.report_html,
                prepared_at_utc = excluded.prepared_at_utc
            """,
            (
                reminder_id,
                scheduled_for_utc,
                reminder_text,
                report_html,
                prepared_at_utc,
            ),
        )


def delete_prepared_weather_report(
    reminder_id: int,
    scheduled_for_utc: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM weather_report_cache
            WHERE reminder_id = ?
              AND scheduled_for_utc = ?
            """,
            (
                reminder_id,
                scheduled_for_utc,
            ),
        )


def delete_prepared_weather_reports_for_reminder(reminder_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM weather_report_cache
            WHERE reminder_id = ?
            """,
            (reminder_id,),
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


def enqueue_reminder_message_deletion(
    *,
    reminder_id: int | None,
    chat_id: int,
    message_id: int,
    sent_at: datetime,
    delete_at: datetime,
) -> bool:
    sent_at_utc = format_utc_datetime(sent_at)
    delete_at_utc = format_utc_datetime(delete_at)

    with get_connection() as connection:
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
