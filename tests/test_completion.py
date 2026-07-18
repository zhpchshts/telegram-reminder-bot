import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
import pytest

from app import completion_service as completion_service_module
from app import database as database_module
from app.completion_service import (
    deliver_completion_occurrence,
    publish_completion_occurrence,
    process_completion_callback,
    process_due_completion_occurrences,
    repeat_active_occurrence,
)
from app.database import (
    activate_claimed_completion_occurrence,
    checkpoint_completion_message,
    claim_completion_occurrence_delivery,
    claim_completion_publication,
    complete_completion_occurrence,
    create_reminder_in_db,
    delete_active_reminder_for_chat_in_db,
    get_active_reminder_from_db,
    get_due_completion_occurrences,
    finalize_completion_publication,
    reschedule_completion_occurrence_after_error,
    update_reminder_in_db,
)
from app.reminder_mapping import build_reminder_read_data


UTC = timezone.utc


class FakeBot:
    def __init__(self) -> None:
        self.sent = []
        self.deleted = []
        self.edited_text = []
        self.edited_markup = []
        self.next_message_id = 10
        self.sent_at = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        message = SimpleNamespace(
            message_id=self.next_message_id,
            date=self.sent_at,
        )
        self.next_message_id += 1
        return message

    async def delete_message(self, **kwargs):
        self.deleted.append(kwargs)
        return True

    async def edit_message_text(self, **kwargs):
        self.edited_text.append(kwargs)
        return True

    async def edit_message_reply_markup(self, **kwargs):
        self.edited_markup.append(kwargs)
        return True


def prepare_database(monkeypatch, tmp_path, *, delete_after_two_days=False) -> int:
    monkeypatch.setattr(database_module, "DB_PATH", tmp_path / "completion.db")
    database_module.init_db()
    return create_reminder_in_db(
        chat_id=100,
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 18, 12, 0),
        interval_days=1,
        timezone="UTC",
        delete_after_two_days=delete_after_two_days,
        requires_completion=True,
        repeat_interval_minutes=60,
    )


def claim_occurrence(reminder_id: int, *, token: str = "claim-1"):
    now = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
    return claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text="Проверить релиз",
        claim_token=token,
        now=now,
        stale_before=now - timedelta(minutes=2),
    )


def test_activation_and_watermark_are_committed_together(monkeypatch, tmp_path) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim = claim_occurrence(reminder_id)

    result = activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )

    assert result["outcome"] == "activated"
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
        reminder = connection.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    assert occurrence["status"] == "active"
    assert occurrence["reminder_revision"] == 1
    assert occurrence["current_message_id"] == 50
    assert reminder["last_handled_scheduled_for_utc"] == "2026-07-18T08:00:00+00:00"
    assert (
        build_reminder_read_data(
            get_active_reminder_from_db(reminder_id)
        ).awaiting_completion
        is True
    )


def test_awaiting_completion_is_false_without_delivered_occurrence(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)

    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))

    assert reminder.awaiting_completion is False


def test_reentry_for_active_occurrence_only_repairs_watermark(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )
    with database_module.get_connection() as connection:
        connection.execute(
            "UPDATE reminders SET last_handled_scheduled_for_utc = NULL WHERE id = ?",
            (reminder_id,),
        )

    result = claim_occurrence(reminder_id, token="claim-2")

    assert result["outcome"] == "already_delivered"
    with database_module.get_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM reminder_completion_occurrences"
        ).fetchone()[0]
        watermark = connection.execute(
            "SELECT last_handled_scheduled_for_utc FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()[0]
    assert count == 1
    assert watermark == "2026-07-18T08:00:00+00:00"


def test_reentry_for_completed_once_occurrence_repairs_parent_state(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(database_module, "DB_PATH", tmp_path / "completed-once.db")
    database_module.init_db()
    reminder_id = create_reminder_in_db(
        chat_id=100,
        reminder_text="Закрыть задачу",
        schedule_type="once",
        start_at=datetime(2026, 7, 18, 12, 0),
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=60,
    )
    claim = claim_occurrence(reminder_id)
    complete_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        chat_id=100,
        callback_message_id=77,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )
    with database_module.get_connection() as connection:
        connection.execute(
            """
            UPDATE reminders
            SET status = 'active', last_handled_scheduled_for_utc = NULL
            WHERE id = ?
            """,
            (reminder_id,),
        )

    result = claim_occurrence(reminder_id, token="claim-2")

    assert result["outcome"] == "already_completed"
    with database_module.get_connection() as connection:
        reminder = connection.execute(
            "SELECT status, last_handled_scheduled_for_utc FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()
    assert reminder["status"] == "sent"
    assert reminder["last_handled_scheduled_for_utc"] == "2026-07-18T08:00:00+00:00"


def test_fast_callback_completes_pending_and_invalidates_claim(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim = claim_occurrence(reminder_id)

    completed = complete_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        chat_id=100,
        callback_message_id=77,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )
    stale_activation = activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=77,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )

    assert completed["outcome"] == "completed"
    assert stale_activation["outcome"] == "completed_same"
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
    assert occurrence["status"] == "completed"
    assert occurrence["delivery_claim_token"] is None
    assert occurrence["completed_by_user_id"] == 200


def test_stale_pending_can_be_reclaimed_and_old_token_loses(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    first = claim_occurrence(reminder_id)

    now = datetime(2026, 7, 18, 9, 3, tzinfo=UTC)
    second = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text="Проверить релиз",
        claim_token="claim-2",
        now=now,
        stale_before=now - timedelta(minutes=2),
    )
    stale = activate_claimed_completion_occurrence(
        occurrence_id=first["occurrence_id"],
        claim_token="claim-1",
        message_id=70,
        sent_at=now,
    )

    assert second["outcome"] == "claimed"
    assert second["is_recovery"] is True
    assert stale["outcome"] == "stale"


def test_fresh_pending_claim_is_not_reclaimed(monkeypatch, tmp_path) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim_occurrence(reminder_id)
    now = datetime(2026, 7, 18, 9, 1, tzinfo=UTC)

    second = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text="Проверить релиз",
        claim_token="claim-2",
        now=now,
        stale_before=now - timedelta(minutes=2),
    )

    assert second["outcome"] == "delivery_in_progress"
    with database_module.get_connection() as connection:
        token = connection.execute(
            "SELECT delivery_claim_token FROM reminder_completion_occurrences"
        ).fetchone()[0]
    assert token == "claim-1"


