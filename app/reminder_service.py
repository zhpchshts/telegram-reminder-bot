from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from aiogram import Bot
from app.config import APP_TIMEZONE_NAME
from app.database import (
    get_active_reminder_for_chat,
    get_active_reminders_for_chat,
    get_chat_timezone,
    mark_reminder_as_deleted,
    create_reminder_in_db,
    set_chat_timezone,
)
from app.formatting import (
    format_datetime_ru,
    format_period_line,
    format_reminder_for_list,
    get_int,
)

from app.reminder_models import ReminderCreateData
from app.scheduler import format_next_run_line, scheduler, schedule_reminder


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


def create_scheduled_reminder(
    *,
    bot: Bot,
    chat_id: int,
    data: ReminderCreateData,
) -> int:
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


def build_active_reminders_list_text_for_chat(chat_id: int) -> str | None:
    reminders = get_active_reminders_for_chat(chat_id)

    if not reminders:
        return None

    lines = ["Активные напоминания в этом чате\n"]

    lines.extend(
        format_reminder_for_list(
            reminder,
            format_next_run_line(get_int(reminder, "id")),
        )
        for reminder in reminders
    )

    return "\n\n".join(lines)
