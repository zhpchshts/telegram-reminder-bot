import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import database


def use_test_db(monkeypatch, tmp_path):
    test_db_path = tmp_path / "test_reminders.db"
    monkeypatch.setattr(database, "DB_PATH", test_db_path)
    database.init_db()

    return test_db_path


def test_init_db_creates_database_file(monkeypatch, tmp_path) -> None:
    test_db_path = use_test_db(monkeypatch, tmp_path)

    assert test_db_path.exists()

    with database.get_connection() as connection:
        reminder_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reminders)").fetchall()
        }
        completion_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(reminder_completion_occurrences)"
            ).fetchall()
        }
        completion_indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(reminder_completion_occurrences)"
            ).fetchall()
        }
        delivery_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(reminder_delivery_occurrences)"
            ).fetchall()
        }
        delivery_indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(reminder_delivery_occurrences)"
            ).fetchall()
        }
        reminder_indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(reminders)").fetchall()
        }

    assert "delivery_tracking_started_at_utc" in reminder_columns
    assert "last_handled_scheduled_for_utc" in reminder_columns
    assert "requires_completion" in reminder_columns
    assert "repeat_interval_minutes" in reminder_columns
    assert "revision" in reminder_columns
    assert "client_request_id" in reminder_columns
    assert "client_request_hash" in reminder_columns
    assert "client_request_status" in reminder_columns
    assert "idx_reminders_client_request" in reminder_indexes
    assert "idx_reminders_chat_status" in reminder_indexes
    assert {
        "delivery_claim_token",
        "delivery_claimed_at_utc",
        "reminder_revision",
        "completion_claim_token",
        "completion_next_attempt_at_utc",
        "completion_message_id",
        "completion_delivery_status",
    } <= completion_columns
    assert "idx_reminder_completion_occurrences_one_active" in completion_indexes
    assert "idx_reminder_completion_occurrences_due" in completion_indexes
    assert "idx_reminder_completion_occurrences_completion_due" in completion_indexes
    assert {
        "reminder_revision",
        "scheduled_for_utc",
        "delivery_attempts",
        "claim_token",
        "next_attempt_at_utc",
    } <= delivery_columns
    assert "idx_reminder_delivery_occurrences_due" in delivery_indexes
    assert "idx_reminder_delivery_occurrences_retention" in delivery_indexes


def test_create_reminder_is_idempotent_per_chat_and_payload(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    create_kwargs = {
        "chat_id": 100,
        "reminder_text": "Не создать дважды",
        "schedule_type": "once",
        "start_at": datetime(2099, 6, 8, 12, 12),
        "client_request_id": "request-12345678",
        "client_request_hash": "same-hash",
    }

    first_id, first_created, first_status = database.create_reminder_idempotently_in_db(
        **create_kwargs
    )
    second_id, second_created, second_status = (
        database.create_reminder_idempotently_in_db(**create_kwargs)
    )

    assert (first_id, first_created, first_status) == (1, True, "pending")
    assert (second_id, second_created, second_status) == (1, False, "pending")
    with database.get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
    assert count == 1


def test_idempotency_key_rejects_different_payload_in_same_chat(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    common_kwargs = {
        "chat_id": 100,
        "reminder_text": "Первый запрос",
        "schedule_type": "once",
        "start_at": datetime(2099, 6, 8, 12, 12),
        "client_request_id": "request-12345678",
    }
    database.create_reminder_idempotently_in_db(
        **common_kwargs,
        client_request_hash="first-hash",
    )

    with pytest.raises(database.ReminderIdempotencyConflictError):
        database.create_reminder_idempotently_in_db(
            **common_kwargs,
            client_request_hash="different-hash",
        )


def test_active_reminder_limit_is_atomic_and_scoped_to_chat(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database, "MAX_ACTIVE_REMINDERS_PER_CHAT", 2)

    first_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Первое",
        schedule_type="once",
        start_at=datetime(2099, 6, 8, 12, 12),
    )
    database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Второе",
        schedule_type="once",
        start_at=datetime(2099, 6, 8, 12, 13),
    )

    with pytest.raises(database.ActiveReminderLimitError):
        database.create_reminder_in_db(
            chat_id=100,
            reminder_text="Лишнее",
            schedule_type="once",
            start_at=datetime(2099, 6, 8, 12, 14),
        )

    other_chat_id = database.create_reminder_in_db(
        chat_id=200,
        reminder_text="Другой чат",
        schedule_type="once",
        start_at=datetime(2099, 6, 8, 12, 14),
    )
    assert other_chat_id == 3

    assert database.delete_active_reminder_for_chat_in_db(first_id, 100) is True
    replacement_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="После удаления",
        schedule_type="once",
        start_at=datetime(2099, 6, 8, 12, 15),
    )
    assert replacement_id == 4