def test_update_before_claim_prevents_stale_delivery(monkeypatch, tmp_path) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    stale_reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    assert stale_reminder.revision == 1
    assert update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Новый текст",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 19, 12, 0),
        interval_days=1,
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=30,
    )
    bot = FakeBot()

    result = asyncio.run(
        deliver_completion_occurrence(
            bot,
            stale_reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )

    assert result == "stale_revision"
    assert bot.sent == []
    with database_module.get_connection() as connection:
        occurrence_count = connection.execute(
            "SELECT COUNT(*) FROM reminder_completion_occurrences"
        ).fetchone()[0]
        revision = connection.execute(
            "SELECT revision FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()[0]
    assert occurrence_count == 0
    assert revision == 2


def test_pending_worker_does_not_recreate_cancelled_old_revision_after_update(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim_occurrence(reminder_id)
    with database_module.get_connection() as connection:
        stale_due = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()

    assert update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Новый текст",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 19, 12, 0),
        interval_days=1,
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=30,
    )
    monkeypatch.setattr(
        completion_service_module,
        "get_due_completion_occurrences",
        lambda **kwargs: [stale_due],
    )
    bot = FakeBot()

    asyncio.run(process_due_completion_occurrences(bot))

    assert bot.sent == []
    with database_module.get_connection() as connection:
        occurrences = connection.execute(
            """
            SELECT reminder_revision, status, rendered_text, scheduled_for_utc
            FROM reminder_completion_occurrences
            """
        ).fetchall()
    assert [tuple(row) for row in occurrences] == [
        (1, "cancelled", "Проверить релиз", "2026-07-18T08:00:00+00:00")
    ]


def test_older_pending_retry_cannot_supersede_newer_active_occurrence(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    older = claim_occurrence(reminder_id, token="older-claim")
    assert reschedule_completion_occurrence_after_error(
        occurrence_id=older["occurrence_id"],
        expected_status="pending",
        expected_message_id=None,
        next_attempt_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        attempts=1,
        last_error="retry later",
    )
    newer = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        rendered_text="Новое срабатывание",
        claim_token="newer-claim",
        now=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
        stale_before=datetime(2026, 7, 18, 8, 59, tzinfo=UTC),
    )
    assert (
        activate_claimed_completion_occurrence(
            occurrence_id=newer["occurrence_id"],
            claim_token="newer-claim",
            message_id=90,
            sent_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
        )["outcome"]
        == "activated"
    )

    obsolete = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        occurrence_id=older["occurrence_id"],
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text="Проверить релиз",
        claim_token="late-older-claim",
        now=datetime(2026, 7, 18, 10, 1, tzinfo=UTC),
        stale_before=datetime(2026, 7, 18, 9, 59, tzinfo=UTC),
    )

    assert obsolete["outcome"] == "obsolete"
    with database_module.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT scheduled_for_utc, status, next_repeat_at_utc,
                   delivery_claim_token
            FROM reminder_completion_occurrences
            ORDER BY scheduled_for_utc
            """
        ).fetchall()
    assert tuple(rows[0]) == (
        "2026-07-18T08:00:00+00:00",
        "superseded",
        None,
        None,
    )
    assert rows[1]["status"] == "active"


def test_old_pending_activation_loses_to_newer_occurrence(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    original_send = bot.send_message

    async def send_older_after_newer_wins(**kwargs):
        message = await original_send(**kwargs)
        newer = claim_completion_occurrence_delivery(
            reminder_id=reminder_id,
            expected_revision=1,
            scheduled_for_utc=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
            rendered_text="Новое срабатывание",
            claim_token="newer-claim",
            now=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
            stale_before=datetime(2026, 7, 18, 8, 59, tzinfo=UTC),
        )
        activation = activate_claimed_completion_occurrence(
            occurrence_id=newer["occurrence_id"],
            claim_token="newer-claim",
            message_id=90,
            sent_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
        )
        assert activation["outcome"] == "activated"
        return message

    bot.send_message = send_older_after_newer_wins

    result = asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )

    assert result == "sent_unrecorded"
    assert bot.deleted == [{"chat_id": 100, "message_id": 10}]
    with database_module.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT scheduled_for_utc, status, current_message_id
            FROM reminder_completion_occurrences
            ORDER BY scheduled_for_utc
            """
        ).fetchall()
    assert tuple(rows[0]) == ("2026-07-18T08:00:00+00:00", "superseded", None)
    assert tuple(rows[1]) == ("2026-07-18T09:00:00+00:00", "active", 90)


