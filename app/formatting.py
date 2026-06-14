import html
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.constants import (
    MONTH_NAMES_RU,
    ORDINAL_NAMES_RU,
    WEEKDAY_NAMES_RU_PLURAL,
    WEEKDAY_NAMES_RU_SINGLE,
)
from app.reminder_models import ReminderReadData


def format_datetime_ru(
    value: datetime,
    timezone_name: str | None = None,
) -> str:
    display_value = value
    if timezone_name and value.tzinfo is not None:
        display_value = value.astimezone(ZoneInfo(timezone_name))

    display_value = display_value.replace(tzinfo=None)
    month_name = MONTH_NAMES_RU[display_value.month]
    return f"{display_value.day:02d} {month_name} в {display_value.strftime('%H:%M')}"


def get_int(row: sqlite3.Row, key: str) -> int:
    return int(row[key])


def get_str(row: sqlite3.Row, key: str) -> str:
    return str(row[key])


def format_period_line(
    *,
    schedule_type: str,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    start_at: datetime | None = None,
) -> str:
    if schedule_type == "once":
        return "один раз"

    if schedule_type == "every_days":
        return f"каждые {interval_days} дн."

    if schedule_type == "every_week":
        weekday_name = WEEKDAY_NAMES_RU_PLURAL.get(str(day_of_week), str(day_of_week))
        return f"каждые {interval_weeks} нед. по {weekday_name}"

    if schedule_type == "monthly_weekday":
        ordinal_name = ORDINAL_NAMES_RU.get(
            int(month_week_number),
            str(month_week_number),
        )
        weekday_name = WEEKDAY_NAMES_RU_SINGLE.get(str(day_of_week), str(day_of_week))
        return f"каждый {ordinal_name} {weekday_name} месяца"

    if schedule_type == "monthly_day":
        return f"каждый месяц {month_day} числа"

    if schedule_type == "yearly_date":
        if start_at is None:
            return "каждый год"

        month_name = MONTH_NAMES_RU[start_at.month]
        return f"каждый год {start_at.day} {month_name}"

    return schedule_type


def format_reminder_read_data_for_list(
    reminder: ReminderReadData,
    next_run_line: str,
) -> str:
    reminder_text = html.escape(reminder.reminder_text)
    period = html.escape(
        format_period_line(
            schedule_type=reminder.schedule_type,
            interval_days=reminder.interval_days,
            interval_weeks=reminder.interval_weeks,
            day_of_week=reminder.day_of_week,
            month_week_number=reminder.month_week_number,
            month_day=reminder.month_day,
            start_at=reminder.start_at
            if reminder.schedule_type == "yearly_date"
            else None,
        )
    )
    first_run = html.escape(
        format_datetime_ru(reminder.start_at, reminder.timezone_name)
    )
    next_run = html.escape(next_run_line)
    timezone_name = html.escape(reminder.timezone_name)

    return (
        f"<b>{reminder_text}</b>\n"
        f"ID: `{reminder.id}`\n"
        f"Период: {period}\n"
        f"Первое срабатывание: {first_run}\n"
        f"{next_run}\n"
        f"Таймзона: `{timezone_name}`"
    )