def test_delivery_occurrence_retention_deletes_only_old_terminal_rows(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Проверить retention",
        schedule_type="every_days",
        start_at=datetime(2099, 6, 8, 12, 12),
        interval_days=1,
    )
    now = datetime(2099, 7, 1, tzinfo=timezone.utc)
    old = (now - timedelta(days=8)).isoformat(timespec="seconds")
    fresh = (now - timedelta(days=1)).isoformat(timespec="seconds")
    rows = [
        ("2099-06-01T00:00:00+00:00", "sent", old),
        ("2099-06-02T00:00:00+00:00", "cancelled", old),
        ("2099-06-03T00:00:00+00:00", "failed", fresh),
        ("2099-06-04T00:00:00+00:00", "pending", old),
    ]
    with database.get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO reminder_delivery_occurrences (
                reminder_id, reminder_revision, chat_id, scheduled_for_utc,
                status, created_at_utc, updated_at_utc
            ) VALUES (?, 1, 100, ?, ?, ?, ?)
            """,
            [
                (reminder_id, scheduled_for, status, updated_at, updated_at)
                for scheduled_for, status, updated_at in rows
            ],
        )

    deleted_count = database.delete_terminal_reminder_delivery_occurrences(
        expired_before=now - timedelta(days=7),
        limit=100,
    )

    assert deleted_count == 2
    with database.get_connection() as connection:
        remaining = connection.execute(
            """
            SELECT status, updated_at_utc
            FROM reminder_delivery_occurrences
            ORDER BY scheduled_for_utc
            """
        ).fetchall()
    assert [(row["status"], row["updated_at_utc"]) for row in remaining] == [
        ("failed", fresh),
        ("pending", old),
    ]


def test_weather_location_cache_ttl_refreshes_and_cleans_derived_rows(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    with database.get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO weather_location_cache (
                location_key, name, latitude, longitude, updated_at
            ) VALUES (?, ?, 56.8, 60.6, ?)
            """,
            [
                ("old", "Старый", "2000-01-01T00:00:00+00:00"),
                ("fresh", "Свежий", "2099-01-01T00:00:00+00:00"),
            ],
        )

    assert database.get_cached_weather_location("old") is None
    assert database.get_cached_weather_location("fresh")["name"] == "Свежий"

    deleted_count = database.delete_expired_weather_location_cache(
        expired_before=datetime(2050, 1, 1, tzinfo=timezone.utc),
        limit=100,
    )

    assert deleted_count == 1
    with database.get_connection() as connection:
        remaining_keys = [
            row["location_key"]
            for row in connection.execute(
                "SELECT location_key FROM weather_location_cache"
            ).fetchall()
        ]
    assert remaining_keys == ["fresh"]