def test_old_pending_fast_callback_cannot_complete_over_newer_occurrence(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    older = claim_occurrence(reminder_id, token="older-claim")
    newer = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        rendered_text="Новое срабатывание",
        claim_token="newer-claim",
        now=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
        stale_before=datetime(2026, 7, 18, 8, 59, tzinfo=UTC),
    )
    activate_claimed_completion_occurrence(
        occurrence_id=newer["occurrence_id"],
        claim_token="newer-claim",
        message_id=90,
        sent_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )

    result = complete_completion_occurrence(
        occurrence_id=older["occurrence_id"],
        chat_id=100,
        callback_message_id=80,
        callback_message_sent_at=datetime(2026, 7, 18, 8, 1, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 2, tzinfo=UTC),
    )

    assert result["outcome"] == "inactive"
    with database_module.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT scheduled_for_utc, status, current_message_id
            FROM reminder_completion_occurrences
            ORDER BY scheduled_for_utc
            """
        ).fetchall()
    assert tuple(rows[0]) == ("2026-07-18T08:00:00+00:00", "superseded", None)
    assert tuple(rows[1]) == ("2026-07-18T09:00:00+00:00", "active", 90)


def test_pending_retry_after_longer_than_claim_timeout_is_not_reclaimed_early(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))

    class RetryAfterBot(FakeBot):
        async def send_message(self, **kwargs):
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=100, text="Проверить релиз"),
                message="Too Many Requests",
                retry_after=600,
            )

    result = asyncio.run(
        deliver_completion_occurrence(
            RetryAfterBot(),
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )
    assert result == "delivery_failed"

    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
    retry_at = datetime.fromisoformat(occurrence["next_repeat_at_utc"])
    before_retry = retry_at - timedelta(minutes=5)
    assert occurrence["delivery_claim_token"] is None
    assert occurrence["delivery_claimed_at_utc"] is None
    assert (
        get_due_completion_occurrences(
            now=before_retry,
            stale_before=before_retry - timedelta(minutes=2),
            limit=100,
        )
        == []
    )

    claim = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text="Проверить релиз",
        claim_token="early-retry",
        now=before_retry,
        stale_before=before_retry - timedelta(minutes=2),
    )
    assert claim["outcome"] == "retry_scheduled"


def test_terminal_failure_finalizes_one_time_reminder_as_missed(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(database_module, "DB_PATH", tmp_path / "terminal-once.db")
    database_module.init_db()
    reminder_id = create_reminder_in_db(
        chat_id=100,
        reminder_text="Недоступная задача",
        schedule_type="once",
        start_at=datetime(2026, 7, 18, 12, 0),
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=60,
    )
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))

    class ForbiddenBot(FakeBot):
        async def send_message(self, **kwargs):
            raise TelegramForbiddenError(
                method=SendMessage(chat_id=100, text="Недоступная задача"),
                message="Forbidden",
            )

    result = asyncio.run(
        deliver_completion_occurrence(
            ForbiddenBot(),
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Недоступная задача",
        )
    )

    assert result == "delivery_failed"
    with database_module.get_connection() as connection:
        occurrence_status = connection.execute(
            "SELECT status FROM reminder_completion_occurrences"
        ).fetchone()[0]
        parent = connection.execute(
            "SELECT status, last_handled_scheduled_for_utc FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()
    assert occurrence_status == "failed"
    assert tuple(parent) == ("missed", "2026-07-18T08:00:00+00:00")

    recovery = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text="Недоступная задача",
        claim_token="restart-claim",
        now=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        stale_before=datetime(2026, 7, 18, 8, 58, tzinfo=UTC),
    )
    assert recovery["outcome"] == "inactive"


def test_pending_with_message_id_is_recovered_without_resending(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim = claim_occurrence(reminder_id)
    with database_module.get_connection() as connection:
        connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET current_message_id = 55,
                current_message_sent_at_utc = '2026-07-18T09:00:00+00:00'
            WHERE id = ?
            """,
            (claim["occurrence_id"],),
        )
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()

    result = asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )

    assert result == "already_delivered"
    assert bot.sent == []
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT status, current_message_id FROM reminder_completion_occurrences"
        ).fetchone()
        watermark = connection.execute(
            "SELECT last_handled_scheduled_for_utc FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()[0]
    assert tuple(occurrence) == ("active", 55)
    assert watermark == "2026-07-18T08:00:00+00:00"


def test_update_atomically_cancels_live_occurrence(monkeypatch, tmp_path) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim_occurrence(reminder_id)

    updated = update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Новый текст",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 19, 12, 0),
        interval_days=1,
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=30,
    )

    assert updated is True
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
        reminder = connection.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    assert reminder["text"] == "Новый текст"
    assert occurrence["status"] == "cancelled"
    assert occurrence["delivery_claim_token"] is None


