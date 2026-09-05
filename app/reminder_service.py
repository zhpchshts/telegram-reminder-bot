from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot

from app.config import APP_TIMEZONE_NAME
from app.constants import (
    COMPLETION_REMINDER_TEXT_MAX_LENGTH,
    LAST_DAY_OF_MONTH,
    MAX_INTERVAL_DAYS,
    MAX_INTERVAL_WEEKS,
    REMINDER_KIND_TEXT,
    REMINDER_KIND_WEATHER,
    REMINDER_TEXT_MAX_LENGTH,
    TELEGRAM_MESSAGE_MAX_LENGTH,
    VALID_COMPLETION_REPEAT_INTERVALS,
    VALID_REMINDER_KINDS,
    VALID_WEEKDAYS,
    WEATHER_REMINDER_TEXT_MAX_LENGTH,
)
from app.database import (
    ActiveReminderLimitError as DatabaseActiveReminderLimitError,
    ReminderIdempotencyConflictError as DatabaseReminderIdempotencyConflictError,
    clear_reminder_idempotency_key,
    create_reminder_in_db,
    create_reminder_idempotently_in_db,
    delete_active_reminder_for_chat_in_db,
    get_active_reminder_for_chat as get_active_reminder_from_db_for_chat,
    get_active_reminders_for_chat,
    get_chat_timezone,
    get_reminder_idempotency_record,
    mark_reminder_idempotency_succeeded,
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
    build_reminder_trigger,
    format_next_run_line,
    get_reminder_mutation_lock,
    get_next_run_at,
    scheduler,
    schedule_reminder,
    schedule_reminder_data,
)
from app.weather_service import parse_weather_locations


LOGGER = logging.getLogger(__name__)
ActiveReminderLimitError = DatabaseActiveReminderLimitError
ReminderIdempotencyConflictError = DatabaseReminderIdempotencyConflictError
ACTIVE_REMINDER_LIST_MAX_MESSAGES = 3
ACTIVE_REMINDER_LIST_TEXT_PREVIEW_MAX_LENGTH = 240
ACTIVE_REMINDER_LIST_HEADER = "Активные напоминания в этом чате\n"


class ReminderSchedulingError(RuntimeError):
    pass


class ReminderRevisionConflictError(RuntimeError):
    pass


class ReminderIdempotencyPendingError(RuntimeError):
    pass


def get_chat_timezone_name(chat_id: int) -> str:
    return get_chat_timezone(chat_id) or APP_TIMEZONE_NAME


def set_chat_timezone_for_chat(*, chat_id: int, timezone_name: str) -> bool:
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return False

    set_chat_timezone(
        chat_id=chat_id,
        timezone=timezone_name,
    )
    return True


def get_active_reminder_for_chat(
    *,
    reminder_id: int,
    chat_id: int,
) -> ReminderReadData | None:
    reminder = get_active_reminder_from_db_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )
    if not reminder:
        return None

    return build_reminder_read_data(reminder)


def validate_positive_int(
    value: int | None,
    field_name: str,
    *,
    maximum: int,
) -> None:
    if value is None or value < 1:
        raise ValueError(f"{field_name} must be greater than or equal to 1.")
    if value > maximum:
        raise ValueError(f"{field_name} must be less than or equal to {maximum}.")


def validate_day_of_week(day_of_week: str | None) -> None:
    if day_of_week not in VALID_WEEKDAYS:
        raise ValueError("day_of_week is invalid.")


def validate_reminder_kind(reminder_kind: str) -> None:
    if reminder_kind not in VALID_REMINDER_KINDS:
        raise ValueError("reminder_kind is invalid.")