def test_init_db_invalidates_only_legacy_naive_weather_cache(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Сохранить пользовательские данные",
        schedule_type="once",
        start_at=datetime(2099, 6, 8, 12, 12),
    )
    with database.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO weather_location_cache (
                location_key, name, latitude, longitude, updated_at
            ) VALUES ('legacy', 'Старый кэш', 56.8, 60.6,
                      '2026-08-26T12:00:00')
            """
        )

    database.init_db()

    assert database.get_active_reminder_from_db(reminder_id) is not None
    with database.get_connection() as connection:
        cache_count = connection.execute(
            "SELECT COUNT(*) FROM weather_location_cache"
        ).fetchone()[0]
    assert cache_count == 0


def test_init_db_adds_completion_publication_fields_without_losing_occurrence(
    monkeypatch, tmp_path
) -> None:
    test_db_path = tmp_path / "legacy-completion.db"
    with sqlite3.connect(test_db_path) as connection:
        connection.execute(
            """
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                start_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO reminders (
                id, chat_id, text, schedule_type, status, start_at, created_at
            ) VALUES (1, 100, 'Сохранить occurrence', 'once', 'active',
                      '2026-07-18T12:00:00', '2026-07-18T10:00:00')
            """
        )
        connection.execute(
            """
            CREATE TABLE reminder_completion_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reminder_id INTEGER NOT NULL,
                reminder_revision INTEGER NOT NULL DEFAULT 1,
                chat_id INTEGER NOT NULL,
                scheduled_for_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                rendered_text TEXT NOT NULL,
                current_message_id INTEGER,
                current_message_sent_at_utc TEXT,
                next_repeat_at_utc TEXT,
                repeat_attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                delivery_claim_token TEXT,
                delivery_claimed_at_utc TEXT,
                completed_at_utc TEXT,
                completed_by_user_id INTEGER,
                completed_by_display_name TEXT,
                superseded_at_utc TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                UNIQUE(reminder_id, reminder_revision, scheduled_for_utc)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO reminder_completion_occurrences (
                reminder_id, reminder_revision, chat_id, scheduled_for_utc,
                status, rendered_text, created_at_utc, updated_at_utc
            ) VALUES (1, 1, 100, '2026-07-18T08:00:00+00:00',
                      'pending', 'Сохранить occurrence',
                      '2026-07-18T08:00:00+00:00',
                      '2026-07-18T08:00:00+00:00')
            """
        )

    monkeypatch.setattr(database, "DB_PATH", test_db_path)
    database.init_db()
    database.init_db()

    with database.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT * FROM reminder_completion_occurrences WHERE id = 1"
        ).fetchone()
    assert occurrence["rendered_text"] == "Сохранить occurrence"
    assert occurrence["status"] == "pending"
    assert occurrence["completion_attempts"] == 0
    assert occurrence["completion_message_id"] is None


def test_init_db_migrates_existing_reminders_without_losing_data(
    monkeypatch, tmp_path
) -> None:
    test_db_path = tmp_path / "legacy-reminders.db"
    with sqlite3.connect(test_db_path) as connection:
        connection.execute(
            """
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                start_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO reminders (
                chat_id, text, schedule_type, status, start_at, created_at
            ) VALUES (100, 'Сохранить меня', 'once', 'active',
                      '2026-07-18T12:00:00', '2026-07-18T10:00:00')
            """
        )

    monkeypatch.setattr(database, "DB_PATH", test_db_path)
    database.init_db()

    with database.get_connection() as connection:
        reminder = connection.execute(
            """
            SELECT text, requires_completion, repeat_interval_minutes, revision
            FROM reminders WHERE id = 1
            """
        ).fetchone()
    assert tuple(reminder) == ("Сохранить меня", 0, None, 1)


def test_create_reminder_in_db_returns_id(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    assert reminder_id == 1

    reminder = database.get_active_reminder_from_db(reminder_id)
    assert reminder is not None
    tracking_started_at = datetime.fromisoformat(
        reminder["delivery_tracking_started_at_utc"]
    )
    assert tracking_started_at.tzinfo == timezone.utc
    assert reminder["last_handled_scheduled_for_utc"] is None
    assert reminder["revision"] == 1


def test_database_normalizes_disabled_completion_interval(
    monkeypatch, tmp_path
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
        requires_completion=False,
        repeat_interval_minutes=60,
    )

    reminder = database.get_active_reminder_from_db(reminder_id)
    assert reminder["repeat_interval_minutes"] is None

    assert database.update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Обновлённое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 9, 12, 12),
        requires_completion=False,
        repeat_interval_minutes=120,
    )
    reminder = database.get_active_reminder_from_db(reminder_id)
    assert reminder["repeat_interval_minutes"] is None


def test_update_reminder_resets_delivery_tracking_state(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="До изменения",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 1, 10, 0),
        interval_days=1,
    )

    with database.get_connection() as connection:
        connection.execute(
            """
            UPDATE reminders
            SET
                delivery_tracking_started_at_utc = ?,
                last_handled_scheduled_for_utc = ?
            WHERE id = ?
            """,
            (
                "2020-01-01T00:00:00+00:00",
                "2026-07-02T05:00:00+00:00",
                reminder_id,
            ),
        )

    assert database.update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="После изменения",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 3, 10, 0),
        interval_days=1,
    )

    reminder = database.get_active_reminder_from_db(reminder_id)
    assert reminder is not None
    assert datetime.fromisoformat(
        reminder["delivery_tracking_started_at_utc"]
    ) > datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert reminder["last_handled_scheduled_for_utc"] is None
    assert reminder["revision"] == 2


def test_mark_reminder_occurrence_handled_is_monotonic_and_atomic(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    repeating_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Регулярное",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 1, 10, 0),
        interval_days=1,
    )
    once_sent_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Одноразовое",
        schedule_type="once",
        start_at=datetime(2026, 7, 1, 11, 0),
    )
    once_missed_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Старая погода",
        schedule_type="once",
        start_at=datetime(2026, 7, 1, 12, 0),
    )
    newer = datetime(2026, 7, 3, 5, 0, tzinfo=timezone.utc)
    older = datetime(2026, 7, 2, 5, 0, tzinfo=timezone.utc)

    assert database.mark_reminder_occurrence_handled(repeating_id, newer)
    assert not database.mark_reminder_occurrence_handled(repeating_id, older)
    assert database.mark_reminder_occurrence_handled(
        once_sent_id,
        newer,
        final_status="sent",
    )
    assert database.mark_reminder_occurrence_handled(
        once_missed_id,
        newer,
        final_status="missed",
    )

    with database.get_connection() as connection:
        rows = {
            row["id"]: row
            for row in connection.execute(
                "SELECT * FROM reminders ORDER BY id"
            ).fetchall()
        }

    assert rows[repeating_id]["last_handled_scheduled_for_utc"] == (
        "2026-07-03T05:00:00+00:00"
    )
    assert rows[repeating_id]["status"] == "active"
    assert rows[once_sent_id]["status"] == "sent"
    assert rows[once_sent_id]["last_handled_scheduled_for_utc"] == (
        "2026-07-03T05:00:00+00:00"
    )
    assert rows[once_missed_id]["status"] == "missed"

    assert (
        database.get_reminder_occurrence_handling_state(repeating_id, older)
        == "already_handled"
    )
    assert (
        database.get_reminder_occurrence_handling_state(
            repeating_id,
            newer + timedelta(days=1),
        )
        == "unhandled"
    )
    assert database.get_reminder_occurrence_handling_state(999_999, newer) == "missing"
    assert (
        database.get_reminder_occurrence_handling_state(
            once_sent_id,
            newer + timedelta(days=1),
        )
        == "inactive"
    )


def test_occurrence_watermark_requires_expected_revision(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Новая ревизия",
        schedule_type="once",
        start_at=datetime(2026, 7, 1, 10, 0),
    )
    assert database.update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Изменённая ревизия",
        schedule_type="once",
        start_at=datetime(2026, 7, 2, 10, 0),
        expected_revision=1,
    )
    scheduled_for = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

    assert not database.mark_reminder_occurrence_handled(
        reminder_id,
        scheduled_for,
        final_status="sent",
        expected_revision=1,
    )
    reminder = database.get_active_reminder_from_db(reminder_id)
    assert reminder is not None
    assert reminder["revision"] == 2
    assert reminder["status"] == "active"
    assert reminder["last_handled_scheduled_for_utc"] is None


def test_delivery_claim_serializes_processes_and_allows_stale_recovery(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Один occurrence",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 1, 10, 0),
        interval_days=1,
    )
    scheduled_for = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 7, 2, 10, 1, tzinfo=timezone.utc)

    first = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="process-one",
        now=now,
        stale_before=now - timedelta(minutes=2),
        max_attempts=10,
    )
    second = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="process-two",
        now=now + timedelta(seconds=1),
        stale_before=now - timedelta(minutes=2),
        max_attempts=10,
    )

    assert first["outcome"] == "claimed"
    assert second["outcome"] == "delivery_in_progress"

    database.init_db()
    recovered = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="process-two",
        now=now + timedelta(minutes=3),
        stale_before=now + timedelta(minutes=1),
        max_attempts=10,
    )

    # If process one crashed after Telegram accepted the message, recovery may
    # send it again: the delivery contract is intentionally at-least-once.
    assert recovered["outcome"] == "claimed"
    assert recovered["delivery_attempts"] == 2
    assert recovered["is_recovery"] is True


def test_delivery_claim_heartbeat_prevents_stale_recovery(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Продлить claim",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 1, 10, 0),
        interval_days=1,
    )
    scheduled_for = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 7, 2, 10, 1, tzinfo=timezone.utc)
    claimed = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="process-one",
        now=now,
        stale_before=now - timedelta(minutes=2),
        max_attempts=10,
    )

    assert database.refresh_reminder_delivery_claim(
        occurrence_id=claimed["occurrence_id"],
        claim_token="process-one",
        now=now + timedelta(seconds=100),
    )
    second_now = now + timedelta(seconds=181)
    second = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="process-two",
        now=second_now,
        stale_before=second_now - timedelta(minutes=2),
        max_attempts=10,
    )

    assert second["outcome"] == "delivery_in_progress"


def test_delivery_retry_is_persistent_due_and_bounded(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Повторить доставку",
        schedule_type="once",
        start_at=datetime(2026, 7, 2, 10, 0),
    )
    scheduled_for = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 7, 2, 10, 1, tzinfo=timezone.utc)
    first = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="attempt-one",
        now=now,
        stale_before=now - timedelta(minutes=2),
        max_attempts=2,
    )
    retry_at = now + timedelta(minutes=5)
    assert database.reschedule_reminder_delivery_occurrence(
        occurrence_id=first["occurrence_id"],
        claim_token="attempt-one",
        next_attempt_at=retry_at,
        last_error="TelegramNetworkError",
    )

    early = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="too-early",
        now=retry_at - timedelta(seconds=1),
        stale_before=now,
        max_attempts=2,
        occurrence_id=first["occurrence_id"],
    )
    due = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="attempt-two",
        now=retry_at,
        stale_before=now,
        max_attempts=2,
        occurrence_id=first["occurrence_id"],
    )
    assert early["outcome"] == "retry_scheduled"
    assert due["outcome"] == "claimed"
    assert due["delivery_attempts"] == 2
    concurrent_final_attempt = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="parallel-final-attempt",
        now=retry_at + timedelta(seconds=1),
        stale_before=retry_at - timedelta(minutes=1),
        max_attempts=2,
        occurrence_id=first["occurrence_id"],
    )
    assert concurrent_final_attempt["outcome"] == "delivery_in_progress"
    assert database.reschedule_reminder_delivery_occurrence(
        occurrence_id=first["occurrence_id"],
        claim_token="attempt-two",
        next_attempt_at=retry_at + timedelta(minutes=5),
        last_error="TelegramNetworkError",
    )

    exhausted = database.claim_reminder_delivery_occurrence(
        reminder_id=reminder_id,
        expected_revision=1,
        scheduled_for_utc=scheduled_for,
        claim_token="attempt-three",
        now=retry_at + timedelta(minutes=5),
        stale_before=retry_at,
        max_attempts=2,
        occurrence_id=first["occurrence_id"],
    )
    assert exhausted["outcome"] == "attempts_exhausted"
    with database.get_connection() as connection:
        occurrence = connection.execute(
            "SELECT status FROM reminder_delivery_occurrences WHERE id = ?",
            (first["occurrence_id"],),
        ).fetchone()
        reminder = connection.execute(
            "SELECT status FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()
    assert occurrence["status"] == "failed"
    assert reminder["status"] == "missed"


def test_update_and_delete_cancel_pending_delivery_claims(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_ids = [
        database.create_reminder_in_db(
            chat_id=100,
            reminder_text=f"Напоминание {index}",
            schedule_type="every_days",
            start_at=datetime(2026, 7, 1, 10, 0),
            interval_days=1,
        )
        for index in (1, 2)
    ]
    now = datetime(2026, 7, 2, 10, 1, tzinfo=timezone.utc)
    for reminder_id in reminder_ids:
        database.claim_reminder_delivery_occurrence(
            reminder_id=reminder_id,
            expected_revision=1,
            scheduled_for_utc=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
            claim_token=f"claim-{reminder_id}",
            now=now,
            stale_before=now - timedelta(minutes=2),
            max_attempts=10,
        )

    assert database.update_reminder_in_db(
        reminder_id=reminder_ids[0],
        chat_id=100,
        reminder_text="Обновлено",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 3, 10, 0),
        interval_days=1,
        expected_revision=1,
    )
    assert not database.delete_active_reminder_for_chat_in_db(
        reminder_ids[1],
        100,
        expected_revision=2,
    )
    with database.get_connection() as connection:
        still_pending = connection.execute(
            """
            SELECT status FROM reminder_delivery_occurrences
            WHERE reminder_id = ?
            """,
            (reminder_ids[1],),
        ).fetchone()
    assert still_pending["status"] == "pending"
    assert database.delete_active_reminder_for_chat_in_db(
        reminder_ids[1],
        100,
        expected_revision=1,
    )

    with database.get_connection() as connection:
        statuses = connection.execute(
            """
            SELECT reminder_id, status FROM reminder_delivery_occurrences
            ORDER BY reminder_id
            """
        ).fetchall()
    assert [(row["reminder_id"], row["status"]) for row in statuses] == [
        (reminder_ids[0], "cancelled"),
        (reminder_ids[1], "cancelled"),
    ]


def test_reminder_auto_delete_setting_is_stored_and_updated(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="every_days",
        start_at=datetime(2026, 6, 8, 12, 12),
        interval_days=1,
        delete_after_two_days=True,
    )

    reminder = database.get_active_reminder_from_db(reminder_id)
    assert reminder is not None
    assert reminder["delete_after_two_days"] == 1

    assert database.update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Обновлённое напоминание",
        schedule_type="every_days",
        start_at=datetime(2026, 6, 9, 12, 12),
        interval_days=1,
        delete_after_two_days=False,
    )

    updated_reminder = database.get_active_reminder_from_db(reminder_id)
    assert updated_reminder is not None
    assert updated_reminder["delete_after_two_days"] == 0


def test_get_active_reminder_from_db(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    reminder = database.get_active_reminder_from_db(reminder_id)

    assert reminder is not None
    assert reminder["id"] == reminder_id
    assert reminder["chat_id"] == 100
    assert reminder["text"] == "Тестовое напоминание"
    assert reminder["schedule_type"] == "once"
    assert reminder["status"] == "active"
    assert reminder["start_at"] == "2026-06-08T12:12:00"


def test_get_active_reminders_for_chat_returns_only_chat_reminders(
    monkeypatch, tmp_path
) -> None:
    use_test_db(monkeypatch, tmp_path)

    database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Напоминание первого чата",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )
    database.create_reminder_in_db(
        chat_id=200,
        reminder_text="Напоминание второго чата",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    reminders = database.get_active_reminders_for_chat(100)

    assert len(reminders) == 1
    assert reminders[0]["chat_id"] == 100
    assert reminders[0]["text"] == "Напоминание первого чата"


def test_get_all_active_reminders_returns_all_active(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Первое",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )
    database.create_reminder_in_db(
        chat_id=200,
        reminder_text="Второе",
        schedule_type="every_days",
        start_at=datetime(2026, 6, 8, 12, 12),
        interval_days=3,
    )

    reminders = database.get_all_active_reminders()

    assert len(reminders) == 2
    assert reminders[0]["text"] == "Первое"
    assert reminders[1]["text"] == "Второе"


def test_count_active_chats_counts_unique_chats_with_active_reminders(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)

    database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Первое активное в первом чате",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )
    database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Второе активное в первом чате",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )
    database.create_reminder_in_db(
        chat_id=200,
        reminder_text="Активное во втором чате",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    deleted_reminder_id = database.create_reminder_in_db(
        chat_id=300,
        reminder_text="Удалённое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )
    sent_reminder_id = database.create_reminder_in_db(
        chat_id=400,
        reminder_text="Отправленное напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    database.mark_reminder_as_deleted(deleted_reminder_id)
    database.set_reminder_status(sent_reminder_id, "sent")

    assert database.count_active_chats() == 2


def test_sent_status_hides_reminder_from_active(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    database.set_reminder_status(reminder_id, "sent")

    assert database.get_active_reminder_from_db(reminder_id) is None
    assert database.get_all_active_reminders() == []


def test_mark_reminder_as_deleted_hides_it_from_active(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="every_days",
        start_at=datetime(2026, 6, 8, 12, 12),
        interval_days=1,
    )

    database.mark_reminder_as_deleted(reminder_id)

    assert database.get_active_reminder_from_db(reminder_id) is None
    assert database.get_all_active_reminders() == []


def test_mark_reminder_as_missed_hides_it_from_active(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    database.mark_reminder_as_missed(reminder_id)

    assert database.get_active_reminder_from_db(reminder_id) is None
    assert database.get_all_active_reminders() == []


def test_create_every_days_reminder_stores_interval_days(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Каждые три дня",
        schedule_type="every_days",
        start_at=datetime(2026, 6, 8, 12, 12),
        interval_days=3,
    )

    reminder = database.get_active_reminder_from_db(reminder_id)

    assert reminder is not None
    assert reminder["schedule_type"] == "every_days"
    assert reminder["interval_days"] == 3


def test_create_every_week_reminder_stores_interval_weeks_and_day(
    monkeypatch, tmp_path
) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Каждые две недели",
        schedule_type="every_week",
        start_at=datetime(2026, 6, 8, 12, 12),
        interval_weeks=2,
        day_of_week="MON",
    )

    reminder = database.get_active_reminder_from_db(reminder_id)

    assert reminder is not None
    assert reminder["schedule_type"] == "every_week"
    assert reminder["interval_weeks"] == 2
    assert reminder["day_of_week"] == "MON"


def test_create_monthly_weekday_reminder_stores_month_week_number_and_day(
    monkeypatch, tmp_path
) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Первый понедельник месяца",
        schedule_type="monthly_weekday",
        start_at=datetime(2026, 6, 8, 12, 12),
        month_week_number=1,
        day_of_week="MON",
    )

    reminder = database.get_active_reminder_from_db(reminder_id)

    assert reminder is not None
    assert reminder["schedule_type"] == "monthly_weekday"
    assert reminder["month_week_number"] == 1
    assert reminder["day_of_week"] == "MON"


def test_get_chat_timezone_returns_none_when_not_set(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    assert database.get_chat_timezone(100) is None


def test_set_chat_timezone_creates_setting(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    database.set_chat_timezone(100, "Asia/Yekaterinburg")

    assert database.get_chat_timezone(100) == "Asia/Yekaterinburg"


def test_set_chat_timezone_updates_existing_setting(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    database.set_chat_timezone(100, "Asia/Yekaterinburg")
    database.set_chat_timezone(100, "Europe/Moscow")

    assert database.get_chat_timezone(100) == "Europe/Moscow"


def test_chat_timezones_are_isolated(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    database.set_chat_timezone(100, "Asia/Yekaterinburg")
    database.set_chat_timezone(200, "Europe/Moscow")

    assert database.get_chat_timezone(100) == "Asia/Yekaterinburg"
    assert database.get_chat_timezone(200) == "Europe/Moscow"


def test_get_active_reminder_for_chat_returns_only_matching_chat(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Напоминание первого чата",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    assert database.get_active_reminder_for_chat(reminder_id, 100) is not None
    assert database.get_active_reminder_for_chat(reminder_id, 200) is None


def test_create_monthly_day_reminder_stores_month_day(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Одиннадцатое число месяца",
        schedule_type="monthly_day",
        start_at=datetime(2026, 6, 11, 12, 12),
        month_day=11,
    )

    reminder = database.get_active_reminder_from_db(reminder_id)

    assert reminder is not None
    assert reminder["schedule_type"] == "monthly_day"
    assert reminder["month_day"] == 11


def test_prepared_weather_report_can_be_saved_read_and_deleted(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Екатеринбург; Хургада",
        reminder_kind="weather",
        schedule_type="once",
        start_at=datetime(2026, 7, 7, 9, 30),
    )

    scheduled_for = datetime(
        2026,
        7,
        7,
        4,
        30,
        tzinfo=timezone.utc,
    )

    assert database.save_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        scheduled_for=scheduled_for,
        reminder_text="Екатеринбург; Хургада",
        report_html="<b>Подготовленный прогноз</b>",
    )

    prepared_report = database.get_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        reminder_text="Екатеринбург; Хургада",
        earliest_scheduled_for=scheduled_for - timedelta(seconds=1),
        latest_scheduled_for=scheduled_for + timedelta(seconds=1),
    )

    assert prepared_report == {
        "scheduled_for_utc": "2026-07-07T04:30:00+00:00",
        "report_html": "<b>Подготовленный прогноз</b>",
    }

    database.delete_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        scheduled_for_utc="2026-07-07T04:30:00+00:00",
    )

    assert (
        database.get_prepared_weather_report(
            reminder_id=reminder_id,
            reminder_revision=1,
            reminder_text="Екатеринбург; Хургада",
            earliest_scheduled_for=scheduled_for - timedelta(seconds=1),
            latest_scheduled_for=scheduled_for + timedelta(seconds=1),
        )
        is None
    )


def test_prepared_weather_report_requires_matching_reminder_text(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Екатеринбург",
        reminder_kind="weather",
        schedule_type="once",
        start_at=datetime(2026, 7, 7, 9, 30),
    )

    scheduled_for = datetime(
        2026,
        7,
        7,
        4,
        30,
        tzinfo=timezone.utc,
    )

    assert database.save_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        scheduled_for=scheduled_for,
        reminder_text="Екатеринбург",
        report_html="<b>Старый прогноз</b>",
    )

    prepared_report = database.get_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        reminder_text="Екатеринбург; Хургада",
        earliest_scheduled_for=scheduled_for - timedelta(seconds=1),
        latest_scheduled_for=scheduled_for + timedelta(seconds=1),
    )

    assert prepared_report is None


def test_prepared_weather_report_rejects_stale_revision_and_is_invalidated(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Екатеринбург",
        reminder_kind="weather",
        schedule_type="once",
        start_at=datetime(2026, 7, 7, 20, 59),
    )
    scheduled_for = datetime(2026, 7, 7, 15, 59, tzinfo=timezone.utc)

    assert database.save_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        scheduled_for=scheduled_for,
        reminder_text="Екатеринбург",
        report_html="<b>Старая ревизия</b>",
    )
    assert database.update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Екатеринбург",
        reminder_kind="weather",
        schedule_type="once",
        start_at=datetime(2026, 7, 7, 21, 0),
        expected_revision=1,
    )

    # This models a revision-1 prefetch finishing after the update committed.
    assert not database.save_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        scheduled_for=scheduled_for,
        reminder_text="Екатеринбург",
        report_html="<b>Поздно завершившаяся старая ревизия</b>",
    )
    assert (
        database.get_prepared_weather_report(
            reminder_id=reminder_id,
            reminder_revision=2,
            reminder_text="Екатеринбург",
            earliest_scheduled_for=scheduled_for - timedelta(minutes=1),
            latest_scheduled_for=scheduled_for + timedelta(minutes=1),
        )
        is None
    )

    assert database.save_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=2,
        scheduled_for=scheduled_for,
        reminder_text="Екатеринбург",
        report_html="<b>Новая ревизия</b>",
    )
    database.delete_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=1,
        scheduled_for_utc="2026-07-07T15:59:00+00:00",
    )
    assert database.get_prepared_weather_report(
        reminder_id=reminder_id,
        reminder_revision=2,
        reminder_text="Екатеринбург",
        earliest_scheduled_for=scheduled_for - timedelta(seconds=1),
        latest_scheduled_for=scheduled_for + timedelta(seconds=1),
    ) == {
        "scheduled_for_utc": "2026-07-07T15:59:00+00:00",
        "report_html": "<b>Новая ревизия</b>",
    }
    assert database.delete_active_reminder_for_chat_in_db(
        reminder_id,
        100,
        expected_revision=2,
    )
    with database.get_connection() as connection:
        cache_count = connection.execute(
            "SELECT COUNT(*) FROM weather_report_cache WHERE reminder_id = ?",
            (reminder_id,),
        ).fetchone()[0]
    assert cache_count == 0


def test_delete_expired_prepared_weather_reports_removes_only_old_entries(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_ids = [
        database.create_reminder_in_db(
            chat_id=100 + index,
            reminder_text=reminder_text,
            reminder_kind="weather",
            schedule_type="once",
            start_at=datetime(2026, 7, 7, 9, 30),
        )
        for index, reminder_text in enumerate(("Екатеринбург", "Хургада"))
    ]

    expired_scheduled_for = datetime(
        2026,
        7,
        7,
        4,
        20,
        tzinfo=timezone.utc,
    )
    active_scheduled_for = datetime(
        2026,
        7,
        7,
        4,
        30,
        tzinfo=timezone.utc,
    )

    assert database.save_prepared_weather_report(
        reminder_id=reminder_ids[0],
        reminder_revision=1,
        scheduled_for=expired_scheduled_for,
        reminder_text="Екатеринбург",
        report_html="<b>Старый прогноз</b>",
    )
    assert database.save_prepared_weather_report(
        reminder_id=reminder_ids[1],
        reminder_revision=1,
        scheduled_for=active_scheduled_for,
        reminder_text="Хургада",
        report_html="<b>Актуальный прогноз</b>",
    )

    database.delete_expired_prepared_weather_reports(
        datetime(
            2026,
            7,
            7,
            4,
            25,
            tzinfo=timezone.utc,
        )
    )

    assert (
        database.get_prepared_weather_report(
            reminder_id=reminder_ids[0],
            reminder_revision=1,
            reminder_text="Екатеринбург",
            earliest_scheduled_for=expired_scheduled_for - timedelta(seconds=1),
            latest_scheduled_for=expired_scheduled_for + timedelta(seconds=1),
        )
        is None
    )
    assert database.get_prepared_weather_report(
        reminder_id=reminder_ids[1],
        reminder_revision=1,
        reminder_text="Хургада",
        earliest_scheduled_for=active_scheduled_for - timedelta(seconds=1),
        latest_scheduled_for=active_scheduled_for + timedelta(seconds=1),
    ) == {
        "scheduled_for_utc": "2026-07-07T04:30:00+00:00",
        "report_html": "<b>Актуальный прогноз</b>",
    }


def test_init_db_migrates_existing_weather_report_cache(
    monkeypatch,
    tmp_path,
) -> None:
    test_db_path = tmp_path / "test_reminders.db"
    monkeypatch.setattr(database, "DB_PATH", test_db_path)

    with sqlite3.connect(test_db_path) as connection:
        connection.execute(
            """
            CREATE TABLE weather_report_cache (
                reminder_id INTEGER NOT NULL,
                scheduled_for_utc TEXT NOT NULL,
                report_html TEXT NOT NULL,
                prepared_at_utc TEXT NOT NULL,
                PRIMARY KEY (reminder_id, scheduled_for_utc)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO weather_report_cache (
                reminder_id,
                scheduled_for_utc,
                report_html,
                prepared_at_utc
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                12,
                "2026-07-07T04:30:00+00:00",
                "<b>Старый прогноз</b>",
                "2026-07-07T04:25:00+00:00",
            ),
        )

    database.init_db()
    database.init_db()

    with database.get_connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(weather_report_cache)"
            ).fetchall()
        }
        rows = connection.execute("SELECT * FROM weather_report_cache").fetchall()

    assert "reminder_text" in columns
    assert "reminder_revision" in columns
    assert rows == []


