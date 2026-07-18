import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import COMPLETION_MESSAGE_SUFFIX, TELEGRAM_MESSAGE_MAX_LENGTH
from app.database import (
    activate_claimed_completion_occurrence,
    checkpoint_completion_message,
    claim_completion_occurrence_delivery,
    claim_completion_publication,
    complete_completion_occurrence,
    fail_completion_occurrence,
    finalize_completion_publication,
    finalize_failed_completion_publication,
    get_due_completion_occurrences,
    get_repeatable_completion_occurrence,
    get_reminder_from_db,
    replace_active_completion_message,
    reschedule_completion_publication,
    reschedule_completion_occurrence_after_error,
)
from app.reminder_mapping import build_reminder_read_data, parse_utc_datetime
from app.reminder_models import ReminderReadData

LOGGER = logging.getLogger(__name__)

COMPLETION_CALLBACK_PREFIX = "completion_done:"
COMPLETION_DELIVERY_CLAIM_TIMEOUT = timedelta(minutes=2)
COMPLETION_WORKER_BATCH_SIZE = 100
COMPLETION_RETRY_DELAY = timedelta(minutes=1)
COMPLETION_PUBLICATION_MAX_ATTEMPTS = 10


def build_completion_callback_data(occurrence_id: int) -> str:
    callback_data = f"{COMPLETION_CALLBACK_PREFIX}{occurrence_id}"
    if len(callback_data.encode("utf-8")) > 64:
        raise ValueError("Completion callback data exceeds the Telegram limit.")
    return callback_data


def parse_completion_callback_data(value: str | None) -> int | None:
    if not value or not value.startswith(COMPLETION_CALLBACK_PREFIX):
        return None
    occurrence_id = value.removeprefix(COMPLETION_CALLBACK_PREFIX)
    if not occurrence_id.isascii() or not occurrence_id.isdigit():
        return None
    parsed = int(occurrence_id)
    return parsed if parsed > 0 else None


def build_completion_keyboard(occurrence_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сделано",
                    callback_data=build_completion_callback_data(occurrence_id),
                )
            ]
        ]
    )


def get_sent_at(message) -> datetime:
    sent_at = message.date
    if sent_at.tzinfo is None or sent_at.tzinfo.utcoffset(sent_at) is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return sent_at.astimezone(timezone.utc)


def is_message_not_found(error: TelegramAPIError) -> bool:
    if isinstance(error, TelegramNotFound):
        return True
    return isinstance(error, TelegramBadRequest) and (
        "message to delete not found" in error.message.casefold()
    )


def is_terminal_send_error(error: Exception) -> bool:
    return isinstance(
        error,
        (
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramNotFound,
            TelegramUnauthorizedError,
        ),
    ) and not isinstance(error, TelegramRetryAfter)


def get_retry_delay(error: Exception) -> timedelta:
    if isinstance(error, TelegramRetryAfter):
        return timedelta(seconds=max(int(error.retry_after), 1))
    return COMPLETION_RETRY_DELAY


async def delete_message_best_effort(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int | None,
    reason: str,
) -> None:
    if message_id is None:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError as error:
        if is_message_not_found(error):
            return
        LOGGER.warning(
            "Completion message deletion failed: chat_id=%s message_id=%s reason=%s error_type=%s",
            chat_id,
            message_id,
            reason,
            type(error).__name__,
        )
    else:
        LOGGER.info(
            "Completion message deleted: chat_id=%s message_id=%s reason=%s",
            chat_id,
            message_id,
            reason,
        )


async def delete_previous_occurrence_message(
    bot: Bot,
    previous,
    *,
    reason: str,
) -> None:
    if previous is None:
        return
    await delete_message_best_effort(
        bot,
        chat_id=int(previous["chat_id"]),
        message_id=(
            int(previous["current_message_id"])
            if previous["current_message_id"] is not None
            else None
        ),
        reason=reason,
    )


async def record_delivery_error(
    *,
    occurrence_id: int,
    status: str,
    message_id: int | None,
    attempts: int,
    error: Exception,
) -> None:
    if is_terminal_send_error(error):
        await asyncio.to_thread(
            fail_completion_occurrence,
            occurrence_id=occurrence_id,
            expected_status=status,
            expected_message_id=message_id,
            last_error=f"{type(error).__name__}: {error}",
        )
        LOGGER.warning(
            "Completion delivery stopped after terminal Telegram error: occurrence_id=%s error_type=%s",
            occurrence_id,
            type(error).__name__,
        )
        return

    next_attempt_at = datetime.now(timezone.utc) + get_retry_delay(error)
    await asyncio.to_thread(
        reschedule_completion_occurrence_after_error,
        occurrence_id=occurrence_id,
        expected_status=status,
        expected_message_id=message_id,
        next_attempt_at=next_attempt_at,
        attempts=attempts,
        last_error=f"{type(error).__name__}: {error}",
    )
    LOGGER.warning(
        "Completion delivery rescheduled: occurrence_id=%s error_type=%s next_attempt_at=%s",
        occurrence_id,
        type(error).__name__,
        next_attempt_at.isoformat(timespec="seconds"),
    )


