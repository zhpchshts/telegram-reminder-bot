import sqlite3
from datetime import datetime, timedelta, timezone

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

    assert "delivery_tracking_started_at_utc" in reminder_columns
    assert "last_handled_scheduled_for_utc" in reminder_columns


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
    database.mark_reminder_as_sent(sent_reminder_id)

    assert database.count_active_chats() == 2


def test_mark_reminder_as_sent_hides_it_from_active(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    database.mark_reminder_as_sent(reminder_id)

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

    scheduled_for = datetime(
        2026,
        7,
        7,
        4,
        30,
        tzinfo=timezone.utc,
    )

    database.save_prepared_weather_report(
        reminder_id=12,
        scheduled_for=scheduled_for,
        reminder_text="Екатеринбург; Хургада",
        report_html="<b>Подготовленный прогноз</b>",
    )

    prepared_report = database.get_prepared_weather_report(
        reminder_id=12,
        reminder_text="Екатеринбург; Хургада",
        earliest_scheduled_for=scheduled_for - timedelta(seconds=1),
        latest_scheduled_for=scheduled_for + timedelta(seconds=1),
    )

    assert prepared_report == {
        "scheduled_for_utc": "2026-07-07T04:30:00+00:00",
        "report_html": "<b>Подготовленный прогноз</b>",
    }

    database.delete_prepared_weather_report(
        reminder_id=12,
        scheduled_for_utc="2026-07-07T04:30:00+00:00",
    )

    assert (
        database.get_prepared_weather_report(
            reminder_id=12,
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

    scheduled_for = datetime(
        2026,
        7,
        7,
        4,
        30,
        tzinfo=timezone.utc,
    )

    database.save_prepared_weather_report(
        reminder_id=12,
        scheduled_for=scheduled_for,
        reminder_text="Екатеринбург",
        report_html="<b>Старый прогноз</b>",
    )

    prepared_report = database.get_prepared_weather_report(
        reminder_id=12,
        reminder_text="Екатеринбург; Хургада",
        earliest_scheduled_for=scheduled_for - timedelta(seconds=1),
        latest_scheduled_for=scheduled_for + timedelta(seconds=1),
    )

    assert prepared_report is None


def test_delete_expired_prepared_weather_reports_removes_only_old_entries(
    monkeypatch,
    tmp_path,
) -> None:
    use_test_db(monkeypatch, tmp_path)

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

    database.save_prepared_weather_report(
        reminder_id=1,
        scheduled_for=expired_scheduled_for,
        reminder_text="Екатеринбург",
        report_html="<b>Старый прогноз</b>",
    )
    database.save_prepared_weather_report(
        reminder_id=2,
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
            reminder_id=1,
            reminder_text="Екатеринбург",
            earliest_scheduled_for=expired_scheduled_for - timedelta(seconds=1),
            latest_scheduled_for=expired_scheduled_for + timedelta(seconds=1),
        )
        is None
    )
    assert database.get_prepared_weather_report(
        reminder_id=2,
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

    with database.get_connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(weather_report_cache)"
            ).fetchall()
        }
        rows = connection.execute("SELECT * FROM weather_report_cache").fetchall()

    assert "reminder_text" in columns
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
