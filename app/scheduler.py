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
from app.completion_service import (
    deliver_completion_occurrence,
    process_due_completion_occurrences,
)
from app.constants import (
    APSCHEDULER_WEEKDAYS,
    MESSAGE_DELETION_DELAY,
    REMINDER_KIND_TEXT,
    REMINDER_KIND_WEATHER,
)
from app.database import (
    count_active_chats,
    delete_reminder_message_deletion,
    delete_expired_prepared_weather_reports,
    delete_prepared_weather_report,
    enqueue_reminder_message_deletion,
    get_active_reminder_from_db,
    get_all_active_reminders,
    get_due_reminder_message_deletions,
    get_prepared_weather_report,
    get_reminder_occurrence_handling_state,
    mark_reminder_as_missed,
    mark_reminder_occurrence_handled,
    reschedule_reminder_message_deletion,
    save_prepared_weather_report,
)
from app.formatting import format_datetime_ru
from app.reminder_mapping import build_reminder_read_data, parse_utc_datetime
from app.reminder_models import ReminderReadData
from app.schedule_calculations import get_month_day_range_for_week_number
from app.weather_service import WeatherServiceError, build_weather_report

scheduler = AsyncIOScheduler()
LOGGER = logging.getLogger(__name__)

WEATHER_PREFETCH_WINDOW = timedelta(minutes=5)
WEATHER_REPORT_CACHE_RETENTION = timedelta(minutes=10)
WEATHER_REPORT_CACHE_LOOKUP_GRACE = timedelta(minutes=1)
WEATHER_CATCHUP_MAX_AGE = timedelta(hours=6)
LATE_REMINDER_NOTICE_THRESHOLD = timedelta(minutes=5)
REMINDER_OCCURRENCE_SEARCH_LIMIT = 100_000
MESSAGE_DELETION_MAX_AGE = timedelta(hours=48)
MESSAGE_DELETION_RETRY_DELAY = timedelta(minutes=1)
MESSAGE_DELETION_BATCH_SIZE = 100
MESSAGE_DELETION_ENQUEUE_ATTEMPTS = 3
MESSAGE_DELETION_ENQUEUE_RETRY_DELAY_SECONDS = 0.05
MESSAGE_DELETION_ERROR_MAX_LENGTH = 1000
DELIVERY_OUTCOME_SENT = "sent"
DELIVERY_OUTCOME_SENT_UNRECORDED = "sent_unrecorded"
DELIVERY_OUTCOME_STALE_WEATHER_SKIPPED = "stale_weather_skipped"
DELIVERY_OUTCOME_STALE_WEATHER_UNRECORDED = "stale_weather_unrecorded"
REMINDER_RESTORE_CATCHUP_LIMIT = 100


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
    *,
    use_prepared_weather_report: bool = True,
    message_prefix: str = "",
) -> Message:
    if reminder_kind == REMINDER_KIND_WEATHER:
        now = datetime.now(timezone.utc)
        prepared_report = None

        if use_prepared_weather_report:
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
            text=f"{message_prefix}{message}",
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
        text=f"{message_prefix}{message}",
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


def build_late_reminder_notice(
    reminder: ReminderReadData,
    scheduled_for_utc: datetime,
) -> str:
    scheduled_for = format_datetime_ru(
        scheduled_for_utc,
        reminder.timezone_name,
    )
    return f"⚠️ Доставлено с опозданием. Плановое время: {scheduled_for}.\n"


