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


def test_create_reminder_in_db_returns_id(monkeypatch, tmp_path) -> None:
    use_test_db(monkeypatch, tmp_path)

    reminder_id = database.create_reminder_in_db(
        chat_id=100,
        reminder_text="Тестовое напоминание",
        schedule_type="once",
        start_at=datetime(2026, 6, 8, 12, 12),
    )

    assert reminder_id == 1


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
