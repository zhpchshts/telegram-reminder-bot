import sqlite3
from datetime import datetime
from typing import Any

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.constants import APSCHEDULER_WEEKDAYS
from app.database import (
    get_all_active_reminders,
    mark_reminder_as_missed,
    mark_reminder_as_sent,
)
from app.formatting import format_datetime_ru, get_int, get_str
from app.schedule_calculations import (
    get_month_day_range_for_week_number,
    normalize_datetime,
)


scheduler = AsyncIOScheduler()


def get_next_run_at(reminder_id: int) -> datetime | None:
    job = scheduler.get_job(str(reminder_id))

    if not job or not job.next_run_time:
        return None

    return normalize_datetime(job.next_run_time)


def format_next_run_line(reminder_id: int) -> str:
    next_run_at = get_next_run_at(reminder_id)

    if not next_run_at:
        return "Следующее срабатывание: не запланировано"

    return f"Следующее срабатывание: {format_datetime_ru(next_run_at)}"


async def send_once_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_id: int,
) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=f"Напоминание #{reminder_id}:\n\n{reminder_text}",
    )

    mark_reminder_as_sent(reminder_id)


async def send_repeating_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_id: int,
) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=f"Повторяющееся напоминание #{reminder_id}:\n\n{reminder_text}",
    )


def schedule_reminder(
    *,
    bot: Bot,
    reminder_id: int,
    chat_id: int,
    reminder_text: str,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
) -> None:
    job_kwargs: dict[str, Any] = {
        "args": [bot, chat_id, reminder_text, reminder_id],
        "id": str(reminder_id),
        "replace_existing": True,
    }

    if schedule_type == "once":
        scheduler.add_job(
            send_once_reminder,
            trigger="date",
            run_date=start_at,
            **job_kwargs,
        )
        return

    if schedule_type == "every_days":
        scheduler.add_job(
            send_repeating_reminder,
            trigger="interval",
            days=interval_days,
            start_date=start_at,
            **job_kwargs,
        )
        return

    if schedule_type == "every_week":
        scheduler.add_job(
            send_repeating_reminder,
            trigger="interval",
            weeks=interval_weeks,
            start_date=start_at,
            **job_kwargs,
        )
        return

    if schedule_type == "monthly_weekday":
        if month_week_number is None or day_of_week is None:
            raise ValueError("month_week_number and day_of_week are required.")

        scheduler.add_job(
            send_repeating_reminder,
            trigger="cron",
            day=get_month_day_range_for_week_number(month_week_number),
            day_of_week=APSCHEDULER_WEEKDAYS[day_of_week],
            hour=start_at.hour,
            minute=start_at.minute,
            start_date=start_at,
            **job_kwargs,
        )
        return

    raise ValueError(f"Unknown schedule_type: {schedule_type}")


def schedule_reminder_from_row(bot: Bot, reminder: sqlite3.Row) -> None:
    schedule_reminder(
        bot=bot,
        reminder_id=get_int(reminder, "id"),
        chat_id=get_int(reminder, "chat_id"),
        reminder_text=get_str(reminder, "text"),
        schedule_type=get_str(reminder, "schedule_type"),
        start_at=datetime.fromisoformat(get_str(reminder, "start_at")),
        interval_days=reminder["interval_days"],
        interval_weeks=reminder["interval_weeks"],
        day_of_week=reminder["day_of_week"],
        month_week_number=reminder["month_week_number"],
    )


async def restore_active_reminders(bot: Bot) -> None:
    now = datetime.now()
    restored_count = 0
    missed_count = 0

    for reminder in get_all_active_reminders():
        reminder_id = get_int(reminder, "id")
        schedule_type = get_str(reminder, "schedule_type")
        start_at = datetime.fromisoformat(get_str(reminder, "start_at"))

        if schedule_type == "once" and start_at <= now:
            mark_reminder_as_missed(reminder_id)
            missed_count += 1
            continue

        schedule_reminder_from_row(bot, reminder)
        restored_count += 1

    print(f"Restored reminders: {restored_count}. Missed reminders: {missed_count}.")
