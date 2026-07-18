import sqlite3
from datetime import datetime, timedelta, timezone
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
                requires_completion INTEGER NOT NULL DEFAULT 0,
                repeat_interval_minutes INTEGER,
                revision INTEGER NOT NULL DEFAULT 1,
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
    requires_completion: bool = False,
    repeat_interval_minutes: int | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    delivery_tracking_started_at_utc = format_utc_datetime(datetime.now(UTC))

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
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
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, ?)
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
    requires_completion: bool = False,
    repeat_interval_minutes: int | None = None,
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
            ),
        )
        if cursor.rowcount > 0:
            now_utc = format_utc_datetime(datetime.now(UTC))
            connection.execute(
                """
                UPDATE reminder_completion_occurrences
                SET
                    status = 'cancelled',
                    next_repeat_at_utc = NULL,
                    delivery_claim_token = NULL,
                    delivery_claimed_at_utc = NULL,
                    updated_at_utc = ?
                WHERE reminder_id = ?
                  AND status IN ('pending', 'active')
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
) -> None:
    connection.execute(
        """
        UPDATE reminders
        SET
            last_handled_scheduled_for_utc = CASE
                WHEN last_handled_scheduled_for_utc IS NULL
                  OR last_handled_scheduled_for_utc < ?
                THEN ?
                ELSE last_handled_scheduled_for_utc
            END,
            status = CASE
                WHEN ? AND schedule_type = 'once' THEN 'sent'
                ELSE status
            END
        WHERE id = ?
        """,
        (
            scheduled_for_utc,
            scheduled_for_utc,
            int(mark_once_sent),
            reminder_id,
        ),
    )


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
        if status not in {"pending", "active"}:
            return {"outcome": "inactive", "occurrence": occurrence}

        reminder = connection.execute(
            """
            SELECT status, schedule_type, requires_completion, revision,
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
            )
            ORDER BY COALESCE(next_repeat_at_utc, delivery_claimed_at_utc, created_at_utc), id
            LIMIT ?
            """,
            (now_utc, now_utc, stale_before_utc, limit),
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


def delete_active_reminder_for_chat_in_db(reminder_id: int, chat_id: int) -> bool:
    now_utc = format_utc_datetime(datetime.now(UTC))
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE reminders SET status = 'deleted'
            WHERE id = ? AND chat_id = ? AND status = 'active'
            """,
            (reminder_id, chat_id),
        )
        if cursor.rowcount != 1:
            return False
        connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET status = 'cancelled', next_repeat_at_utc = NULL,
                delivery_claim_token = NULL, delivery_claimed_at_utc = NULL,
                updated_at_utc = ?
            WHERE reminder_id = ? AND status IN ('pending', 'active')
            """,
            (now_utc, reminder_id),
        )
        return True