def test_delete_atomically_cancels_live_occurrence(monkeypatch, tmp_path) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim_occurrence(reminder_id)

    deleted = delete_active_reminder_for_chat_in_db(reminder_id, 100)

    assert deleted is True
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
        reminder = connection.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    assert reminder["status"] == "deleted"
    assert occurrence["status"] == "cancelled"
    assert occurrence["delivery_claim_token"] is None


def test_repeat_rechecks_parent_before_sending_stale_due_row(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )
    with database_module.get_connection() as connection:
        stale_due_row = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
    assert delete_active_reminder_for_chat_in_db(reminder_id, 100) is True
    bot = FakeBot()

    asyncio.run(repeat_active_occurrence(bot, stale_due_row))

    assert bot.sent == []


def test_delivery_sends_button_and_does_not_duplicate_active(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    scheduled_for = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)

    first = asyncio.run(
        deliver_completion_occurrence(bot, reminder, scheduled_for, "Проверить релиз")
    )
    second = asyncio.run(
        deliver_completion_occurrence(bot, reminder, scheduled_for, "Проверить релиз")
    )

    assert first == "sent"
    assert second == "already_delivered"
    assert len(bot.sent) == 1
    assert bot.sent[0]["reply_markup"].inline_keyboard[0][0].text == "✅ Сделано"


def test_successful_send_with_failed_activation_is_deleted_and_not_watermarked(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()

    def fail_activation(**kwargs):
        raise database_module.sqlite3.OperationalError("simulated commit failure")

    monkeypatch.setattr(
        completion_service_module,
        "activate_claimed_completion_occurrence",
        fail_activation,
    )

    result = asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )

    assert result == "sent_unrecorded"
    assert bot.deleted == [{"chat_id": 100, "message_id": 10}]
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT status, current_message_id FROM reminder_completion_occurrences"
        ).fetchone()
        watermark = connection.execute(
            "SELECT last_handled_scheduled_for_utc FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()[0]
    assert tuple(occurrence) == ("pending", None)
    assert watermark is None


def test_sender_keeps_message_completed_by_fast_callback(monkeypatch, tmp_path) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    original_activation = activate_claimed_completion_occurrence

    def complete_before_activation(**kwargs):
        complete_completion_occurrence(
            occurrence_id=kwargs["occurrence_id"],
            chat_id=100,
            callback_message_id=kwargs["message_id"],
            callback_message_sent_at=kwargs["sent_at"],
            user_id=200,
            display_name="Участник",
            completed_at=kwargs["sent_at"] + timedelta(seconds=1),
        )
        return original_activation(**kwargs)

    monkeypatch.setattr(
        completion_service_module,
        "activate_claimed_completion_occurrence",
        complete_before_activation,
    )

    result = asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )

    assert result == "sent"
    assert bot.deleted == []


def test_update_during_send_prevents_activation_and_deletes_extra_message(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    original_send = bot.send_message

    async def send_then_update(**kwargs):
        message = await original_send(**kwargs)
        update_reminder_in_db(
            reminder_id=reminder_id,
            chat_id=100,
            reminder_text="Новый текст",
            schedule_type="every_days",
            start_at=datetime(2026, 7, 19, 12, 0),
            interval_days=1,
            timezone="UTC",
            requires_completion=True,
            repeat_interval_minutes=30,
        )
        return message

    bot.send_message = send_then_update

    result = asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )

    assert result == "sent_unrecorded"
    assert bot.deleted == [{"chat_id": 100, "message_id": 10}]
    with database_module.get_connection() as connection:
        status = connection.execute(
            "SELECT status FROM reminder_completion_occurrences"
        ).fetchone()[0]
    assert status == "cancelled"


def test_delete_during_send_keeps_parent_deleted_and_deletes_extra_message(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    original_send = bot.send_message

    async def send_then_delete(**kwargs):
        message = await original_send(**kwargs)
        assert delete_active_reminder_for_chat_in_db(reminder_id, 100) is True
        return message

    bot.send_message = send_then_delete

    result = asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )

    assert result == "sent_unrecorded"
    assert bot.deleted == [{"chat_id": 100, "message_id": 10}]
    with database_module.get_connection() as connection:
        parent_status = connection.execute(
            "SELECT status FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()[0]
    assert parent_status == "deleted"


def test_callback_marks_current_message_and_removes_keyboard(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )
    with database_module.get_connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM reminder_message_deletion_queue"
            ).fetchone()[0]
            == 0
        )

    result = asyncio.run(
        process_completion_callback(
            bot,
            occurrence_id=1,
            chat_id=100,
            callback_message_id=10,
            callback_message_sent_at=bot.sent_at,
            user_id=200,
            display_name="Участник",
        )
    )

    assert result == "Выполнено."
    assert bot.edited_text[0]["text"].endswith("✅ Выполнено")
    with database_module.get_connection() as connection:
        status = connection.execute(
            "SELECT status FROM reminder_completion_occurrences"
        ).fetchone()[0]
    assert status == "completed"