def test_reminder_message_deletion_queue_is_persistent_and_independent(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Ежедневное напоминание",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 7, 9, 0),
        interval_days=1,
        delete_after_two_days=True,
    )
    sent_at = datetime(2026, 7, 7, 4, 0, tzinfo=timezone.utc)
    delete_at = sent_at + timedelta(hours=47, minutes=45)

    assert database.enqueue_reminder_message_deletion(
        reminder_id=reminder_id,
        chat_id=100,
        message_id=501,
        sent_at=sent_at,
        delete_at=delete_at,
    )
    assert not database.enqueue_reminder_message_deletion(
        reminder_id=reminder_id,
        chat_id=100,
        message_id=501,
        sent_at=sent_at,
        delete_at=delete_at,
    )

    assert database.update_reminder_in_db(
        reminder_id=reminder_id,
        chat_id=100,
        reminder_text="Ежедневное напоминание",
        schedule_type="every_days",
        start_at=datetime(2026, 7, 7, 9, 0),
        interval_days=1,
        delete_after_two_days=False,
    )

    database.mark_reminder_as_deleted(reminder_id)

    with database.get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM reminder_message_deletion_queue"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["reminder_id"] == reminder_id
    assert rows[0]["message_id"] == 501
    assert rows[0]["delete_at_utc"] == "2026-07-09T03:45:00+00:00"
    assert rows[0]["next_attempt_at_utc"] == "2026-07-09T03:45:00+00:00"