async def deliver_reminder_occurrence(
    bot: Bot,
    reminder: ReminderReadData,
    scheduled_for_utc: datetime,
    *,
    is_catchup: bool,
) -> str:
    scheduled_for = ensure_timezone_aware(scheduled_for_utc).astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    occurrence_age = now - scheduled_for

    if (
        is_catchup
        and reminder.reminder_kind == REMINDER_KIND_WEATHER
        and occurrence_age > WEATHER_CATCHUP_MAX_AGE
    ):
        final_status = "missed" if reminder.schedule_type == "once" else None
        handled = await asyncio.to_thread(
            mark_reminder_occurrence_handled,
            reminder.id,
            scheduled_for,
            final_status=final_status,
        )
        if not handled:
            handling_state = await get_occurrence_handling_state_for_log(
                reminder.id,
                scheduled_for,
            )
            LOGGER.warning(
                (
                    "Reminder occurrence watermark was not updated: "
                    "reminder_id=%s scheduled_for=%s database_state=%s"
                ),
                reminder.id,
                scheduled_for.isoformat(timespec="seconds"),
                handling_state,
            )
            if handling_state != "already_handled":
                return DELIVERY_OUTCOME_STALE_WEATHER_UNRECORDED

        LOGGER.info(
            (
                "Stale weather catch-up skipped: reminder_id=%s chat_id=%s "
                "scheduled_for=%s age_seconds=%s"
            ),
            reminder.id,
            reminder.chat_id,
            scheduled_for.isoformat(timespec="seconds"),
            int(occurrence_age.total_seconds()),
        )
        return DELIVERY_OUTCOME_STALE_WEATHER_SKIPPED

    message_prefix = ""
    if occurrence_age >= LATE_REMINDER_NOTICE_THRESHOLD:
        message_prefix = build_late_reminder_notice(reminder, scheduled_for)

    if reminder.requires_completion:
        completion_outcome = await deliver_completion_occurrence(
            bot,
            reminder,
            scheduled_for,
            f"{message_prefix}{reminder.reminder_text}",
        )
        if completion_outcome in {
            DELIVERY_OUTCOME_SENT,
            "already_delivered",
            "already_completed",
        }:
            return DELIVERY_OUTCOME_SENT
        return DELIVERY_OUTCOME_SENT_UNRECORDED

    sent_message = await send_reminder_message(
        bot=bot,
        chat_id=reminder.chat_id,
        reminder_text=reminder.reminder_text,
        reminder_kind=reminder.reminder_kind,
        reminder_id=reminder.id,
        use_prepared_weather_report=not is_catchup,
        message_prefix=message_prefix,
    )
    await enqueue_sent_reminder_message_for_deletion(
        reminder_id=reminder.id,
        chat_id=reminder.chat_id,
        message=sent_message,
        delete_after_two_days=reminder.delete_after_two_days,
    )
    final_status = "sent" if reminder.schedule_type == "once" else None
    handled = await asyncio.to_thread(
        mark_reminder_occurrence_handled,
        reminder.id,
        scheduled_for,
        final_status=final_status,
    )
    if not handled:
        handling_state = await get_occurrence_handling_state_for_log(
            reminder.id,
            scheduled_for,
        )
        LOGGER.warning(
            (
                "Reminder occurrence watermark was not updated after send: "
                "reminder_id=%s scheduled_for=%s database_state=%s"
            ),
            reminder.id,
            scheduled_for.isoformat(timespec="seconds"),
            handling_state,
        )
        return DELIVERY_OUTCOME_SENT_UNRECORDED

    return DELIVERY_OUTCOME_SENT


async def get_occurrence_handling_state_for_log(
    reminder_id: int,
    scheduled_for: datetime,
) -> str:
    try:
        return await asyncio.to_thread(
            get_reminder_occurrence_handling_state,
            reminder_id,
            scheduled_for,
        )
    except Exception as error:
        LOGGER.exception(
            (
                "Could not diagnose reminder occurrence watermark state: "
                "reminder_id=%s scheduled_for=%s error_type=%s"
            ),
            reminder_id,
            scheduled_for.isoformat(timespec="seconds"),
            type(error).__name__,
        )
        return "diagnostic_failed"


async def run_scheduled_reminder(bot: Bot, reminder_id: int) -> None:
    reminder_row = await asyncio.to_thread(
        get_active_reminder_from_db,
        reminder_id,
    )
    if reminder_row is None:
        return

    reminder = build_reminder_read_data(reminder_row)
    scheduled_for = get_latest_unhandled_run_at(
        reminder,
        now=datetime.now(timezone.utc),
    )
    if scheduled_for is None:
        return

    await deliver_reminder_occurrence(
        bot,
        reminder,
        scheduled_for,
        is_catchup=False,
    )


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


