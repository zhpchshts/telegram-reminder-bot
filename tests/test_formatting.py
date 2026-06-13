import sqlite3
from datetime import datetime
from app.reminder_models import ReminderReadData

from app.formatting import (
    format_datetime_ru,
    format_period_line,
    format_reminder_for_list,
    format_reminder_read_data_for_list,
)


def make_reminder_row(
    *,
    reminder_id: int = 1,
    chat_id: int = 100,
    text: str = "Тестовое напоминание",
    schedule_type: str = "once",
    start_at: str = "2026-06-08T12:12:00",
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone: str | None = "Asia/Yekaterinburg",
) -> sqlite3.Row:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    return connection.execute(
        """
        SELECT
            ? AS id,
            ? AS chat_id,
            ? AS text,
            ? AS schedule_type,
            'active' AS status,
            ? AS start_at,
            ? AS interval_days,
            ? AS interval_weeks,
            ? AS day_of_week,
            ? AS month_week_number,
            ? AS month_day,
            ? AS timezone
        """,
        (
            reminder_id,
            chat_id,
            text,
            schedule_type,
            start_at,
            interval_days,
            interval_weeks,
            day_of_week,
            month_week_number,
            month_day,
            timezone,
        ),
    ).fetchone()


def test_format_datetime_ru() -> None:
    result = format_datetime_ru(datetime(2026, 6, 8, 12, 12))

    assert result == "08 июня в 12:12"


def test_format_period_line_once() -> None:
    result = format_period_line(schedule_type="once")

    assert result == "один раз"


def test_format_period_line_every_days() -> None:
    result = format_period_line(
        schedule_type="every_days",
        interval_days=3,
    )

    assert result == "каждые 3 дн."


def test_format_period_line_every_week() -> None:
    result = format_period_line(
        schedule_type="every_week",
        interval_weeks=2,
        day_of_week="SUN",
    )

    assert result == "каждые 2 нед. по воскресеньям"


def test_format_period_line_monthly_weekday() -> None:
    result = format_period_line(
        schedule_type="monthly_weekday",
        month_week_number=1,
        day_of_week="MON",
    )

    assert result == "каждый 1-й понедельник месяца"


def test_format_reminder_for_list_once() -> None:
    reminder = make_reminder_row(
        reminder_id=10,
        text="Тест once",
        schedule_type="once",
        start_at="2026-06-08T12:12:00",
    )

    result = format_reminder_for_list(
        reminder,
        "Следующее срабатывание: 08 июня в 12:12",
    )

    assert result == (
        "<b>Тест once</b>\n"
        "ID: <code>10</code>\n"
        "Период: один раз\n"
        "Первое срабатывание: 08 июня в 12:12\n"
        "Следующее срабатывание: 08 июня в 12:12\n"
        "Таймзона: <code>Asia/Yekaterinburg</code>"
    )


def test_format_reminder_for_list_every_days() -> None:
    reminder = make_reminder_row(
        reminder_id=11,
        text="Тест every days",
        schedule_type="every_days",
        start_at="2026-06-08T12:12:00",
        interval_days=3,
    )

    result = format_reminder_for_list(
        reminder,
        "Следующее срабатывание: 11 июня в 12:12",
    )

    assert result == (
        "<b>Тест every days</b>\n"
        "ID: <code>11</code>\n"
        "Период: каждые 3 дн.\n"
        "Первое срабатывание: 08 июня в 12:12\n"
        "Следующее срабатывание: 11 июня в 12:12\n"
        "Таймзона: <code>Asia/Yekaterinburg</code>"
    )


def test_format_period_line_monthly_day() -> None:
    result = format_period_line(
        schedule_type="monthly_day",
        month_day=11,
    )

    assert result == "каждый месяц 11 числа"


def test_format_reminder_read_data_for_list_every_days() -> None:
    reminder = ReminderReadData(
        id=11,
        chat_id=100,
        reminder_text="<b>Тест every days</b>",
        schedule_type="every_days",
        start_at=datetime(2026, 6, 8, 12, 12),
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )

    result = format_reminder_read_data_for_list(
        reminder,
        "Следующее срабатывание: 11 июня в 12:12",
    )

    assert result == (
        "&lt;b&gt;Тест every days&lt;/b&gt;\n"
        "ID: `11`\n"
        "Период: каждые 3 дн.\n"
        "Первое срабатывание: 08 июня в 12:12\n"
        "Следующее срабатывание: 11 июня в 12:12\n"
        "Таймзона: `Asia/Yekaterinburg`"
    )