async def deliver_completion_occurrence(
    bot: Bot,
    reminder: ReminderReadData,
    scheduled_for_utc: datetime,
    rendered_text: str,
    *,
    occurrence_id: int | None = None,
    expected_revision: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    claim_token = uuid4().hex
    claim_revision = (
        reminder.revision if expected_revision is None else expected_revision
    )
    claim = await asyncio.to_thread(
        claim_completion_occurrence_delivery,
        reminder_id=reminder.id,
        expected_revision=claim_revision,
        occurrence_id=occurrence_id,
        scheduled_for_utc=scheduled_for_utc,
        rendered_text=rendered_text,
        claim_token=claim_token,
        now=now,
        stale_before=now - COMPLETION_DELIVERY_CLAIM_TIMEOUT,
    )
    outcome = str(claim["outcome"])
    if outcome == "stale_revision":
        LOGGER.info(
            "Completion delivery skipped for stale reminder revision: reminder_id=%s expected_revision=%s scheduled_for=%s",
            reminder.id,
            claim_revision,
            scheduled_for_utc.isoformat(timespec="seconds"),
        )
        return outcome
    if outcome in {"already_delivered", "already_completed"}:
        return outcome
    if outcome == "recovered":
        await delete_previous_occurrence_message(
            bot,
            claim.get("previous"),
            reason="pending_recovery",
        )
        return "already_delivered"
    if outcome == "inconsistent":
        LOGGER.warning(
            "Completion occurrence has a terminal status while its reminder is active: reminder_id=%s scheduled_for=%s",
            reminder.id,
            scheduled_for_utc.isoformat(timespec="seconds"),
        )
    if outcome != "claimed":
        return outcome

    occurrence_id = int(claim["occurrence_id"])
    LOGGER.info(
        "Completion occurrence delivery claimed: reminder_id=%s occurrence_id=%s scheduled_for=%s recovery=%s",
        reminder.id,
        occurrence_id,
        scheduled_for_utc.isoformat(timespec="seconds"),
        bool(claim.get("is_recovery")),
    )
    if claim.get("is_recovery"):
        LOGGER.warning(
            "Recovering stale pending completion delivery; a physical duplicate is possible: reminder_id=%s occurrence_id=%s",
            reminder.id,
            occurrence_id,
        )
    if len(rendered_text) > TELEGRAM_MESSAGE_MAX_LENGTH:
        error = ValueError("Rendered completion reminder exceeds Telegram limit.")
        await asyncio.to_thread(
            fail_completion_occurrence,
            occurrence_id=occurrence_id,
            expected_status="pending",
            expected_message_id=None,
            last_error=str(error),
        )
        raise error

    try:
        message = await bot.send_message(
            chat_id=reminder.chat_id,
            text=rendered_text,
            reply_markup=build_completion_keyboard(occurrence_id),
        )
    except Exception as error:
        await record_delivery_error(
            occurrence_id=occurrence_id,
            status="pending",
            message_id=None,
            attempts=1,
            error=error,
        )
        return "delivery_failed"

    sent_at = get_sent_at(message)
    try:
        activation = await asyncio.to_thread(
            activate_claimed_completion_occurrence,
            occurrence_id=occurrence_id,
            claim_token=claim_token,
            message_id=message.message_id,
            sent_at=sent_at,
        )
    except Exception:
        LOGGER.exception(
            "Completion activation failed after Telegram send; a physical duplicate is possible: reminder_id=%s occurrence_id=%s message_id=%s",
            reminder.id,
            occurrence_id,
            message.message_id,
        )
        await delete_message_best_effort(
            bot,
            chat_id=reminder.chat_id,
            message_id=message.message_id,
            reason="activation_error",
        )
        return "sent_unrecorded"

    activation_outcome = str(activation["outcome"])
    if activation_outcome == "activated":
        previous = activation.get("previous")
        if previous is not None:
            LOGGER.info(
                "Previous completion occurrence superseded: reminder_id=%s previous_occurrence_id=%s new_occurrence_id=%s",
                reminder.id,
                previous["id"],
                occurrence_id,
            )
        await delete_previous_occurrence_message(
            bot,
            previous,
            reason="new_planned_occurrence",
        )
        LOGGER.info(
            "Completion occurrence activated: reminder_id=%s occurrence_id=%s message_id=%s",
            reminder.id,
            occurrence_id,
            message.message_id,
        )
        return "sent"

    if activation_outcome in {"completed_same", "active_same"}:
        return "sent"

    await delete_message_best_effort(
        bot,
        chat_id=reminder.chat_id,
        message_id=message.message_id,
        reason=f"activation_{activation_outcome}",
    )
    return "sent_unrecorded"


async def repeat_active_occurrence(bot: Bot, occurrence) -> None:
    occurrence_id = int(occurrence["id"])
    old_message_id = int(occurrence["current_message_id"])
    occurrence = await asyncio.to_thread(
        get_repeatable_completion_occurrence,
        occurrence_id=occurrence_id,
        expected_message_id=old_message_id,
    )
    if occurrence is None:
        LOGGER.info(
            "Completion repeat skipped after state recheck: occurrence_id=%s expected_message_id=%s",
            occurrence_id,
            old_message_id,
        )
        return

    chat_id = int(occurrence["chat_id"])
    rendered_text = str(occurrence["rendered_text"])
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=rendered_text,
            reply_markup=build_completion_keyboard(occurrence_id),
        )
    except Exception as error:
        await record_delivery_error(
            occurrence_id=occurrence_id,
            status="active",
            message_id=old_message_id,
            attempts=int(occurrence["repeat_attempts"] or 0) + 1,
            error=error,
        )
        return

    sent_at = get_sent_at(message)
    interval = int(occurrence["parent_repeat_interval_minutes"] or 60)
    updated = await asyncio.to_thread(
        replace_active_completion_message,
        occurrence_id=occurrence_id,
        expected_message_id=old_message_id,
        new_message_id=message.message_id,
        sent_at=sent_at,
        next_repeat_at=sent_at + timedelta(minutes=interval),
    )

    if not updated:
        LOGGER.info(
            "Completion repeat compare-and-set did not match: occurrence_id=%s expected_message_id=%s new_message_id=%s",
            occurrence_id,
            old_message_id,
            message.message_id,
        )
        await delete_message_best_effort(
            bot,
            chat_id=chat_id,
            message_id=message.message_id,
            reason="repeat_compare_and_set",
        )
        return

    await delete_message_best_effort(
        bot,
        chat_id=chat_id,
        message_id=old_message_id,
        reason="repeat_replaced",
    )
    LOGGER.info(
        "Completion occurrence repeated: occurrence_id=%s old_message_id=%s new_message_id=%s",
        occurrence_id,
        old_message_id,
        message.message_id,
    )