def test_due_reminder_message_deletions_can_be_rescheduled_and_deleted(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)
    sent_at = datetime(2026, 7, 7, 4, 0, tzinfo=timezone.utc)
    delete_at = sent_at + timedelta(hours=47, minutes=45)
    database.enqueue_reminder_message_deletion(
        reminder_id=12,
        chat_id=100,
        message_id=501,
        sent_at=sent_at,
        delete_at=delete_at,
    )

    due_rows = database.get_due_reminder_message_deletions(
        delete_at,
        limit=10,
    )
    assert len(due_rows) == 1

    next_attempt_at = delete_at + timedelta(minutes=1)
    database.reschedule_reminder_message_deletion(
        queue_id=due_rows[0]["id"],
        delete_attempts=1,
        next_attempt_at=next_attempt_at,
        last_error="temporary error",
    )

    assert database.get_due_reminder_message_deletions(delete_at, limit=10) == []
    retried_rows = database.get_due_reminder_message_deletions(
        next_attempt_at,
        limit=10,
    )
    assert len(retried_rows) == 1
    assert retried_rows[0]["delete_attempts"] == 1
    assert retried_rows[0]["last_error"] == "temporary error"

    database.delete_reminder_message_deletion(retried_rows[0]["id"])
    assert (
        database.get_due_reminder_message_deletions(
            next_attempt_at,
            limit=10,
        )
        == []
    )