def validate_reminder_create_data(data: ReminderCreateData) -> None:
    validate_reminder_kind(data.reminder_kind)
    if not data.reminder_text.strip():
        raise ValueError("reminder_text is required.")

    if (
        not data.requires_completion
        and len(data.reminder_text) > REMINDER_TEXT_MAX_LENGTH
    ):
        raise ValueError(
            f"reminder_text must not exceed {REMINDER_TEXT_MAX_LENGTH} characters."
        )

    if data.reminder_kind == REMINDER_KIND_WEATHER:
        if len(data.reminder_text) > WEATHER_REMINDER_TEXT_MAX_LENGTH:
            raise ValueError(
                "weather reminder locations must not exceed "
                f"{WEATHER_REMINDER_TEXT_MAX_LENGTH} characters."
            )
        parse_weather_locations(data.reminder_text)

    if data.requires_completion:
        if data.reminder_kind != REMINDER_KIND_TEXT:
            raise ValueError("Completion is supported only for text reminders.")
        if data.repeat_interval_minutes not in VALID_COMPLETION_REPEAT_INTERVALS:
            raise ValueError("repeat_interval_minutes is invalid.")
        if len(data.reminder_text) > COMPLETION_REMINDER_TEXT_MAX_LENGTH:
            raise ValueError("reminder_text is too long for a completion reminder.")

    if data.schedule_type == "once":
        return

    if data.schedule_type == "every_days":
        validate_positive_int(
            data.interval_days,
            "interval_days",
            maximum=MAX_INTERVAL_DAYS,
        )
        return

    if data.schedule_type == "every_week":
        validate_positive_int(
            data.interval_weeks,
            "interval_weeks",
            maximum=MAX_INTERVAL_WEEKS,
        )
        validate_day_of_week(data.day_of_week)
        return

    if data.schedule_type == "monthly_weekday":
        if data.month_week_number is None or not 1 <= data.month_week_number <= 5:
            raise ValueError("month_week_number must be between 1 and 5.")

        validate_day_of_week(data.day_of_week)
        return

    if data.schedule_type == "monthly_day":
        if data.month_day is None or (
            data.month_day != LAST_DAY_OF_MONTH and not 1 <= data.month_day <= 31
        ):
            raise ValueError(
                "month_day must be between 1 and 31 or the last-day value."
            )

        return

    if data.schedule_type == "yearly_date":
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


def build_reminder_idempotency_hash(data: ReminderCreateData) -> str:
    request_payload = asdict(data)
    request_payload["start_at"] = data.start_at.isoformat()
    return sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def synchronize_updated_reminder_job(
    *,
    bot: Bot,
    reminder_id: int,
    chat_id: int,
    scheduled_revision: int,
) -> ReminderReadData | None:
    for _attempt in range(3):
        current_reminder = get_active_reminder_for_chat(
            reminder_id=reminder_id,
            chat_id=chat_id,
        )
        if current_reminder is None:
            job = scheduler.get_job(str(reminder_id))
            if job is not None:
                scheduler.remove_job(str(reminder_id))
            return None

        current_revision = current_reminder.revision
        if current_revision == scheduled_revision:
            return current_reminder

        schedule_reminder_data(bot, current_reminder)
        scheduled_revision = current_revision

    LOGGER.warning(
        "Reminder job reconciliation reached retry limit: reminder_id=%s chat_id=%s",
        reminder_id,
        chat_id,
    )
    return get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )


def resolve_reminder_idempotency_record(
    *,
    record: dict[str, object],
    idempotency_key: str,
) -> int:
    reminder_id = int(record["id"])
    request_status = record.get("client_request_status")
    if request_status == "succeeded":
        return reminder_id

    if record.get("reminder_status") != "active":
        clear_reminder_idempotency_key(reminder_id)
        raise ReminderIdempotencyPendingError(
            "Предыдущая попытка создания не завершилась. Повторите запрос."
        )

    expected_job_name = f"reminder-revision:{int(record['revision'])}"
    current_job = scheduler.get_job(str(reminder_id))
    if (
        current_job is not None
        and getattr(current_job, "name", None) == expected_job_name
    ):
        try:
            mark_reminder_idempotency_succeeded(
                reminder_id=reminder_id,
                client_request_id=idempotency_key,
            )
        except Exception:
            LOGGER.exception(
                "Could not recover idempotency state: reminder_id=%s",
                reminder_id,
            )
        return reminder_id

    raise ReminderIdempotencyPendingError(
        "Создание напоминания ещё выполняется. Повторите запрос чуть позже."
    )