async def finalize_terminal_completion_error(
    bot: Bot,
    *,
    occurrence,
    claim_token: str,
    error: Exception,
) -> None:
    occurrence_id = int(occurrence["id"])
    chat_id = int(occurrence["chat_id"])
    current_message_id = (
        int(occurrence["current_message_id"])
        if occurrence["current_message_id"] is not None
        else None
    )
    completed_text = f"{occurrence['rendered_text']}{COMPLETION_MESSAGE_SUFFIX}"
    fallback_succeeded = False
    if (
        current_message_id is not None
        and len(completed_text) <= TELEGRAM_MESSAGE_MAX_LENGTH
    ):
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=current_message_id,
                text=completed_text,
                reply_markup=None,
            )
            fallback_succeeded = True
        except Exception:
            LOGGER.warning(
                "Completion fallback edit failed: occurrence_id=%s message_id=%s",
                occurrence_id,
                current_message_id,
                exc_info=True,
            )
    if not fallback_succeeded and current_message_id is not None:
        try:
            await remove_message_keyboard_best_effort(
                bot,
                chat_id=chat_id,
                message_id=current_message_id,
            )
        except Exception:
            LOGGER.warning(
                "Completion fallback keyboard removal failed: occurrence_id=%s message_id=%s",
                occurrence_id,
                current_message_id,
                exc_info=True,
            )

    finalized = await asyncio.to_thread(
        finalize_failed_completion_publication,
        occurrence_id=occurrence_id,
        claim_token=claim_token,
        now=datetime.now(timezone.utc),
        last_error=f"{type(error).__name__}: {error}",
        fallback_succeeded=fallback_succeeded,
    )
    if not finalized:
        LOGGER.info(
            "Terminal completion finalization lost its CAS: occurrence_id=%s",
            occurrence_id,
        )


