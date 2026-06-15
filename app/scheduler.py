import sqlite3
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import APP_TIMEZONE_NAME
from app.constants import APSCHEDULER_WEEKDAYS
from app.database import (
    count_active_chats,
    get_all_active_reminders,
    mark_reminder_as_missed,
    mark_reminder_as_sent,
)
from app.formatting import format_datetime_ru
from app.reminder_mapping import build_reminder_read_data
from app.schedule_calculations import get_month_day_range_for_week_number

scheduler = AsyncIOScheduler()


async def send_healthcheck(
    bot: Bot,
    chat_id: int,
) -> None:
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    active_reminders_count = len(get_all_active_reminders())
    active_chats_count = count_active_chats()
    scheduled_jobs_count = len(scheduler.get_jobs())
    scheduler_status = "running" if scheduler.running else "stopped"

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Бот работает.\n\n"
            f"Время сервера UTC: {now_utc}\n"
            f"Scheduler: {scheduler_status}\n"
            f"Запланированных jobs: {scheduled_jobs_count}\n"
            f"Активных напоминаний в базе: {active_reminders_count}\n"
            f"Чатов с активными напоминаниями: {active_chats_count}"
        ),
    )


def schedule_healthcheck(
    bot: Bot,
    chat_id: int,
    interval_minutes: int,
) -> None:
    scheduler.add_job(
        send_healthcheck,
        trigger="interval",
        minutes=interval_minutes,
        args=[bot, chat_id],
        id="healthcheck",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )


def get_next_run_at(reminder_id: int) -> datetime | None:
    job = scheduler.get_job(str(reminder_id))
    if not job or not job.next_run_time:
        return None

    return job.next_run_time


def format_next_run_line(
    reminder_id: int,
    timezone_name: str | None = None,
) -> str:
    next_run_at = get_next_run_at(reminder_id)
    if not next_run_at:
        return "Следующее срабатывание: не запланировано"

    return f"Следующее срабатывание: {format_datetime_ru(next_run_at, timezone_name)}"


async def send_once_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_id: int,
) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=reminder_text,
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
        text=reminder_text,
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
    month_day: int | None = None,
    timezone_name: str | None = None,
) -> None:
    job_timezone = ZoneInfo(timezone_name or APP_TIMEZONE_NAME)
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
            timezone=job_timezone,
            **job_kwargs,
        )
        return

    if schedule_type == "every_days":
        scheduler.add_job(
            send_repeating_reminder,
            trigger="interval",
            days=interval_days,
            start_date=start_at,
            timezone=job_timezone,
            **job_kwargs,
        )
        return

    if schedule_type == "every_week":
        scheduler.add_job(
            send_repeating_reminder,
            trigger="interval",
            weeks=interval_weeks,
            start_date=start_at,
            timezone=job_timezone,
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
            timezone=job_timezone,
            **job_kwargs,
        )
        return

    if schedule_type == "monthly_day":
        if month_day is None:
            raise ValueError("month_day is required.")

        scheduler.add_job(
            send_repeating_reminder,
            trigger="cron",
            day=month_day,
            hour=start_at.hour,
            minute=start_at.minute,
            start_date=start_at,
            timezone=job_timezone,
            **job_kwargs,
        )
        return

    if schedule_type == "yearly_date":
        scheduler.add_job(
            send_repeating_reminder,
            trigger="cron",
            month=start_at.month,
            day=start_at.day,
            hour=start_at.hour,
            minute=start_at.minute,
            start_date=start_at,
            timezone=job_timezone,
            **job_kwargs,
        )
        return

    raise ValueError(f"Unknown schedule_type: {schedule_type}")


def schedule_reminder_from_row(bot: Bot, reminder: sqlite3.Row) -> None:
    reminder_data = build_reminder_read_data(reminder)
    schedule_reminder(
        bot=bot,
        reminder_id=reminder_data.id,
        chat_id=reminder_data.chat_id,
        reminder_text=reminder_data.reminder_text,
        schedule_type=reminder_data.schedule_type,
        start_at=reminder_data.start_at,
        interval_days=reminder_data.interval_days,
        interval_weeks=reminder_data.interval_weeks,
        day_of_week=reminder_data.day_of_week,
        month_week_number=reminder_data.month_week_number,
        month_day=reminder_data.month_day,
        timezone_name=reminder_data.timezone_name,
    )


async def restore_active_reminders(bot: Bot) -> None:
    now = datetime.now()
    restored_count = 0
    missed_count = 0

    for reminder in get_all_active_reminders():
        reminder_data = build_reminder_read_data(reminder)

        if reminder_data.schedule_type == "once" and reminder_data.start_at <= now:
            mark_reminder_as_missed(reminder_data.id)
            missed_count += 1
            continue

        schedule_reminder_from_row(bot, reminder)
        restored_count += 1

    print(f"Restored reminders: {restored_count}. Missed reminders: {missed_count}.")