def test_completion_with_auto_delete_sends_final_and_queues_both_messages(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )
    with database_module.get_connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM reminder_message_deletion_queue"
            ).fetchone()[0]
            == 0
        )

    result = asyncio.run(
        process_completion_callback(
            bot,
            occurrence_id=1,
            chat_id=100,
            callback_message_id=10,
            callback_message_sent_at=bot.sent_at,
            user_id=200,
            display_name="Участник",
        )
    )

    assert result == "Отмечено как выполненное."
    assert len(bot.sent) == 2
    assert bot.sent[1] == {
        "chat_id": 100,
        "text": "Проверить релиз\n\n✅ Выполнено",
    }
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
        queued = connection.execute(
            """
            SELECT message_id, sent_at_utc, delete_at_utc
            FROM reminder_message_deletion_queue
            ORDER BY message_id
            """
        ).fetchall()
    assert occurrence["status"] == "completed"
    assert occurrence["completion_delivery_status"] == "sent"
    assert occurrence["completion_message_id"] == 11
    assert [row["message_id"] for row in queued] == [10, 11]
    assert queued[0]["sent_at_utc"] == bot.sent_at.isoformat(timespec="seconds")
    assert datetime.fromisoformat(queued[0]["delete_at_utc"]) < datetime.fromisoformat(
        queued[1]["delete_at_utc"]
    )
    assert datetime.fromisoformat(queued[1]["delete_at_utc"]) == (
        bot.sent_at + timedelta(hours=47, minutes=45)
    )


def test_auto_delete_completion_is_awaiting_while_completing(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    claim = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )

    result = complete_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        chat_id=100,
        callback_message_id=50,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )

    assert result["outcome"] == "completing"
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    assert reminder.awaiting_completion is True


def test_terminal_final_send_and_fallback_failure_are_logically_completed(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(database_module, "DB_PATH", tmp_path / "terminal-final.db")
    database_module.init_db()
    reminder_id = create_reminder_in_db(
        chat_id=100,
        reminder_text="Закрыть задачу",
        schedule_type="once",
        start_at=datetime(2026, 7, 18, 12, 0),
        timezone="UTC",
        delete_after_two_days=True,
        requires_completion=True,
        repeat_interval_minutes=60,
    )
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))

    class TerminalFinalBot(FakeBot):
        async def send_message(self, **kwargs):
            if self.sent:
                raise TelegramForbiddenError(
                    method=SendMessage(chat_id=100, text=kwargs["text"]),
                    message="Forbidden",
                )
            return await super().send_message(**kwargs)

        async def edit_message_text(self, **kwargs):
            raise TelegramForbiddenError(
                method=SendMessage(chat_id=100, text=kwargs["text"]),
                message="Forbidden",
            )

        async def edit_message_reply_markup(self, **kwargs):
            raise TelegramForbiddenError(
                method=SendMessage(chat_id=100, text="fallback"),
                message="Forbidden",
            )

    bot = TerminalFinalBot()
    asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Закрыть задачу",
        )
    )
    asyncio.run(
        process_completion_callback(
            bot,
            occurrence_id=1,
            chat_id=100,
            callback_message_id=10,
            callback_message_sent_at=bot.sent_at,
            user_id=200,
            display_name="Участник",
        )
    )

    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
        parent_status = connection.execute(
            "SELECT status FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()[0]
    assert occurrence["status"] == "completed"
    assert occurrence["completion_delivery_status"] == "failed"
    assert occurrence["completion_claim_token"] is None
    assert occurrence["completion_next_attempt_at_utc"] is None
    assert occurrence["next_repeat_at_utc"] is None
    assert parent_status == "sent"
    assert (
        get_due_completion_occurrences(
            now=datetime.now(UTC) + timedelta(days=1),
            stale_before=datetime.now(UTC),
            limit=10,
        )
        == []
    )


def test_checkpoint_recovery_finalizes_without_resending(monkeypatch, tmp_path) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    claim = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )
    complete_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        chat_id=100,
        callback_message_id=50,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )
    publication_claim = claim_completion_publication(
        occurrence_id=claim["occurrence_id"],
        claim_token="publication-1",
        now=datetime.now(UTC),
        stale_before=datetime.now(UTC) - timedelta(minutes=2),
    )
    assert publication_claim["outcome"] == "claimed"
    assert (
        checkpoint_completion_message(
            occurrence_id=claim["occurrence_id"],
            claim_token="publication-1",
            message_id=88,
            sent_at=datetime(2026, 7, 18, 9, 2, tzinfo=UTC),
        )
        == "checkpointed"
    )
    bot = FakeBot()

    asyncio.run(process_due_completion_occurrences(bot))

    assert bot.sent == []
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT status, completion_message_id FROM reminder_completion_occurrences"
        ).fetchone()
    assert tuple(occurrence) == ("completed", 88)