def create_scheduled_reminder(
    *,
    bot: Bot,
    chat_id: int,
    data: ReminderCreateData,
    idempotency_key: str | None = None,
) -> int:
    validate_reminder_create_data(data)

    request_hash: str | None = None
    if idempotency_key is not None:
        request_hash = build_reminder_idempotency_hash(data)
        idempotency_record = get_reminder_idempotency_record(
            chat_id=chat_id,
            client_request_id=idempotency_key,
            client_request_hash=request_hash,
        )
        if idempotency_record is not None:
            replayed_reminder_id = resolve_reminder_idempotency_record(
                record=idempotency_record,
                idempotency_key=idempotency_key,
            )
            LOGGER.info(
                "Idempotent reminder creation replayed: reminder_id=%s chat_id=%s",
                replayed_reminder_id,
                chat_id,
            )
            return replayed_reminder_id

    reminder_timezone = ZoneInfo(data.timezone_name)
    start_at = data.start_at
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=reminder_timezone)
    if start_at <= datetime.now(reminder_timezone):
        raise ValueError("start_at must be in the future.")

    # Constructing the trigger can fail for an invalid timezone or an interval
    # that cannot be represented by APScheduler. Validate it before persisting
    # an active reminder so a rejected request cannot leave a zombie row.
    build_reminder_trigger(
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone_name=data.timezone_name,
    )

    create_kwargs = {
        "chat_id": chat_id,
        "reminder_text": data.reminder_text,
        "reminder_kind": data.reminder_kind,
        "delete_after_two_days": data.delete_after_two_days,
        "requires_completion": data.requires_completion,
        "repeat_interval_minutes": (
            data.repeat_interval_minutes if data.requires_completion else None
        ),
        "schedule_type": data.schedule_type,
        "start_at": data.start_at,
        "interval_days": data.interval_days,
        "interval_weeks": data.interval_weeks,
        "day_of_week": data.day_of_week,
        "month_week_number": data.month_week_number,
        "month_day": data.month_day,
        "timezone": data.timezone_name,
    }
    if idempotency_key is None:
        reminder_id = create_reminder_in_db(**create_kwargs)
        was_created = True
    else:
        assert request_hash is not None
        reminder_id, was_created, request_status = create_reminder_idempotently_in_db(
            **create_kwargs,
            client_request_id=idempotency_key,
            client_request_hash=request_hash,
        )

    if not was_created:
        replayed_reminder_id = resolve_reminder_idempotency_record(
            record={
                "id": reminder_id,
                "client_request_status": request_status,
                "reminder_status": "active",
                "revision": 1,
            },
            idempotency_key=idempotency_key,
        )
        LOGGER.info(
            "Idempotent reminder creation replayed: reminder_id=%s chat_id=%s",
            replayed_reminder_id,
            chat_id,
        )
        return replayed_reminder_id

    try:
        schedule_reminder(
            bot=bot,
            reminder_id=reminder_id,
            schedule_type=data.schedule_type,
            start_at=data.start_at,
            interval_days=data.interval_days,
            interval_weeks=data.interval_weeks,
            day_of_week=data.day_of_week,
            month_week_number=data.month_week_number,
            month_day=data.month_day,
            timezone_name=data.timezone_name,
        )
    except Exception as error:
        LOGGER.exception(
            "Reminder scheduling failed after database insert: reminder_id=%s chat_id=%s",
            reminder_id,
            chat_id,
        )
        try:
            mark_reminder_as_deleted(reminder_id)
            clear_reminder_idempotency_key(reminder_id)
        except Exception:
            LOGGER.exception(
                "Could not deactivate reminder after scheduling failure: reminder_id=%s",
                reminder_id,
            )
        raise ReminderSchedulingError("Reminder could not be scheduled.") from error

    if idempotency_key is not None:
        try:
            mark_reminder_idempotency_succeeded(
                reminder_id=reminder_id,
                client_request_id=idempotency_key,
            )
        except Exception:
            LOGGER.exception(
                "Could not persist successful idempotency state: reminder_id=%s",
                reminder_id,
            )
    return reminder_id


def update_active_reminder_for_chat(
    *,
    bot: Bot,
    reminder_id: int,
    chat_id: int,
    data: ReminderCreateData,
    expected_revision: int | None = None,
) -> ReminderReadData | None:
    with get_reminder_mutation_lock(reminder_id):
        return _update_active_reminder_for_chat(
            bot=bot,
            reminder_id=reminder_id,
            chat_id=chat_id,
            data=data,
            expected_revision=expected_revision,
        )