def test_init_db_migrates_existing_reminders_and_creates_deletion_queue(
    monkeypatch,
    tmp_path,
) -> None:
    test_db_path = tmp_path / "test_reminders.db"
    monkeypatch.setattr(database, "DB_PATH", test_db_path)

    with sqlite3.connect(test_db_path) as connection:
        connection.execute(
            """
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                start_at TEXT NOT NULL,
                interval_days INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO reminders (
                chat_id,
                text,
                schedule_type,
                status,
                start_at,
                interval_days,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                100,
                "Существующее напоминание",
                "every_days",
                "active",
                "2026-07-07T09:00:00",
                1,
                "2026-07-01T12:00:00",
            ),
        )

    database.init_db()
    database.init_db()

    with database.get_connection() as connection:
        reminder = connection.execute("SELECT * FROM reminders WHERE id = 1").fetchone()
        queue_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(reminder_message_deletion_queue)"
            ).fetchall()
        }
        queue_indexes = {
            row["name"]
            for row in connection.execute(
                "PRAGMA index_list(reminder_message_deletion_queue)"
            ).fetchall()
        }

    assert reminder is not None
    assert reminder["text"] == "Существующее напоминание"
    assert reminder["delete_after_two_days"] == 0
    assert reminder["delivery_tracking_started_at_utc"] is not None
    assert (
        datetime.fromisoformat(reminder["delivery_tracking_started_at_utc"]).tzinfo
        == timezone.utc
    )
    assert reminder["last_handled_scheduled_for_utc"] is None
    assert {
        "id",
        "reminder_id",
        "chat_id",
        "message_id",
        "sent_at_utc",
        "delete_at_utc",
        "delete_attempts",
        "next_attempt_at_utc",
        "last_error",
    } <= queue_columns
    assert "idx_reminder_message_deletion_queue_next_attempt" in queue_indexes
    assert "idx_reminder_message_deletion_queue_delete_at" in queue_indexes