def get_latest_unhandled_run_at(
    reminder: ReminderReadData,
    *,
    now: datetime,
) -> datetime | None:
    now_utc = ensure_timezone_aware(now, "UTC").astimezone(timezone.utc)
    trigger = build_reminder_trigger(
        schedule_type=reminder.schedule_type,
        start_at=reminder.start_at,
        interval_days=reminder.interval_days,
        interval_weeks=reminder.interval_weeks,
        day_of_week=reminder.day_of_week,
        month_week_number=reminder.month_week_number,
        month_day=reminder.month_day,
        timezone_name=reminder.timezone_name,
    )

    if reminder.last_handled_scheduled_for_utc is None:
        lower_bound = reminder.delivery_tracking_started_at_utc.astimezone(timezone.utc)
        lower_bound_is_inclusive = True
        search_from = lower_bound - timedelta(microseconds=1)
    else:
        lower_bound = reminder.last_handled_scheduled_for_utc.astimezone(timezone.utc)
        lower_bound_is_inclusive = False
        search_from = lower_bound + timedelta(microseconds=1)

    fire_time = trigger.get_next_fire_time(None, search_from)
    latest_run_at: datetime | None = None
    occurrence_count = 0

    while fire_time is not None:
        fire_time_utc = fire_time.astimezone(timezone.utc)
        is_before_lower_bound = fire_time_utc < lower_bound or (
            fire_time_utc == lower_bound and not lower_bound_is_inclusive
        )
        if is_before_lower_bound:
            next_fire_time = trigger.get_next_fire_time(fire_time, search_from)
            if next_fire_time is not None and (
                next_fire_time.astimezone(timezone.utc) <= fire_time_utc
            ):
                raise RuntimeError(
                    "Reminder trigger returned a non-advancing fire time: "
                    f"reminder_id={reminder.id}"
                )
            fire_time = next_fire_time
            continue

        if fire_time_utc > now_utc:
            break

        occurrence_count += 1
        if occurrence_count > REMINDER_OCCURRENCE_SEARCH_LIMIT:
            raise RuntimeError(
                "Reminder occurrence search exceeded the safety limit: "
                f"reminder_id={reminder.id}"
            )

        latest_run_at = fire_time_utc
        next_fire_time = trigger.get_next_fire_time(fire_time, fire_time)
        if next_fire_time is not None and (
            next_fire_time.astimezone(timezone.utc) <= fire_time_utc
        ):
            raise RuntimeError(
                "Reminder trigger returned a non-advancing fire time: "
                f"reminder_id={reminder.id}"
            )
        fire_time = next_fire_time

    return latest_run_at


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
    requires_completion: bool = False,
    repeat_interval_minutes: int | None = None,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
    timezone_name: str | None = None,
    next_run_time: datetime | None = None,
) -> None:
    job_kwargs: dict[str, Any] = {
        "args": [bot, reminder_id],
        "id": str(reminder_id),
        "replace_existing": True,
        "max_instances": 1,
        "coalesce": True,
    }
    if next_run_time is not None:
        job_kwargs["next_run_time"] = next_run_time
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
    scheduler.add_job(
        run_scheduled_reminder,
        **trigger_kwargs,
        **job_kwargs,
    )


def schedule_reminder_from_row(
    bot: Bot,
    reminder: sqlite3.Row,
    *,
    next_run_time: datetime | None = None,
) -> None:
    reminder_data = build_reminder_read_data(reminder)
    schedule_reminder_data(
        bot,
        reminder_data,
        next_run_time=next_run_time,
    )


def schedule_reminder_data(
    bot: Bot,
    reminder: ReminderReadData,
    *,
    next_run_time: datetime | None = None,
) -> None:
    schedule_reminder(
        bot=bot,
        reminder_id=reminder.id,
        chat_id=reminder.chat_id,
        reminder_text=reminder.reminder_text,
        reminder_kind=reminder.reminder_kind,
        delete_after_two_days=reminder.delete_after_two_days,
        requires_completion=reminder.requires_completion,
        repeat_interval_minutes=reminder.repeat_interval_minutes,
        schedule_type=reminder.schedule_type,
        start_at=reminder.start_at,
        interval_days=reminder.interval_days,
        interval_weeks=reminder.interval_weeks,
        day_of_week=reminder.day_of_week,
        month_week_number=reminder.month_week_number,
        month_day=reminder.month_day,
        timezone_name=reminder.timezone_name,
        next_run_time=next_run_time,
    )


def schedule_completion_occurrence_worker(bot: Bot) -> None:
    scheduler.add_job(
        process_due_completion_occurrences,
        trigger="interval",
        minutes=1,
        args=[bot],
        id="completion-occurrence-repeat-worker",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
        max_instances=1,
        coalesce=True,
    )


def get_restore_row_value(reminder: object, key: str) -> object:
    try:
        return reminder[key]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return None


def log_restoration_error(
    *,
    reminder_id: object,
    chat_id: object,
    stage: str,
    error: Exception,
) -> None:
    LOGGER.exception(
        (
            "Reminder restoration failed: reminder_id=%s chat_id=%s "
            "stage=%s error_type=%s"
        ),
        reminder_id,
        chat_id,
        stage,
        type(error).__name__,
    )