def _update_active_reminder_for_chat(
    *,
    bot: Bot,
    reminder_id: int,
    chat_id: int,
    data: ReminderCreateData,
    expected_revision: int | None = None,
) -> ReminderReadData | None:
    validate_reminder_create_data(data)

    build_reminder_trigger(
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone_name=data.timezone_name,
    )

    reminder = get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )
    if not reminder:
        return None
    if expected_revision is not None and reminder.revision != expected_revision:
        raise ReminderRevisionConflictError("Reminder was changed by another client.")

    is_updated = update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=chat_id,
        reminder_text=data.reminder_text,
        reminder_kind=data.reminder_kind,
        delete_after_two_days=data.delete_after_two_days,
        requires_completion=data.requires_completion,
        repeat_interval_minutes=(
            data.repeat_interval_minutes if data.requires_completion else None
        ),
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone=data.timezone_name,
        expected_revision=expected_revision,
    )
    if not is_updated:
        current_reminder = get_active_reminder_for_chat(
            reminder_id=reminder_id,
            chat_id=chat_id,
        )
        if current_reminder is not None and expected_revision is not None:
            raise ReminderRevisionConflictError(
                "Reminder was changed by another client."
            )
        return None

    LOGGER.info(
        "Reminder updated and live completion occurrences cancelled: reminder_id=%s chat_id=%s",
        reminder_id,
        chat_id,
    )

    scheduled_revision = reminder.revision + 1
    try:
        schedule_reminder(
            bot=bot,
            reminder_id=reminder_id,
            schedule_type=data.schedule_type,
            start_at=data.start_at,
            interval_days=data.interval_days,
            interval_weeks=data.interval_weeks,
            day_of_week=data.day_of_week,
            month_week_number=data.month_week_number,
            month_day=data.month_day,
            timezone_name=data.timezone_name,
            reminder_revision=scheduled_revision,
        )
        updated_reminder = synchronize_updated_reminder_job(
            bot=bot,
            reminder_id=reminder_id,
            chat_id=chat_id,
            scheduled_revision=scheduled_revision,
        )
    except Exception as error:
        LOGGER.exception(
            "Reminder %s was updated in the database, but rescheduling failed.",
            reminder_id,
        )
        raise ReminderSchedulingError(
            "Reminder was updated in the database, but rescheduling failed."
        ) from error

    if not updated_reminder:
        return None

    return updated_reminder


def build_period_line_for_create_data(data: ReminderCreateData) -> str:
    period_kwargs = {
        "schedule_type": data.schedule_type,
        "interval_days": data.interval_days,
        "interval_weeks": data.interval_weeks,
        "day_of_week": data.day_of_week,
        "month_week_number": data.month_week_number,
        "month_day": data.month_day,
    }

    if data.schedule_type == "yearly_date":
        period_kwargs["start_at"] = data.start_at

    return format_period_line(**period_kwargs)


def _build_created_reminder_lines(
    *,
    reminder_id: int,
    data: ReminderCreateData,
) -> list[str]:
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
        answer_lines.append("Период: " + build_period_line_for_create_data(data))

    answer_lines.extend(
        [
            f"Таймзона: {data.timezone_name}",
            f"Первое срабатывание: {format_datetime_ru(data.start_at, data.timezone_name)}",
            format_next_run_line(reminder_id, data.timezone_name),
            f"Текст: {data.reminder_text}",
        ]
    )

    return answer_lines


def build_created_reminder_text(
    *,
    reminder_id: int,
    data: ReminderCreateData,
) -> str:
    return "\n".join(
        _build_created_reminder_lines(
            reminder_id=reminder_id,
            data=data,
        )
    )


def build_created_reminder_messages(
    *,
    reminder_id: int,
    data: ReminderCreateData,
) -> tuple[str, ...]:
    answer_lines = _build_created_reminder_lines(
        reminder_id=reminder_id,
        data=data,
    )
    answer_text = "\n".join(answer_lines)
    if len(answer_text) <= TELEGRAM_MESSAGE_MAX_LENGTH:
        return (answer_text,)

    metadata_text = "\n".join(
        [
            *answer_lines[:-1],
            "Текст напоминания — в следующем сообщении.",
        ]
    )
    reminder_text = f"Текст: {data.reminder_text}"
    if (
        len(metadata_text) > TELEGRAM_MESSAGE_MAX_LENGTH
        or len(reminder_text) > TELEGRAM_MESSAGE_MAX_LENGTH
    ):
        raise ValueError("Reminder confirmation exceeds the Telegram message limit.")

    return metadata_text, reminder_text


def delete_active_reminder_for_chat(
    reminder_id: int,
    chat_id: int,
    *,
    expected_revision: int | None = None,
) -> bool:
    with get_reminder_mutation_lock(reminder_id):
        return _delete_active_reminder_for_chat(
            reminder_id,
            chat_id,
            expected_revision=expected_revision,
        )


