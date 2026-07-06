import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import APP_TIMEZONE_NAME
from app.constants import (
    APSCHEDULER_WEEKDAYS,
    REMINDER_KIND_TEXT,
    REMINDER_KIND_WEATHER,
)
from app.database import (
    count_active_chats,
    delete_expired_prepared_weather_reports,
    delete_prepared_weather_report,
    get_all_active_reminders,
    get_prepared_weather_report,
    mark_reminder_as_missed,
    mark_reminder_as_sent,
    save_prepared_weather_report,
)
from app.formatting import format_datetime_ru
from app.reminder_mapping import build_reminder_read_data
from app.schedule_calculations import get_month_day_range_for_week_number
from app.weather_service import WeatherServiceError, build_weather_report

scheduler = AsyncIOScheduler()
LOGGER = logging.getLogger(__name__)

WEATHER_PREFETCH_WINDOW = timedelta(minutes=5)
WEATHER_REPORT_CACHE_RETENTION = timedelta(minutes=10)
WEATHER_REPORT_CACHE_LOOKUP_GRACE = timedelta(minutes=1)


def ensure_timezone_aware(
    value: datetime,
    timezone_name: str | None = None,
) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=ZoneInfo(timezone_name or APP_TIMEZONE_NAME))

    return value


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


def schedule_weather_report_prefetch() -> None:
    scheduler.add_job(
        prefetch_weather_reports,
        trigger="interval",
        minutes=1,
        id="weather-report-prefetch",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
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


def build_reminder_message(reminder_text: str, reminder_kind: str) -> str:
    if reminder_kind != REMINDER_KIND_WEATHER:
        return reminder_text

    try:
        return build_weather_report(reminder_text)
    except ValueError as error:
        return f"Не смог подготовить прогноз погоды.\n{error}"
    except WeatherServiceError as error:
        return f"Не смог получить прогноз погоды.\n{error}"


async def prefetch_weather_reports() -> None:
    now = datetime.now(timezone.utc)

    await asyncio.to_thread(
        delete_expired_prepared_weather_reports,
        now - WEATHER_REPORT_CACHE_RETENTION,
    )

    for reminder in get_all_active_reminders():
        reminder_data = build_reminder_read_data(reminder)

        if reminder_data.reminder_kind != REMINDER_KIND_WEATHER:
            continue

        next_run_at = get_next_run_at(reminder_data.id)

        if next_run_at is None:
            continue

        scheduled_for = next_run_at.astimezone(timezone.utc)

        if not now <= scheduled_for <= now + WEATHER_PREFETCH_WINDOW:
            continue

        prepared_report = await asyncio.to_thread(
            get_prepared_weather_report,
            reminder_data.id,
            reminder_data.reminder_text,
            scheduled_for - timedelta(seconds=1),
            scheduled_for + timedelta(seconds=1),
        )

        if prepared_report is not None:
            continue

        try:
            report_html = await asyncio.to_thread(
                build_weather_report,
                reminder_data.reminder_text,
                raise_on_error=True,
                request_attempts=1,
            )
        except (ValueError, WeatherServiceError) as error:
            LOGGER.warning(
                (
                    "Weather report prefetch failed: reminder_id=%s "
                    "scheduled_for=%s error=%s"
                ),
                reminder_data.id,
                scheduled_for.isoformat(timespec="seconds"),
                error,
            )
            continue

        await asyncio.to_thread(
            save_prepared_weather_report,
            reminder_data.id,
            scheduled_for,
            reminder_data.reminder_text,
            report_html,
        )


async def send_reminder_message(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str,
    reminder_id: int,
) -> None:
    if reminder_kind == REMINDER_KIND_WEATHER:
        now = datetime.now(timezone.utc)

        prepared_report = await asyncio.to_thread(
            get_prepared_weather_report,
            reminder_id,
            reminder_text,
            now - WEATHER_REPORT_CACHE_LOOKUP_GRACE,
            now + WEATHER_REPORT_CACHE_LOOKUP_GRACE,
        )

        if prepared_report is None:
            message = await asyncio.to_thread(
                build_reminder_message,
                reminder_text,
                reminder_kind,
            )
        else:
            message = prepared_report["report_html"]

        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML",
        )

        if prepared_report is not None:
            await asyncio.to_thread(
                delete_prepared_weather_report,
                reminder_id,
                prepared_report["scheduled_for_utc"],
            )

        return

    message = build_reminder_message(reminder_text, reminder_kind)

    await bot.send_message(
        chat_id=chat_id,
        text=message,
    )


async def send_once_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str,
    reminder_id: int,
) -> None:
    await send_reminder_message(
        bot=bot,
        chat_id=chat_id,
        reminder_text=reminder_text,
        reminder_kind=reminder_kind,
        reminder_id=reminder_id,
    )
    mark_reminder_as_sent(reminder_id)


