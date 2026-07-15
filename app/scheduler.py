import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import Message
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
    delete_reminder_message_deletion,
    delete_expired_prepared_weather_reports,
    delete_prepared_weather_report,
    enqueue_reminder_message_deletion,
    get_all_active_reminders,
    get_due_reminder_message_deletions,
    get_prepared_weather_report,
    mark_reminder_as_missed,
    mark_reminder_as_sent,
    reschedule_reminder_message_deletion,
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
MESSAGE_DELETION_DELAY = timedelta(hours=47, minutes=45)
MESSAGE_DELETION_MAX_AGE = timedelta(hours=48)
MESSAGE_DELETION_RETRY_DELAY = timedelta(minutes=1)
MESSAGE_DELETION_BATCH_SIZE = 100
MESSAGE_DELETION_ENQUEUE_ATTEMPTS = 3
MESSAGE_DELETION_ENQUEUE_RETRY_DELAY_SECONDS = 0.05
MESSAGE_DELETION_ERROR_MAX_LENGTH = 1000


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
                target_time_utc=scheduled_for,
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
) -> Message:
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

        sent_message = await bot.send_message(
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

        return sent_message

    message = build_reminder_message(reminder_text, reminder_kind)

    return await bot.send_message(
        chat_id=chat_id,
        text=message,
    )


def get_message_sent_at_utc(message: Message) -> datetime:
    sent_at = message.date
    if sent_at.tzinfo is None or sent_at.tzinfo.utcoffset(sent_at) is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)

    return sent_at.astimezone(timezone.utc)


async def enqueue_sent_reminder_message_for_deletion(
    *,
    reminder_id: int,
    chat_id: int,
    message: Message,
    delete_after_two_days: bool,
) -> None:
    if not delete_after_two_days:
        return

    sent_at = get_message_sent_at_utc(message)
    delete_at = sent_at + MESSAGE_DELETION_DELAY

    for attempt in range(1, MESSAGE_DELETION_ENQUEUE_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(
                enqueue_reminder_message_deletion,
                reminder_id=reminder_id,
                chat_id=chat_id,
                message_id=message.message_id,
                sent_at=sent_at,
                delete_at=delete_at,
            )
            return
        except sqlite3.Error:
            if attempt == MESSAGE_DELETION_ENQUEUE_ATTEMPTS:
                LOGGER.exception(
                    (
                        "Reminder message deletion enqueue failed permanently: "
                        "reminder_id=%s chat_id=%s message_id=%s attempts=%s"
                    ),
                    reminder_id,
                    chat_id,
                    message.message_id,
                    attempt,
                )
                return

            LOGGER.warning(
                (
                    "Reminder message deletion enqueue failed, retrying: "
                    "reminder_id=%s chat_id=%s message_id=%s attempt=%s"
                ),
                reminder_id,
                chat_id,
                message.message_id,
                attempt,
                exc_info=True,
            )
            await asyncio.sleep(MESSAGE_DELETION_ENQUEUE_RETRY_DELAY_SECONDS * attempt)


async def send_once_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str,
    reminder_id: int,
    delete_after_two_days: bool = False,
) -> None:
    sent_message = await send_reminder_message(
        bot=bot,
        chat_id=chat_id,
        reminder_text=reminder_text,
        reminder_kind=reminder_kind,
        reminder_id=reminder_id,
    )
    await enqueue_sent_reminder_message_for_deletion(
        reminder_id=reminder_id,
        chat_id=chat_id,
        message=sent_message,
        delete_after_two_days=delete_after_two_days,
    )
    mark_reminder_as_sent(reminder_id)


async def send_repeating_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_kind: str,
    reminder_id: int,
    delete_after_two_days: bool = False,
) -> None:
    sent_message = await send_reminder_message(
        bot=bot,
        chat_id=chat_id,
        reminder_text=reminder_text,
        reminder_kind=reminder_kind,
        reminder_id=reminder_id,
    )
    await enqueue_sent_reminder_message_for_deletion(
        reminder_id=reminder_id,
        chat_id=chat_id,
        message=sent_message,
        delete_after_two_days=delete_after_two_days,
    )


def parse_utc_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def is_message_not_found_error(error: TelegramAPIError) -> bool:
    if isinstance(error, TelegramNotFound):
        return True

    return isinstance(error, TelegramBadRequest) and (
        "message to delete not found" in error.message.casefold()
    )


async def remove_reminder_message_deletion(queue_id: int) -> None:
    try:
        await asyncio.to_thread(delete_reminder_message_deletion, queue_id)
    except sqlite3.Error:
        LOGGER.exception(
            "Could not remove reminder message deletion queue item: queue_id=%s",
            queue_id,
        )


async def retry_reminder_message_deletion(
    row: sqlite3.Row,
    *,
    now: datetime,
    expires_at: datetime,
    error: Exception,
    retry_after_seconds: int | None = None,
) -> None:
    retry_delay = (
        timedelta(seconds=max(retry_after_seconds, 1))
        if retry_after_seconds is not None
        else MESSAGE_DELETION_RETRY_DELAY
    )
    next_attempt_at = now + retry_delay
    queue_id = int(row["id"])

    if next_attempt_at >= expires_at:
        LOGGER.warning(
            (
                "Reminder message deletion retry window exhausted: "
                "queue_id=%s reminder_id=%s chat_id=%s message_id=%s error=%s"
            ),
            queue_id,
            row["reminder_id"],
            row["chat_id"],
            row["message_id"],
            error,
        )
        await remove_reminder_message_deletion(queue_id)
        return

    try:
        await asyncio.to_thread(
            reschedule_reminder_message_deletion,
            queue_id=queue_id,
            delete_attempts=int(row["delete_attempts"]) + 1,
            next_attempt_at=next_attempt_at,
            last_error=str(error)[:MESSAGE_DELETION_ERROR_MAX_LENGTH],
        )
    except sqlite3.Error:
        LOGGER.exception(
            (
                "Could not reschedule reminder message deletion: "
                "queue_id=%s reminder_id=%s chat_id=%s message_id=%s"
            ),
            queue_id,
            row["reminder_id"],
            row["chat_id"],
            row["message_id"],
        )