def _delete_active_reminder_for_chat(
    reminder_id: int,
    chat_id: int,
    *,
    expected_revision: int | None = None,
) -> bool:
    if not delete_active_reminder_for_chat_in_db(
        reminder_id,
        chat_id,
        expected_revision=expected_revision,
    ):
        if expected_revision is not None:
            current_reminder = get_active_reminder_for_chat(
                reminder_id=reminder_id,
                chat_id=chat_id,
            )
            if current_reminder is not None:
                raise ReminderRevisionConflictError(
                    "Reminder was changed by another client."
                )
        return False

    LOGGER.info(
        "Reminder deleted and live completion occurrences cancelled: reminder_id=%s chat_id=%s",
        reminder_id,
        chat_id,
    )

    try:
        job = scheduler.get_job(str(reminder_id))
        if job:
            scheduler.remove_job(str(reminder_id))
    except Exception:
        LOGGER.exception(
            "Reminder %s was deleted in the database, but scheduler cleanup failed.",
            reminder_id,
        )

    return True


def list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
    reminders = [
        build_reminder_read_data(reminder)
        for reminder in get_active_reminders_for_chat(chat_id)
    ]

    return sort_reminders_by_next_run(reminders)


def _build_active_reminder_list_page(
    reminder_blocks: list[str],
    *,
    footer: str | None = None,
) -> str:
    parts = [ACTIVE_REMINDER_LIST_HEADER, *reminder_blocks]
    if footer is not None:
        parts.append(footer)
    return "\n\n".join(parts)


def _pack_active_reminder_list_blocks(
    reminder_blocks: list[str],
) -> tuple[list[list[str]], int]:
    page_blocks: list[list[str]] = [[]]
    shown_count = 0

    for reminder_block in reminder_blocks:
        candidate_blocks = [*page_blocks[-1], reminder_block]
        candidate_page = _build_active_reminder_list_page(candidate_blocks)
        if len(candidate_page) <= TELEGRAM_MESSAGE_MAX_LENGTH:
            page_blocks[-1].append(reminder_block)
            shown_count += 1
            continue

        if not page_blocks[-1] or len(page_blocks) >= ACTIVE_REMINDER_LIST_MAX_MESSAGES:
            break

        next_page = _build_active_reminder_list_page([reminder_block])
        if len(next_page) > TELEGRAM_MESSAGE_MAX_LENGTH:
            break

        page_blocks.append([reminder_block])
        shown_count += 1

    return page_blocks, shown_count


def build_active_reminders_list_messages_for_chat(
    chat_id: int,
) -> tuple[str, ...] | None:
    reminders = list_active_reminders_for_chat(chat_id)
    if not reminders:
        return None

    reminder_views = [
        (
            reminder,
            format_next_run_line(reminder.id, reminder.timezone_name),
        )
        for reminder in reminders
    ]
    full_reminder_blocks = [
        format_reminder_read_data_for_list(reminder, next_run_line)
        for reminder, next_run_line in reminder_views
    ]
    full_page_blocks, full_shown_count = _pack_active_reminder_list_blocks(
        full_reminder_blocks
    )
    if full_shown_count == len(full_reminder_blocks):
        return tuple(
            _build_active_reminder_list_page(blocks) for blocks in full_page_blocks
        )

    preview_reminder_blocks = [
        format_reminder_read_data_for_list(
            reminder,
            next_run_line,
            text_preview_max_length=ACTIVE_REMINDER_LIST_TEXT_PREVIEW_MAX_LENGTH,
        )
        for reminder, next_run_line in reminder_views
    ]
    page_blocks, shown_count = _pack_active_reminder_list_blocks(
        preview_reminder_blocks
    )
    total_count = len(preview_reminder_blocks)

    while True:
        footer = (
            f"Показаны {shown_count} из {total_count}. "
            "Полный список и полный текст — в Mini App: /app."
        )
        candidate_page = _build_active_reminder_list_page(
            page_blocks[-1],
            footer=footer,
        )
        if len(candidate_page) <= TELEGRAM_MESSAGE_MAX_LENGTH:
            break

        page_blocks[-1].pop()
        shown_count -= 1
        if not page_blocks[-1] and len(page_blocks) > 1:
            page_blocks.pop()

    return tuple(
        _build_active_reminder_list_page(
            blocks,
            footer=footer if index == len(page_blocks) - 1 else None,
        )
        for index, blocks in enumerate(page_blocks)
    )