async def send_repeating_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str,
    reminder_id: int,
) -> None:
    await send_reminder_message(
        bot=bot,
        chat_id=chat_id,
        reminder_text=reminder_text,
        reminder_kind=reminder_kind,
        reminder_id=reminder_id,
    )


def build_reminder_trigger_kwargs(
    *,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    job_timezone = ZoneInfo(timezone_name or APP_TIMEZONE_NAME)

    if schedule_type == "once":
        return {
            "trigger": "date",
            "run_date": start_at,
            "timezone": job_timezone,
        }

    if schedule_type == "every_days":
        return {
            "trigger": "interval",
            "days": interval_days,
            "start_date": start_at,
            "timezone": job_timezone,
        }

    if schedule_type == "every_week":
        return {
            "trigger": "interval",
            "weeks": interval_weeks,
            "start_date": start_at,
            "timezone": job_timezone,
        }

    if schedule_type == "monthly_weekday":
        if month_week_number is None or day_of_week is None:
            raise ValueError("month_week_number and day_of_week are required.")

        return {
            "trigger": "cron",
            "day": get_month_day_range_for_week_number(month_week_number),
            "day_of_week": APSCHEDULER_WEEKDAYS[day_of_week],
            "hour": start_at.hour,
            "minute": start_at.minute,
            "start_date": start_at,
            "timezone": job_timezone,
        }

    if schedule_type == "monthly_day":
        if month_day is None:
            raise ValueError("month_day is required.")

        return {
            "trigger": "cron",
            "day": month_day,
            "hour": start_at.hour,
            "minute": start_at.minute,
            "start_date": start_at,
            "timezone": job_timezone,
        }

    if schedule_type == "yearly_date":
        return {
            "trigger": "cron",
            "month": start_at.month,
            "day": start_at.day,
            "hour": start_at.hour,
            "minute": start_at.minute,
            "start_date": start_at,
            "timezone": job_timezone,
        }

    raise ValueError(f"Unknown schedule_type: {schedule_type}")


def build_reminder_trigger(
    *,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone_name: str | None = None,
):
    trigger_kwargs = build_reminder_trigger_kwargs(
        schedule_type=schedule_type,
        start_at=start_at,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
        month_day=month_day,
        timezone_name=timezone_name,
    )
    trigger_type = trigger_kwargs.pop("trigger")

    if trigger_type == "date":
        return DateTrigger(**trigger_kwargs)

    if trigger_type == "interval":
        return IntervalTrigger(**trigger_kwargs)

    return CronTrigger(**trigger_kwargs)


def get_next_run_at_for_schedule(
    *,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> datetime | None:
    job_timezone = ZoneInfo(timezone_name or APP_TIMEZONE_NAME)

    if now is None:
        current_time = datetime.now(job_timezone)
    elif now.tzinfo is None:
        current_time = now.replace(tzinfo=job_timezone)
    else:
        current_time = now.astimezone(job_timezone)

    trigger = build_reminder_trigger(
        schedule_type=schedule_type,
        start_at=start_at,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
        month_day=month_day,
        timezone_name=timezone_name,
    )

    return trigger.get_next_fire_time(None, current_time)


def schedule_reminder(
    *,
    bot: Bot,
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
    timezone_name: str | None = None,
) -> None:
    job_kwargs: dict[str, Any] = {
        "args": [bot, chat_id, reminder_text, reminder_kind, reminder_id],
        "id": str(reminder_id),
        "replace_existing": True,
    }
    trigger_kwargs = build_reminder_trigger_kwargs(
        schedule_type=schedule_type,
        start_at=start_at,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
        month_day=month_day,
        timezone_name=timezone_name,
    )
    reminder_function = (
        send_once_reminder if schedule_type == "once" else send_repeating_reminder
    )

    scheduler.add_job(
        reminder_function,
        **trigger_kwargs,
        **job_kwargs,
    )


def schedule_reminder_from_row(bot: Bot, reminder: sqlite3.Row) -> None:
    reminder_data = build_reminder_read_data(reminder)
    schedule_reminder(
        bot=bot,
        reminder_id=reminder_data.id,
        chat_id=reminder_data.chat_id,
        reminder_text=reminder_data.reminder_text,
        reminder_kind=reminder_data.reminder_kind,
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
    now = datetime.now(timezone.utc)
    restored_count = 0
    missed_count = 0

    for reminder in get_all_active_reminders():
        reminder_data = build_reminder_read_data(reminder)
        start_at = ensure_timezone_aware(
            reminder_data.start_at,
            reminder_data.timezone_name,
        )

        if reminder_data.schedule_type == "once" and start_at <= now:
            mark_reminder_as_missed(reminder_data.id)
            missed_count += 1
            continue

        schedule_reminder_from_row(bot, reminder)
        restored_count += 1
    schedule_weather_report_prefetch()
    print(f"Restored reminders: {restored_count}. Missed reminders: {missed_count}.")
