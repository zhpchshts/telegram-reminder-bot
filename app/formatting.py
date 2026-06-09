import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.constants import (
    MONTH_NAMES_RU,
    ORDINAL_NAMES_RU,
    WEEKDAY_NAMES_RU_PLURAL,
    WEEKDAY_NAMES_RU_SINGLE,
)


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

    return schedule_type


def format_period_line_from_row(reminder: sqlite3.Row) -> str:
    return format_period_line(
        schedule_type=get_str(reminder, "schedule_type"),
        interval_days=reminder["interval_days"],
        interval_weeks=reminder["interval_weeks"],
        day_of_week=reminder["day_of_week"],
        month_week_number=reminder["month_week_number"],
        month_day=reminder["month_day"],
    )


def format_reminder_for_list(
    reminder: sqlite3.Row,
    next_run_line: str,
    timezone_name: str | None = None,
) -> str:
    reminder_id = get_int(reminder, "id")
    start_at = datetime.fromisoformat(get_str(reminder, "start_at"))
    reminder_timezone = timezone_name or reminder["timezone"]

    return (
        f"#{reminder_id} — {format_period_line_from_row(reminder)}\n"
        f"Первое срабатывание: {format_datetime_ru(start_at, reminder_timezone)}\n"
        f"{next_run_line}\n"
        f"{get_str(reminder, 'text')}"
    )