def test_finalization_queue_rolls_back_as_one_transaction(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    claim = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )
    complete_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        chat_id=100,
        callback_message_id=50,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )
    claim_completion_publication(
        occurrence_id=claim["occurrence_id"],
        claim_token="publication-1",
        now=datetime.now(UTC),
        stale_before=datetime.now(UTC) - timedelta(minutes=2),
    )
    checkpoint_completion_message(
        occurrence_id=claim["occurrence_id"],
        claim_token="publication-1",
        message_id=88,
        sent_at=datetime(2026, 7, 18, 9, 2, tzinfo=UTC),
    )
    original_enqueue = database_module._enqueue_reminder_message_deletion
    calls = 0

    def fail_second_enqueue(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("simulated queue failure")
        return original_enqueue(*args, **kwargs)

    monkeypatch.setattr(
        database_module,
        "_enqueue_reminder_message_deletion",
        fail_second_enqueue,
    )

    with pytest.raises(sqlite3.OperationalError, match="simulated queue failure"):
        finalize_completion_publication(
            occurrence_id=claim["occurrence_id"],
            claim_token="publication-1",
            now=datetime.now(UTC),
        )

    with database_module.get_connection() as connection:
        status = connection.execute(
            "SELECT status FROM reminder_completion_occurrences"
        ).fetchone()[0]
        queue_count = connection.execute(
            "SELECT COUNT(*) FROM reminder_message_deletion_queue"
        ).fetchone()[0]
    assert status == "completing"
    assert queue_count == 0


def test_new_planned_occurrence_can_activate_while_old_one_completes(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    older = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=older["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )
    complete_completion_occurrence(
        occurrence_id=older["occurrence_id"],
        chat_id=100,
        callback_message_id=50,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )
    newer = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        rendered_text="Новое срабатывание",
        claim_token="claim-newer",
        now=datetime(2026, 7, 18, 10, 1, tzinfo=UTC),
        stale_before=datetime(2026, 7, 18, 9, 59, tzinfo=UTC),
    )
    assert (
        activate_claimed_completion_occurrence(
            occurrence_id=newer["occurrence_id"],
            claim_token="claim-newer",
            message_id=90,
            sent_at=datetime(2026, 7, 18, 10, 1, tzinfo=UTC),
        )["outcome"]
        == "activated"
    )

    bot = FakeBot()
    asyncio.run(publish_completion_occurrence(bot, older["occurrence_id"]))

    with database_module.get_connection() as connection:
        occurrences = connection.execute(
            """
            SELECT scheduled_for_utc, status
            FROM reminder_completion_occurrences
            ORDER BY scheduled_for_utc
            """
        ).fetchall()
        watermark = connection.execute(
            "SELECT last_handled_scheduled_for_utc FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()[0]
    assert [tuple(row) for row in occurrences] == [
        ("2026-07-18T08:00:00+00:00", "completed"),
        ("2026-07-18T10:00:00+00:00", "active"),
    ]
    assert watermark == "2026-07-18T10:00:00+00:00"


def test_old_callback_copy_and_current_message_are_both_queued(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    claim = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )
    bot = FakeBot()
    bot.next_message_id = 60

    asyncio.run(
        process_completion_callback(
            bot,
            occurrence_id=claim["occurrence_id"],
            chat_id=100,
            callback_message_id=40,
            callback_message_sent_at=datetime(2026, 7, 18, 8, 30, tzinfo=UTC),
            user_id=200,
            display_name="Участник",
        )
    )

    with database_module.get_connection() as connection:
        queued = connection.execute(
            """
            SELECT message_id, sent_at_utc
            FROM reminder_message_deletion_queue
            ORDER BY message_id
            """
        ).fetchall()
    assert [row["message_id"] for row in queued] == [40, 50, 60]
    assert queued[0]["sent_at_utc"] == "2026-07-18T08:30:00+00:00"
    assert queued[1]["sent_at_utc"] == "2026-07-18T09:00:00+00:00"


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_update_or_delete_cancels_completing_and_queues_checkpoint(
    monkeypatch, tmp_path, operation
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    claim = claim_occurrence(reminder_id)
    activate_claimed_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        claim_token="claim-1",
        message_id=50,
        sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )
    complete_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        chat_id=100,
        callback_message_id=50,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )
    claim_completion_publication(
        occurrence_id=claim["occurrence_id"],
        claim_token="publication-1",
        now=datetime.now(UTC),
        stale_before=datetime.now(UTC) - timedelta(minutes=2),
    )
    checkpoint_completion_message(
        occurrence_id=claim["occurrence_id"],
        claim_token="publication-1",
        message_id=88,
        sent_at=datetime(2026, 7, 18, 9, 2, tzinfo=UTC),
    )

    if operation == "update":
        assert update_reminder_in_db(
            reminder_id=reminder_id,
            chat_id=100,
            reminder_text="Новый текст",
            schedule_type="every_days",
            start_at=datetime(2026, 7, 19, 12, 0),
            interval_days=1,
            timezone="UTC",
            requires_completion=True,
            repeat_interval_minutes=30,
        )
    else:
        assert delete_active_reminder_for_chat_in_db(reminder_id, 100)

    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT status, completion_claim_token FROM reminder_completion_occurrences"
        ).fetchone()
        queued = connection.execute(
            "SELECT message_id FROM reminder_message_deletion_queue"
        ).fetchall()
    assert tuple(occurrence) == ("cancelled", None)
    assert [row["message_id"] for row in queued] == [88]


def test_final_publication_retry_after_does_not_resume_repeats(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))

    class RetryFinalBot(FakeBot):
        async def send_message(self, **kwargs):
            if self.sent:
                raise TelegramRetryAfter(
                    method=SendMessage(chat_id=100, text=kwargs["text"]),
                    message="Too Many Requests",
                    retry_after=600,
                )
            return await super().send_message(**kwargs)

    bot = RetryFinalBot()
    asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )
    before = datetime.now(UTC)
    asyncio.run(
        process_completion_callback(
            bot,
            occurrence_id=1,
            chat_id=100,
            callback_message_id=10,
            callback_message_sent_at=bot.sent_at,
            user_id=200,
            display_name="Участник",
        )
    )

    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences"
        ).fetchone()
    retry_at = datetime.fromisoformat(occurrence["completion_next_attempt_at_utc"])
    assert occurrence["status"] == "completing"
    assert occurrence["completion_claim_token"] is None
    assert occurrence["next_repeat_at_utc"] is None
    assert retry_at >= before + timedelta(seconds=599)