async def publish_completion_occurrence(bot: Bot, occurrence_id: int) -> str:
    now = datetime.now(timezone.utc)
    claim_token = uuid4().hex
    claim = await asyncio.to_thread(
        claim_completion_publication,
        occurrence_id=occurrence_id,
        claim_token=claim_token,
        now=now,
        stale_before=now - COMPLETION_DELIVERY_CLAIM_TIMEOUT,
    )
    outcome = str(claim["outcome"])
    if outcome != "claimed":
        return outcome

    occurrence = claim["occurrence"]
    message_id = occurrence["completion_message_id"]
    if message_id is None:
        completed_text = f"{occurrence['rendered_text']}{COMPLETION_MESSAGE_SUFFIX}"
        if len(completed_text) > TELEGRAM_MESSAGE_MAX_LENGTH:
            await finalize_terminal_completion_error(
                bot,
                occurrence=occurrence,
                claim_token=claim_token,
                error=ValueError("Completed reminder exceeds Telegram limit."),
            )
            return "completed_with_delivery_failure"
        try:
            message = await bot.send_message(
                chat_id=int(occurrence["chat_id"]),
                text=completed_text,
            )
        except Exception as error:
            attempts = int(occurrence["completion_attempts"] or 0) + 1
            if is_terminal_send_error(error) or (
                attempts >= COMPLETION_PUBLICATION_MAX_ATTEMPTS
                and not isinstance(error, TelegramRetryAfter)
            ):
                await finalize_terminal_completion_error(
                    bot,
                    occurrence=occurrence,
                    claim_token=claim_token,
                    error=error,
                )
                return "completed_with_delivery_failure"

            retry_at = datetime.now(timezone.utc) + get_retry_delay(error)
            await asyncio.to_thread(
                reschedule_completion_publication,
                occurrence_id=occurrence_id,
                claim_token=claim_token,
                next_attempt_at=retry_at,
                last_error=f"{type(error).__name__}: {error}",
            )
            return "publication_rescheduled"

        sent_at = get_sent_at(message)
        try:
            checkpoint_outcome = await asyncio.to_thread(
                checkpoint_completion_message,
                occurrence_id=occurrence_id,
                claim_token=claim_token,
                message_id=message.message_id,
                sent_at=sent_at,
            )
        except Exception:
            LOGGER.exception(
                "Completion checkpoint failed after Telegram send: occurrence_id=%s message_id=%s",
                occurrence_id,
                message.message_id,
            )
            await delete_message_best_effort(
                bot,
                chat_id=int(occurrence["chat_id"]),
                message_id=message.message_id,
                reason="completion_checkpoint_error",
            )
            return "sent_unrecorded"
        if checkpoint_outcome not in {"checkpointed", "checkpointed_same"}:
            await delete_message_best_effort(
                bot,
                chat_id=int(occurrence["chat_id"]),
                message_id=message.message_id,
                reason=f"completion_checkpoint_{checkpoint_outcome}",
            )
            return "sent_unrecorded"
        message_id = message.message_id

    finalized = await asyncio.to_thread(
        finalize_completion_publication,
        occurrence_id=occurrence_id,
        claim_token=claim_token,
        now=datetime.now(timezone.utc),
    )
    if finalized:
        return "completed"

    LOGGER.info(
        "Completion finalization lost its CAS after checkpoint: occurrence_id=%s message_id=%s",
        occurrence_id,
        message_id,
    )
    return "sent_unrecorded"