async def deliver_restored_occurrence(
    bot: Bot,
    reminder: ReminderReadData,
    scheduled_for: datetime,
) -> str:
    try:
        return await deliver_reminder_occurrence(
            bot,
            reminder,
            scheduled_for,
            is_catchup=True,
        )
    except Exception as error:
        log_restoration_error(
            reminder_id=reminder.id,
            chat_id=reminder.chat_id,
            stage="catchup_delivery",
            error=error,
        )
        return "error"


async def restore_active_reminders(bot: Bot) -> None:
    restored_jobs = 0
    catchup_sent = 0
    stale_weather_skipped = 0
    catchup_unrecorded = 0
    legacy_once_missed = 0
    catchup_errors = 0
    without_missed_occurrences = 0

    for stage, schedule_maintenance_job in (
        ("weather_prefetch_scheduling", schedule_weather_report_prefetch),
        (
            "message_deletion_cleanup_scheduling",
            lambda: schedule_reminder_message_deletion_cleanup(bot),
        ),
    ):
        try:
            schedule_maintenance_job()
        except Exception as error:
            log_restoration_error(
                reminder_id=None,
                chat_id=None,
                stage=stage,
                error=error,
            )

    try:
        active_reminders = get_all_active_reminders()
    except Exception as error:
        log_restoration_error(
            reminder_id=None,
            chat_id=None,
            stage="active_reminders_loading",
            error=error,
        )
        active_reminders = []

    for reminder_row in active_reminders:
        reminder_id = get_restore_row_value(reminder_row, "id")
        chat_id = get_restore_row_value(reminder_row, "chat_id")
        stage = "mapping"

        try:
            reminder = build_reminder_read_data(reminder_row)
            reminder_id = reminder.id
            chat_id = reminder.chat_id

            if reminder.schedule_type != "once":
                catchup_delivery_count = 0

                while True:
                    stage = "catchup_calculation"
                    evaluation_now = datetime.now(timezone.utc)
                    scheduled_for = get_latest_unhandled_run_at(
                        reminder,
                        now=evaluation_now,
                    )

                    if scheduled_for is None:
                        if catchup_delivery_count == 0:
                            without_missed_occurrences += 1

                        stage = "future_run_calculation"
                        next_run_time = get_next_run_at_for_schedule(
                            schedule_type=reminder.schedule_type,
                            start_at=reminder.start_at,
                            interval_days=reminder.interval_days,
                            interval_weeks=reminder.interval_weeks,
                            day_of_week=reminder.day_of_week,
                            month_week_number=reminder.month_week_number,
                            month_day=reminder.month_day,
                            timezone_name=reminder.timezone_name,
                            now=evaluation_now + timedelta(microseconds=1),
                        )
                        if next_run_time is not None:
                            stage = "future_job_scheduling"
                            schedule_reminder_data(
                                bot,
                                reminder,
                                next_run_time=next_run_time,
                            )
                            restored_jobs += 1
                        break

                    if catchup_delivery_count >= REMINDER_RESTORE_CATCHUP_LIMIT:
                        catchup_errors += 1
                        LOGGER.error(
                            (
                                "Reminder restoration catch-up limit exceeded: "
                                "reminder_id=%s chat_id=%s stage=catchup_limit "
                                "limit=%s"
                            ),
                            reminder.id,
                            reminder.chat_id,
                            REMINDER_RESTORE_CATCHUP_LIMIT,
                        )
                        break

                    outcome = await deliver_restored_occurrence(
                        bot,
                        reminder,
                        scheduled_for,
                    )
                    catchup_delivery_count += 1

                    if outcome == DELIVERY_OUTCOME_SENT:
                        catchup_sent += 1
                        LOGGER.info(
                            (
                                "Reminder catch-up sent: reminder_id=%s chat_id=%s "
                                "scheduled_for=%s"
                            ),
                            reminder.id,
                            reminder.chat_id,
                            scheduled_for.isoformat(timespec="seconds"),
                        )
                    elif outcome == DELIVERY_OUTCOME_STALE_WEATHER_SKIPPED:
                        stale_weather_skipped += 1
                    elif outcome == "error":
                        catchup_errors += 1
                    else:
                        catchup_unrecorded += 1

                    if outcome not in {
                        DELIVERY_OUTCOME_SENT,
                        DELIVERY_OUTCOME_STALE_WEATHER_SKIPPED,
                    }:
                        fresh_now = datetime.now(timezone.utc)
                        stage = "future_run_calculation_after_unrecorded_catchup"
                        next_run_time = get_next_run_at_for_schedule(
                            schedule_type=reminder.schedule_type,
                            start_at=reminder.start_at,
                            interval_days=reminder.interval_days,
                            interval_weeks=reminder.interval_weeks,
                            day_of_week=reminder.day_of_week,
                            month_week_number=reminder.month_week_number,
                            month_day=reminder.month_day,
                            timezone_name=reminder.timezone_name,
                            now=fresh_now + timedelta(microseconds=1),
                        )
                        if next_run_time is not None:
                            stage = "future_job_scheduling_after_unrecorded_catchup"
                            schedule_reminder_data(
                                bot,
                                reminder,
                                next_run_time=next_run_time,
                            )
                            restored_jobs += 1
                        break

                    stage = "post_catchup_reload"
                    reloaded_row = await asyncio.to_thread(
                        get_active_reminder_from_db,
                        reminder.id,
                    )
                    if reloaded_row is None:
                        break

                    stage = "post_catchup_mapping"
                    reminder = build_reminder_read_data(reloaded_row)
                    reminder_id = reminder.id
                    chat_id = reminder.chat_id

                continue

            stage = "catchup_calculation"
            evaluation_now = datetime.now(timezone.utc)
            scheduled_for = get_latest_unhandled_run_at(
                reminder,
                now=evaluation_now,
            )

            if scheduled_for is not None:
                outcome = await deliver_restored_occurrence(
                    bot,
                    reminder,
                    scheduled_for,
                )
                if outcome == DELIVERY_OUTCOME_SENT:
                    catchup_sent += 1
                elif outcome == DELIVERY_OUTCOME_STALE_WEATHER_SKIPPED:
                    stale_weather_skipped += 1
                elif outcome == "error":
                    catchup_errors += 1
                else:
                    catchup_unrecorded += 1
                continue

            if reminder.schedule_type == "once":
                stage = "once_due_recheck"
                fresh_now = datetime.now(timezone.utc)
                scheduled_for = get_latest_unhandled_run_at(
                    reminder,
                    now=fresh_now,
                )
                if scheduled_for is not None:
                    outcome = await deliver_restored_occurrence(
                        bot,
                        reminder,
                        scheduled_for,
                    )
                    if outcome == DELIVERY_OUTCOME_SENT:
                        catchup_sent += 1
                    elif outcome == DELIVERY_OUTCOME_STALE_WEATHER_SKIPPED:
                        stale_weather_skipped += 1
                    elif outcome == "error":
                        catchup_errors += 1
                    else:
                        catchup_unrecorded += 1
                    continue

                start_at_utc = ensure_timezone_aware(
                    reminder.start_at,
                    reminder.timezone_name,
                ).astimezone(timezone.utc)
                if start_at_utc <= fresh_now:
                    if start_at_utc < reminder.delivery_tracking_started_at_utc:
                        stage = "legacy_once_missed"
                        mark_reminder_as_missed(reminder.id)
                        legacy_once_missed += 1
                    else:
                        without_missed_occurrences += 1
                    continue

            stage = "future_run_calculation"
            next_run_time = get_next_run_at_for_schedule(
                schedule_type=reminder.schedule_type,
                start_at=reminder.start_at,
                interval_days=reminder.interval_days,
                interval_weeks=reminder.interval_weeks,
                day_of_week=reminder.day_of_week,
                month_week_number=reminder.month_week_number,
                month_day=reminder.month_day,
                timezone_name=reminder.timezone_name,
                now=fresh_now + timedelta(microseconds=1),
            )
            if next_run_time is not None:
                stage = "future_job_scheduling"
                schedule_reminder_data(
                    bot,
                    reminder,
                    next_run_time=next_run_time,
                )
                restored_jobs += 1
                if reminder.schedule_type == "once":
                    without_missed_occurrences += 1
        except Exception as error:
            log_restoration_error(
                reminder_id=reminder_id,
                chat_id=chat_id,
                stage=stage,
                error=error,
            )
            continue

    try:
        schedule_completion_occurrence_worker(bot)
    except Exception as error:
        log_restoration_error(
            reminder_id=None,
            chat_id=None,
            stage="completion_worker_scheduling",
            error=error,
        )

    LOGGER.info(
        (
            "Reminder restoration completed: restored_jobs=%s catchup_sent=%s "
            "stale_weather_skipped=%s catchup_unrecorded=%s legacy_once_missed=%s "
            "catchup_errors=%s without_missed_occurrences=%s"
        ),
        restored_jobs,
        catchup_sent,
        stale_weather_skipped,
        catchup_unrecorded,
        legacy_once_missed,
        catchup_errors,
        without_missed_occurrences,
    )