def test_parallel_completion_publishers_create_one_final_message(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(
        monkeypatch,
        tmp_path,
        delete_after_two_days=True,
    )
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))

    class SlowFinalBot(FakeBot):
        async def send_message(self, **kwargs):
            if self.sent:
                await asyncio.sleep(0.05)
            return await super().send_message(**kwargs)

    bot = SlowFinalBot()
    asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )
    complete_completion_occurrence(
        occurrence_id=1,
        chat_id=100,
        callback_message_id=10,
        callback_message_sent_at=bot.sent_at,
        user_id=200,
        display_name="Участник",
        completed_at=datetime.now(UTC),
    )

    async def publish_twice():
        return await asyncio.gather(
            publish_completion_occurrence(bot, 1),
            publish_completion_occurrence(bot, 1),
        )

    outcomes = asyncio.run(publish_twice())

    assert len(bot.sent) == 2
    assert sorted(outcomes) == ["completed", "publication_in_progress"]
    with database_module.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT status, completion_message_id FROM reminder_completion_occurrences"
        ).fetchone()
    assert tuple(occurrence) == ("completed", 11)


def test_fast_callback_marks_one_time_reminder_as_sent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(database_module, "DB_PATH", tmp_path / "completion-once.db")
    database_module.init_db()
    reminder_id = create_reminder_in_db(
        chat_id=100,
        reminder_text="Закрыть задачу",
        schedule_type="once",
        start_at=datetime(2026, 7, 18, 12, 0),
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=60,
    )
    claim = claim_occurrence(reminder_id)

    result = complete_completion_occurrence(
        occurrence_id=claim["occurrence_id"],
        chat_id=100,
        callback_message_id=77,
        callback_message_sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        user_id=200,
        display_name="Участник",
        completed_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
    )

    assert result["outcome"] == "completed"
    with database_module.get_connection() as connection:
        status = connection.execute(
            "SELECT status FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()[0]
    assert status == "sent"


def test_callback_falls_back_to_keyboard_removal_when_text_would_overflow(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    claim = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text="x" * 4090,
        claim_token="claim-long",
        now=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        stale_before=datetime(2026, 7, 18, 8, 58, tzinfo=UTC),
    )
    bot = FakeBot()

    result = asyncio.run(
        process_completion_callback(
            bot,
            occurrence_id=claim["occurrence_id"],
            chat_id=100,
            callback_message_id=77,
            callback_message_sent_at=bot.sent_at,
            user_id=200,
            display_name="Участник",
        )
    )

    assert result == "Выполнено."
    assert bot.edited_text == []
    assert bot.edited_markup == [
        {"chat_id": 100, "message_id": 77, "reply_markup": None}
    ]


def test_callback_edits_completed_text_at_exact_telegram_limit(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    rendered_text = "x" * (4096 - len("\n\n✅ Выполнено"))
    claim = claim_completion_occurrence_delivery(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        rendered_text=rendered_text,
        claim_token="claim-limit",
        now=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        stale_before=datetime(2026, 7, 18, 8, 58, tzinfo=UTC),
    )
    bot = FakeBot()

    result = asyncio.run(
        process_completion_callback(
            bot,
            occurrence_id=claim["occurrence_id"],
            chat_id=100,
            callback_message_id=77,
            callback_message_sent_at=bot.sent_at,
            user_id=200,
            display_name="Участник",
        )
    )

    assert result == "Выполнено."
    assert len(bot.edited_text[0]["text"]) == 4096
    assert bot.edited_markup == []


def test_final_rendered_text_limit_is_checked_before_send(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()

    try:
        asyncio.run(
            deliver_completion_occurrence(
                bot,
                reminder,
                datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
                f"Опоздавшее напоминание: {'x' * 4090}",
            )
        )
    except ValueError as error:
        assert str(error) == "Rendered completion reminder exceeds Telegram limit."
    else:
        raise AssertionError("Expected the final rendered text length check to fail.")

    assert bot.sent == []


def test_due_worker_replaces_message_then_deletes_previous(
    monkeypatch, tmp_path
) -> None:
    reminder_id = prepare_database(monkeypatch, tmp_path)
    reminder = build_reminder_read_data(get_active_reminder_from_db(reminder_id))
    bot = FakeBot()
    asyncio.run(
        deliver_completion_occurrence(
            bot,
            reminder,
            datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
            "Проверить релиз",
        )
    )
    with database_module.get_connection() as connection:
        connection.execute(
            "UPDATE reminder_completion_occurrences SET next_repeat_at_utc = ?",
            ("2000-01-01T00:00:00+00:00",),
        )

    asyncio.run(process_due_completion_occurrences(bot))

    assert len(bot.sent) == 2
    assert bot.deleted == [{"chat_id": 100, "message_id": 10}]
    with database_module.get_connection() as connection:
        message_id = connection.execute(
            "SELECT current_message_id FROM reminder_completion_occurrences"
        ).fetchone()[0]
    assert message_id == 11


def test_one_failed_occurrence_does_not_stop_worker_batch(
    monkeypatch, tmp_path
) -> None:
    first_reminder_id = prepare_database(monkeypatch, tmp_path)
    second_reminder_id = create_reminder_in_db(
        chat_id=200,
        reminder_text="Вторая задача",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 18, 12, 0),
        interval_days=1,
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=60,
    )
    for reminder_id, message_id in (
        (first_reminder_id, 50),
        (second_reminder_id, 60),
    ):
        claim = claim_occurrence(reminder_id, token=f"claim-{reminder_id}")
        activate_claimed_completion_occurrence(
            occurrence_id=claim["occurrence_id"],
            claim_token=f"claim-{reminder_id}",
            message_id=message_id,
            sent_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        )
    with database_module.get_connection() as connection:
        connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET next_repeat_at_utc = '2000-01-01T00:00:00+00:00'
            """
        )

    bot = FakeBot()
    bot.next_message_id = 100
    original_send = bot.send_message
    send_attempts = 0

    async def fail_first_send(**kwargs):
        nonlocal send_attempts
        send_attempts += 1
        if send_attempts == 1:
            raise RuntimeError("temporary send failure")
        return await original_send(**kwargs)

    bot.send_message = fail_first_send

    asyncio.run(process_due_completion_occurrences(bot))

    assert send_attempts == 2
    with database_module.get_connection() as connection:
        occurrences = connection.execute(
            """
            SELECT reminder_id, current_message_id, repeat_attempts
            FROM reminder_completion_occurrences
            ORDER BY reminder_id
            """
        ).fetchall()
    assert tuple(occurrences[0]) == (first_reminder_id, 50, 1)
    assert tuple(occurrences[1]) == (second_reminder_id, 100, 0)


def test_one_failed_pending_does_not_stop_worker_batch(monkeypatch, tmp_path) -> None:
    first_reminder_id = prepare_database(monkeypatch, tmp_path)
    second_reminder_id = create_reminder_in_db(
        chat_id=200,
        reminder_text="Вторая задача",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 18, 12, 0),
        interval_days=1,
        timezone="UTC",
        requires_completion=True,
        repeat_interval_minutes=60,
    )
    claim_occurrence(first_reminder_id, token="claim-first")
    claim_occurrence(second_reminder_id, token="claim-second")
    with database_module.get_connection() as connection:
        connection.execute(
            """
            UPDATE reminder_completion_occurrences
            SET delivery_claimed_at_utc = '2000-01-01T00:00:00+00:00'
            """
        )

    processed_reminder_ids = []

    async def fail_first_delivery(
        bot,
        reminder,
        scheduled_for,
        rendered_text,
        **kwargs,
    ):
        processed_reminder_ids.append(reminder.id)
        if reminder.id == first_reminder_id:
            raise RuntimeError("broken pending occurrence")
        return "sent"

    monkeypatch.setattr(
        completion_service_module,
        "deliver_completion_occurrence",
        fail_first_delivery,
    )

    asyncio.run(process_due_completion_occurrences(FakeBot()))

    assert processed_reminder_ids == [first_reminder_id, second_reminder_id]
