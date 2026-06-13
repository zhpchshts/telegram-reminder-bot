from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot

from app.config import APP_TIMEZONE_NAME
from app.constants import VALID_WEEKDAYS
from app.database import (
    create_reminder_in_db,
    get_active_reminder_for_chat,
    get_active_reminders_for_chat,
    get_chat_timezone,
    mark_reminder_as_deleted,
    set_chat_timezone,
    update_reminder_in_db,
)
from app.formatting import (
    format_datetime_ru,
    format_period_line,
    format_reminder_read_data_for_list,
)
from app.reminder_mapping import build_reminder_read_data
from app.reminder_models import ReminderCreateData, ReminderReadData
from app.scheduler import (
    format_next_run_line,
    get_next_run_at,
    scheduler,
    schedule_reminder,
)


def get_chat_timezone_name(chat_id: int) -> str:
    return get_chat_timezone(chat_id) or APP_TIMEZONE_NAME


def set_chat_timezone_for_chat(*, chat_id: int, timezone_name: str) -> bool:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return False

    set_chat_timezone(
        chat_id=chat_id,
        timezone=timezone_name,
    )
    return True


def validate_positive_int(value: int | None, field_name: str) -> None:
    if value is None or value < 1:
        raise ValueError(f"{field_name} must be greater than or equal to 1.")


def validate_day_of_week(day_of_week: str | None) -> None:
    if day_of_week not in VALID_WEEKDAYS:
        raise ValueError("day_of_week is invalid.")


def validate_reminder_create_data(data: ReminderCreateData) -> None:
    if not data.reminder_text.strip():
        raise ValueError("reminder_text is required.")

    if data.schedule_type == "once":
        return

    if data.schedule_type == "every_days":
        validate_positive_int(data.interval_days, "interval_days")
        return

    if data.schedule_type == "every_week":
        validate_positive_int(data.interval_weeks, "interval_weeks")
        validate_day_of_week(data.day_of_week)
        return

    if data.schedule_type == "monthly_weekday":
        if data.month_week_number is None or not 1 <= data.month_week_number <= 5:
            raise ValueError("month_week_number must be between 1 and 5.")

        validate_day_of_week(data.day_of_week)
        return

    if data.schedule_type == "monthly_day":
        if data.month_day is None or not 1 <= data.month_day <= 31:
            raise ValueError("month_day must be between 1 and 31.")

        return

    raise ValueError("Unknown schedule_type.")


def normalize_sort_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_reminder_next_run_sort_key(reminder: ReminderReadData) -> tuple[datetime, int]:
    next_run_at = get_next_run_at(reminder.id)
    sort_at = next_run_at or reminder.start_at

    return normalize_sort_datetime(sort_at), reminder.id


def sort_reminders_by_next_run(
    reminders: list[ReminderReadData],
) -> list[ReminderReadData]:
    return sorted(reminders, key=get_reminder_next_run_sort_key)


def create_scheduled_reminder(
    *,
    bot: Bot,
    chat_id: int,
    data: ReminderCreateData,
) -> int:
    validate_reminder_create_data(data)

    reminder_id = create_reminder_in_db(
        chat_id=chat_id,
        reminder_text=data.reminder_text,
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone=data.timezone_name,
    )

    schedule_reminder(
        bot=bot,
        reminder_id=reminder_id,
        chat_id=chat_id,
        reminder_text=data.reminder_text,
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone_name=data.timezone_name,
    )

    return reminder_id


def update_active_reminder_for_chat(
    *,
    bot: Bot,
    reminder_id: int,
    chat_id: int,
    data: ReminderCreateData,
) -> ReminderReadData | None:
    validate_reminder_create_data(data)

    reminder = get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )
    if not reminder:
        return None

    is_updated = update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=chat_id,
        reminder_text=data.reminder_text,
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone=data.timezone_name,
    )
    if not is_updated:
        return None

    schedule_reminder(
        bot=bot,
        reminder_id=reminder_id,
        chat_id=chat_id,
        reminder_text=data.reminder_text,
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone_name=data.timezone_name,
    )

    updated_reminder = get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )
    if not updated_reminder:
        return None

    return build_reminder_read_data(updated_reminder)


def build_created_reminder_text(
    *,
    reminder_id: int,
    data: ReminderCreateData,
) -> str:
    header = (
        "Одноразовое напоминание создано."
        if data.schedule_type == "once"
        else "Повторяющееся напоминание создано."
    )

    answer_lines = [
        header,
        "",
        f"ID: {reminder_id}",
    ]

    if data.schedule_type != "once":
        answer_lines.append(
            "Период: "
            + format_period_line(
                schedule_type=data.schedule_type,
                interval_days=data.interval_days,
                interval_weeks=data.interval_weeks,
                day_of_week=data.day_of_week,
                month_week_number=data.month_week_number,
                month_day=data.month_day,
            )
        )

    answer_lines.extend(
        [
            f"Таймзона: {data.timezone_name}",
            f"Первое срабатывание: {format_datetime_ru(data.start_at, data.timezone_name)}",
            format_next_run_line(reminder_id, data.timezone_name),
            f"Текст: {data.reminder_text}",
        ]
    )

    return "\n".join(answer_lines)


def delete_active_reminder_for_chat(reminder_id: int, chat_id: int) -> bool:
    reminder = get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )
    if not reminder:
        return False

    job = scheduler.get_job(str(reminder_id))
    if job:
        scheduler.remove_job(str(reminder_id))

    mark_reminder_as_deleted(reminder_id)
    return True


def list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
    reminders = [
        build_reminder_read_data(reminder)
        for reminder in get_active_reminders_for_chat(chat_id)
    ]

    return sort_reminders_by_next_run(reminders)


def build_active_reminders_list_text_for_chat(chat_id: int) -> str | None:
    reminders = list_active_reminders_for_chat(chat_id)
    if not reminders:
        return None

    lines = ["Активные напоминания в этом чате\n"]

    lines.extend(
        format_reminder_read_data_for_list(
            reminder,
            format_next_run_line(reminder.id, reminder.timezone_name),
        )
        for reminder in reminders
    )

    return "\n\n".join(lines)