async def process_due_completion_occurrences(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    try:
        occurrences = await asyncio.to_thread(
            get_due_completion_occurrences,
            now=now,
            stale_before=now - COMPLETION_DELIVERY_CLAIM_TIMEOUT,
            limit=COMPLETION_WORKER_BATCH_SIZE,
        )
    except sqlite3.Error:
        LOGGER.exception("Could not load due completion occurrences.")
        return

    for occurrence in occurrences:
        try:
            if occurrence["status"] == "active":
                await repeat_active_occurrence(bot, occurrence)
                continue
            if occurrence["status"] == "completing":
                await publish_completion_occurrence(
                    bot,
                    int(occurrence["id"]),
                )
                continue

            reminder_row = await asyncio.to_thread(
                get_reminder_from_db,
                int(occurrence["reminder_id"]),
            )
            if reminder_row is None:
                continue
            reminder = build_reminder_read_data(reminder_row)
            await deliver_completion_occurrence(
                bot,
                reminder,
                parse_utc_datetime(occurrence["scheduled_for_utc"]),
                str(occurrence["rendered_text"]),
                occurrence_id=int(occurrence["id"]),
                expected_revision=int(occurrence["reminder_revision"]),
            )
        except Exception:
            LOGGER.exception(
                "Completion worker item failed: occurrence_id=%s",
                occurrence["id"],
            )


async def remove_message_keyboard_best_effort(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except TelegramAPIError as error:
        if isinstance(error, TelegramBadRequest) and (
            "message is not modified" in error.message.casefold()
        ):
            return
        LOGGER.warning(
            "Could not remove completion keyboard: chat_id=%s message_id=%s error_type=%s",
            chat_id,
            message_id,
            type(error).__name__,
        )


async def claim_completion_callback(
    *,
    occurrence_id: int,
    chat_id: int,
    callback_message_id: int,
    callback_message_sent_at: datetime | None,
    user_id: int,
    display_name: str,
) -> dict[str, object]:
    result = await asyncio.to_thread(
        complete_completion_occurrence,
        occurrence_id=occurrence_id,
        chat_id=chat_id,
        callback_message_id=callback_message_id,
        callback_message_sent_at=callback_message_sent_at,
        user_id=user_id,
        display_name=display_name,
        completed_at=datetime.now(timezone.utc),
    )
    outcome = str(result["outcome"])
    response_text = "Не удалось обработать кнопку."
    action = "none"
    if outcome == "completing":
        response_text = "Отмечено как выполненное."
        action = "publish"
    elif outcome == "completed":
        response_text = "Выполнено."
        action = "edit"
    elif outcome == "already_completing":
        response_text = "Выполнение уже обрабатывается."
    elif outcome == "already_completed":
        response_text = "Уже отмечено выполненным."
        action = "remove_keyboard"
    elif outcome in {"inactive", "reminder_inactive", "obsolete"}:
        response_text = "Это срабатывание уже неактуально."
        action = "remove_keyboard"
    elif outcome == "wrong_chat":
        response_text = "Кнопка относится к другому чату."
    elif outcome == "missing":
        response_text = "Напоминание больше не активно."

    return {
        **result,
        "response_text": response_text,
        "action": action,
        "callback_message_id": callback_message_id,
        "chat_id": chat_id,
        "occurrence_id": occurrence_id,
        "user_id": user_id,
    }


async def finish_completion_callback(bot: Bot, result: dict[str, object]) -> None:
    action = str(result["action"])
    occurrence_id = int(result["occurrence_id"])
    chat_id = int(result["chat_id"])
    callback_message_id = int(result["callback_message_id"])
    if action == "publish":
        await publish_completion_occurrence(bot, occurrence_id)
        return

    if action == "edit":
        await delete_previous_occurrence_message(
            bot,
            result.get("previous"),
            reason="fast_pending_completion",
        )
        current_message_id = int(result["message_id"])
        rendered_text = str(result["rendered_text"])
        completed_text = f"{rendered_text}{COMPLETION_MESSAGE_SUFFIX}"
        edited = False
        if len(completed_text) <= TELEGRAM_MESSAGE_MAX_LENGTH:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=current_message_id,
                    text=completed_text,
                    reply_markup=None,
                )
                edited = True
            except TelegramAPIError:
                LOGGER.warning(
                    "Could not mark completion message text; falling back to keyboard removal: occurrence_id=%s message_id=%s",
                    occurrence_id,
                    current_message_id,
                )
        else:
            LOGGER.warning(
                "Completed message exceeds Telegram limit; removing keyboard only: occurrence_id=%s length=%s",
                occurrence_id,
                len(completed_text),
            )
        if not edited:
            await remove_message_keyboard_best_effort(
                bot,
                chat_id=chat_id,
                message_id=current_message_id,
            )
        if callback_message_id != current_message_id:
            await remove_message_keyboard_best_effort(
                bot,
                chat_id=chat_id,
                message_id=callback_message_id,
            )
        LOGGER.info(
            "Completion occurrence completed: occurrence_id=%s chat_id=%s message_id=%s user_id=%s",
            occurrence_id,
            chat_id,
            current_message_id,
            result["user_id"],
        )
        return

    if action == "remove_keyboard":
        await remove_message_keyboard_best_effort(
            bot,
            chat_id=chat_id,
            message_id=callback_message_id,
        )


async def process_completion_callback(
    bot: Bot,
    **kwargs,
) -> str:
    result = await claim_completion_callback(**kwargs)
    await finish_completion_callback(bot, result)
    return str(result["response_text"])