async def process_reminder_message_deletion(bot: Bot, row: sqlite3.Row) -> None:
    queue_id = int(row["id"])

    try:
        sent_at = parse_utc_datetime(row["sent_at_utc"])
        delete_at = parse_utc_datetime(row["delete_at_utc"])
    except (TypeError, ValueError):
        LOGGER.warning(
            "Dropping reminder message deletion with invalid timestamps: queue_id=%s",
            queue_id,
            exc_info=True,
        )
        await remove_reminder_message_deletion(queue_id)
        return

    now = datetime.now(timezone.utc)
    expires_at = sent_at + MESSAGE_DELETION_MAX_AGE

    if now < delete_at:
        try:
            await asyncio.to_thread(
                reschedule_reminder_message_deletion,
                queue_id=queue_id,
                delete_attempts=int(row["delete_attempts"]),
                next_attempt_at=delete_at,
                last_error=str(row["last_error"] or ""),
            )
        except sqlite3.Error:
            LOGGER.exception(
                "Could not restore reminder message deletion time: queue_id=%s",
                queue_id,
            )
        return

    if now >= expires_at:
        LOGGER.warning(
            (
                "Reminder message deletion expired before Telegram deadline: "
                "queue_id=%s reminder_id=%s chat_id=%s message_id=%s"
            ),
            queue_id,
            row["reminder_id"],
            row["chat_id"],
            row["message_id"],
        )
        await remove_reminder_message_deletion(queue_id)
        return

    try:
        await bot.delete_message(
            chat_id=int(row["chat_id"]),
            message_id=int(row["message_id"]),
        )
    except TelegramRetryAfter as error:
        await retry_reminder_message_deletion(
            row,
            now=now,
            expires_at=expires_at,
            error=error,
            retry_after_seconds=error.retry_after,
        )
    except (TelegramNetworkError, TelegramServerError) as error:
        await retry_reminder_message_deletion(
            row,
            now=now,
            expires_at=expires_at,
            error=error,
        )
    except TelegramAPIError as error:
        if is_message_not_found_error(error):
            LOGGER.info(
                (
                    "Reminder message was already deleted: "
                    "queue_id=%s chat_id=%s message_id=%s"
                ),
                queue_id,
                row["chat_id"],
                row["message_id"],
            )
        elif isinstance(
            error,
            (
                TelegramBadRequest,
                TelegramForbiddenError,
                TelegramUnauthorizedError,
            ),
        ):
            LOGGER.warning(
                (
                    "Terminal Telegram error deleting reminder message: "
                    "queue_id=%s reminder_id=%s chat_id=%s message_id=%s error=%s"
                ),
                queue_id,
                row["reminder_id"],
                row["chat_id"],
                row["message_id"],
                error,
            )
        else:
            LOGGER.warning(
                (
                    "Unhandled Telegram API error deleting reminder message: "
                    "queue_id=%s reminder_id=%s chat_id=%s message_id=%s error=%s"
                ),
                queue_id,
                row["reminder_id"],
                row["chat_id"],
                row["message_id"],
                error,
            )

        await remove_reminder_message_deletion(queue_id)
    except Exception as error:
        LOGGER.exception(
            (
                "Unexpected error deleting reminder message: "
                "queue_id=%s reminder_id=%s chat_id=%s message_id=%s"
            ),
            queue_id,
            row["reminder_id"],
            row["chat_id"],
            row["message_id"],
        )
        await retry_reminder_message_deletion(
            row,
            now=now,
            expires_at=expires_at,
            error=error,
        )
    else:
        await remove_reminder_message_deletion(queue_id)


async def cleanup_reminder_message_deletion_queue(bot: Bot) -> None:
    now = datetime.now(timezone.utc)

    try:
        rows = await asyncio.to_thread(
            get_due_reminder_message_deletions,
            now,
            limit=MESSAGE_DELETION_BATCH_SIZE,
        )
    except sqlite3.Error:
        LOGGER.exception("Could not load due reminder message deletions.")
        return

    for row in rows:
        try:
            await process_reminder_message_deletion(bot, row)
        except Exception:
            LOGGER.exception(
                "Reminder message deletion item failed unexpectedly: queue_id=%s",
                row["id"],
            )


def schedule_reminder_message_deletion_cleanup(bot: Bot) -> None:
    scheduler.add_job(
        cleanup_reminder_message_deletion_queue,
        trigger="interval",
        minutes=1,
        args=[bot],
        id="reminder-message-deletion-cleanup",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
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
    delete_after_two_days: bool = False,
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
        "args": [
            bot,
            chat_id,
            reminder_text,
            reminder_kind,
            reminder_id,
            delete_after_two_days,
        ],
        "id": str(reminder_id),
        "replace_existing": True,
        "max_instances": 1,
        "coalesce": True,
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
        delete_after_two_days=reminder_data.delete_after_two_days,
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
    schedule_reminder_message_deletion_cleanup(bot)
    print(f"Restored reminders: {restored_count}. Missed reminders: {missed_count}.")
