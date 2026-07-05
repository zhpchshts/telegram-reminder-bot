import sqlite3
from datetime import datetime
from typing import Any

from app.config import DB_PATH
from app.constants import REMINDER_COLUMNS, REMINDER_KIND_TEXT, SCHEMA_MIGRATIONS


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
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reminders)").fetchall()
        }

        for column_name, column_definition in SCHEMA_MIGRATIONS.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE reminders ADD COLUMN {column_definition}"
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
) -> int:
    now = datetime.now().isoformat(timespec="seconds")

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
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
) -> bool:
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
                timezone = ?
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
