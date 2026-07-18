import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import DeleteMessage

from app import database as database_module
from app import scheduler as scheduler_module
from app.constants import REMINDER_KIND_TEXT, REMINDER_KIND_WEATHER
from app.scheduler import (
    build_reminder_message,
    format_next_run_line,
    schedule_healthcheck,
    schedule_reminder,
    send_healthcheck,
)
from app.reminder_models import ReminderReadData


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs = []

    def add_job(self, func, **kwargs) -> None:
        self.jobs.append(
            {
                "func": func,
                **kwargs,
            }
        )

    def get_job(self, job_id: str):
        return None


class FakeJob:
    def __init__(self, next_run_time: datetime | None) -> None:
        self.next_run_time = next_run_time


class FakeSchedulerWithJob:
    def __init__(self, job) -> None:
        self.job = job

    def get_job(self, job_id: str):
        return self.job


class FakeBot:
    def __init__(self) -> None:
        self.messages = []
        self.deleted_messages = []
        self.sent_at = datetime(2026, 7, 7, 4, 30, tzinfo=timezone.utc)
        self.next_message_id = 1

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
    ):
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
        )
        message = SimpleNamespace(
            message_id=self.next_message_id,
            date=self.sent_at,
        )
        self.next_message_id += 1
        return message

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        self.deleted_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
            }
        )
        return True


def build_reminder_data(
    *,
    reminder_id: int = 1,
    chat_id: int = 100,
    reminder_text: str = "Тест",
    reminder_kind: str = REMINDER_KIND_TEXT,
    schedule_type: str = "every_days",
    start_at: datetime | None = None,
    timezone_name: str = "UTC",
    tracking_started_at: datetime | None = None,
    last_handled_at: datetime | None = None,
    delete_after_two_days: bool = False,
    interval_days: int | None = 1,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
) -> ReminderReadData:
    actual_start_at = start_at or datetime(2026, 7, 1, 10, 0)
    actual_tracking_started_at = tracking_started_at or datetime(
        2026, 7, 1, 0, 0, tzinfo=timezone.utc
    )
    return ReminderReadData(
        id=reminder_id,
        chat_id=chat_id,
        reminder_text=reminder_text,
        reminder_kind=reminder_kind,
        schedule_type=schedule_type,
        start_at=actual_start_at,
        timezone_name=timezone_name,
        delivery_tracking_started_at_utc=actual_tracking_started_at,
        last_handled_scheduled_for_utc=last_handled_at,
        delete_after_two_days=delete_after_two_days,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
        month_day=month_day,
    )


def test_schedule_once_reminder_adds_date_job(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    start_at = datetime(2026, 6, 8, 12, 12)

    schedule_reminder(
        bot=FakeBot(),
        reminder_id=1,
        chat_id=100,
        reminder_text="Тест once",
        schedule_type="once",
        start_at=start_at,
    )

    assert len(fake_scheduler.jobs) == 1

    job = fake_scheduler.jobs[0]

    assert job["trigger"] == "date"
    assert job["run_date"] == start_at
    assert job["id"] == "1"
    assert job["replace_existing"] is True
    assert job["func"] == scheduler_module.run_scheduled_reminder
    assert job["args"][1:] == [1]
    assert job["max_instances"] == 1
    assert job["coalesce"] is True


def test_schedule_every_days_reminder_adds_interval_job(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    start_at = datetime(2026, 6, 8, 12, 12)

    schedule_reminder(
        bot=FakeBot(),
        reminder_id=2,
        chat_id=100,
        reminder_text="Тест every days",
        schedule_type="every_days",
        start_at=start_at,
        interval_days=3,
    )

    job = fake_scheduler.jobs[0]

    assert job["trigger"] == "interval"
    assert job["days"] == 3
    assert job["start_date"] == start_at
    assert job["id"] == "2"


def test_schedule_every_week_reminder_adds_interval_job(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    start_at = datetime(2026, 6, 8, 12, 12)

    schedule_reminder(
        bot=FakeBot(),
        reminder_id=3,
        chat_id=100,
        reminder_text="Тест every week",
        schedule_type="every_week",
        start_at=start_at,
        interval_weeks=2,
    )

    job = fake_scheduler.jobs[0]

    assert job["trigger"] == "interval"
    assert job["weeks"] == 2
    assert job["start_date"] == start_at
    assert job["id"] == "3"


def test_schedule_monthly_weekday_reminder_adds_cron_job(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    start_at = datetime(2026, 6, 1, 12, 12)

    schedule_reminder(
        bot=FakeBot(),
        reminder_id=4,
        chat_id=100,
        reminder_text="Тест monthly",
        schedule_type="monthly_weekday",
        start_at=start_at,
        month_week_number=1,
        day_of_week="MON",
    )

    job = fake_scheduler.jobs[0]

    assert job["trigger"] == "cron"
    assert job["day"] == "1-7"
    assert job["day_of_week"] == "mon"
    assert job["hour"] == 12
    assert job["minute"] == 12
    assert job["start_date"] == start_at
    assert job["id"] == "4"


def test_schedule_monthly_weekday_requires_month_week_number_and_day() -> None:
    with pytest.raises(
        ValueError, match="month_week_number and day_of_week are required"
    ):
        schedule_reminder(
            bot=FakeBot(),
            reminder_id=5,
            chat_id=100,
            reminder_text="Тест monthly invalid",
            schedule_type="monthly_weekday",
            start_at=datetime(2026, 6, 1, 12, 12),
        )


def test_schedule_unknown_type_raises_error() -> None:
    with pytest.raises(ValueError, match="Unknown schedule_type"):
        schedule_reminder(
            bot=FakeBot(),
            reminder_id=6,
            chat_id=100,
            reminder_text="Тест unknown",
            schedule_type="unknown",
            start_at=datetime(2026, 6, 1, 12, 12),
        )


@pytest.mark.parametrize(
    ("reminder", "now", "expected"),
    [
        (
            build_reminder_data(
                schedule_type="once",
                start_at=datetime(2026, 7, 10, 10, 0),
                tracking_started_at=datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc),
                interval_days=None,
            ),
            datetime(2026, 7, 10, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc),
        ),
        (
            build_reminder_data(
                schedule_type="every_days",
                start_at=datetime(2026, 7, 1, 10, 0),
                interval_days=2,
            ),
            datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc),
        ),
        (
            build_reminder_data(
                schedule_type="every_week",
                start_at=datetime(2026, 7, 6, 10, 0),
                timezone_name="Asia/Yekaterinburg",
                tracking_started_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
                interval_days=None,
                interval_weeks=1,
                day_of_week="MON",
            ),
            datetime(2026, 7, 20, 6, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc),
        ),
        (
            build_reminder_data(
                schedule_type="monthly_day",
                start_at=datetime(2026, 1, 31, 10, 0),
                tracking_started_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                interval_days=None,
                month_day=31,
            ),
            datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        ),
        (
            build_reminder_data(
                schedule_type="monthly_weekday",
                start_at=datetime(2026, 6, 1, 10, 0),
                interval_days=None,
                month_week_number=5,
                day_of_week="MON",
            ),
            datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc),
        ),
        (
            build_reminder_data(
                schedule_type="yearly_date",
                start_at=datetime(2024, 2, 29, 10, 0),
                tracking_started_at=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                interval_days=None,
            ),
            datetime(2028, 3, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2028, 2, 29, 10, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_get_latest_unhandled_run_at_supports_all_schedule_types(
    reminder,
    now,
    expected,
) -> None:
    assert (
        scheduler_module.get_latest_unhandled_run_at(
            reminder,
            now=now,
        )
        == expected
    )


def test_get_latest_unhandled_run_at_excludes_watermark_and_old_once() -> None:
    watermark = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)
    repeating = build_reminder_data(last_handled_at=watermark)
    old_once = build_reminder_data(
        schedule_type="once",
        start_at=datetime(2026, 6, 30, 10, 0),
        tracking_started_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        interval_days=None,
    )

    assert (
        scheduler_module.get_latest_unhandled_run_at(
            repeating,
            now=datetime(2026, 7, 3, 11, 0, tzinfo=timezone.utc),
        )
        is None
    )
    assert (
        scheduler_module.get_latest_unhandled_run_at(
            old_once,
            now=datetime(2026, 7, 3, 11, 0, tzinfo=timezone.utc),
        )
        is None
    )


def test_get_latest_unhandled_run_at_handles_dst() -> None:
    reminder = build_reminder_data(
        schedule_type="every_days",
        start_at=datetime(2026, 3, 28, 2, 30),
        timezone_name="Europe/Berlin",
        tracking_started_at=datetime(2026, 3, 27, 0, 0, tzinfo=timezone.utc),
    )

    assert scheduler_module.get_latest_unhandled_run_at(
        reminder,
        now=datetime(2026, 3, 29, 2, 0, tzinfo=timezone.utc),
    ) == datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)


def test_get_latest_unhandled_run_at_has_iteration_limit(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_module, "REMINDER_OCCURRENCE_SEARCH_LIMIT", 2)

    with pytest.raises(RuntimeError, match="exceeded the safety limit"):
        scheduler_module.get_latest_unhandled_run_at(
            build_reminder_data(),
            now=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        )


def test_format_next_run_line_when_job_not_found(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    result = format_next_run_line(999)

    assert result == "Следующее срабатывание: не запланировано"


def test_format_next_run_line_when_job_exists(monkeypatch) -> None:
    fake_scheduler = FakeSchedulerWithJob(FakeJob(datetime(2026, 6, 8, 12, 12)))
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    result = format_next_run_line(1)

    assert result == "Следующее срабатывание: 08 июня в 12:12"


def test_send_once_reminder_sends_message_and_marks_sent(monkeypatch) -> None:
    bot = FakeBot()
    handled = []

    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: handled.append((args, kwargs)) or True,
    )
    scheduled_for = datetime.now(timezone.utc)

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_text="Тест once",
                schedule_type="once",
                interval_days=None,
            ),
            scheduled_for,
            is_catchup=False,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": "Тест once",
            "parse_mode": None,
        }
    ]
    assert handled == [((1, scheduled_for), {"final_status": "sent"})]


def test_send_repeating_reminder_sends_message_and_stays_active(monkeypatch) -> None:
    bot = FakeBot()
    handled = []
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: handled.append((args, kwargs)) or True,
    )
    scheduled_for = datetime.now(timezone.utc)

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_id=2,
                reminder_text="Тест repeating",
            ),
            scheduled_for,
            is_catchup=False,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": "Тест repeating",
            "parse_mode": None,
        }
    ]
    assert handled == [((2, scheduled_for), {"final_status": None})]


def test_send_repeating_weather_reminder_uses_html_parse_mode(monkeypatch) -> None:
    bot = FakeBot()
    monkeypatch.setattr(
        scheduler_module,
        "get_prepared_weather_report",
        lambda *args: None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        lambda raw_locations: (
            "<b>Прогноз погоды на сегодня</b>\n\n"
            "☁️ <b>Екатеринбург · Свердловская область</b>\n"
            "Сейчас 17°, днём до 26°. Пасмурно.\n"
            "Осадки маловероятны.\n\n"
            "Источник: Open-Meteo"
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: True,
    )

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_id=2,
                reminder_text="Екатеринбург",
                reminder_kind=REMINDER_KIND_WEATHER,
            ),
            datetime.now(timezone.utc),
            is_catchup=False,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": (
                "<b>Прогноз погоды на сегодня</b>\n\n"
                "☁️ <b>Екатеринбург · Свердловская область</b>\n"
                "Сейчас 17°, днём до 26°. Пасмурно.\n"
                "Осадки маловероятны.\n\n"
                "Источник: Open-Meteo"
            ),
            "parse_mode": "HTML",
        }
    ]


@pytest.mark.parametrize(
    ("delay", "notice_expected"),
    [
        (timedelta(minutes=5), True),
        (timedelta(minutes=4, seconds=59), False),
    ],
)
def test_late_notice_uses_scheduled_time_threshold(
    monkeypatch,
    delay,
    notice_expected,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    bot = FakeBot()
    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: True,
    )

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(reminder_text="Проверить доставку"),
            fixed_now - delay,
            is_catchup=True,
        )
    )

    assert (
        bot.messages[0]["text"].startswith("⚠️ Доставлено с опозданием.")
        is notice_expected
    )


def test_fresh_weather_catchup_builds_new_html_report(monkeypatch) -> None:
    bot = FakeBot()
    build_calls = []
    monkeypatch.setattr(
        scheduler_module,
        "get_prepared_weather_report",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("Catch-up must not read a prepared weather report.")
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        lambda raw_locations: (
            build_calls.append(raw_locations) or "<b>Новый прогноз</b>"
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: True,
    )

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_kind=REMINDER_KIND_WEATHER,
                reminder_text="Екатеринбург",
            ),
            datetime.now(timezone.utc) - timedelta(hours=1),
            is_catchup=True,
        )
    )

    assert build_calls == ["Екатеринбург"]
    assert bot.messages[0]["parse_mode"] == "HTML"
    assert "<b>Новый прогноз</b>" in bot.messages[0]["text"]


@pytest.mark.parametrize(
    ("schedule_type", "expected_status"),
    [("every_days", None), ("once", "missed")],
)
def test_stale_weather_catchup_is_handled_without_sending(
    monkeypatch,
    schedule_type,
    expected_status,
) -> None:
    bot = FakeBot()
    handled = []
    scheduled_for = datetime.now(timezone.utc) - timedelta(hours=6, seconds=1)
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: handled.append((args, kwargs)) or True,
    )

    outcome = asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_kind=REMINDER_KIND_WEATHER,
                schedule_type=schedule_type,
                interval_days=None if schedule_type == "once" else 1,
            ),
            scheduled_for,
            is_catchup=True,
        )
    )

    assert outcome == "stale_weather_skipped"
    assert bot.messages == []
    assert handled == [((1, scheduled_for), {"final_status": expected_status})]


def test_sent_occurrence_with_unrecorded_watermark_is_not_resent(
    monkeypatch,
    caplog,
) -> None:
    bot = FakeBot()
    mark_calls = []
    scheduled_for = datetime.now(timezone.utc)

    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: mark_calls.append((args, kwargs)) or False,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_reminder_occurrence_handling_state",
        lambda *args: "missing",
    )

    with caplog.at_level("WARNING"):
        outcome = asyncio.run(
            scheduler_module.deliver_reminder_occurrence(
                bot,
                build_reminder_data(reminder_id=77),
                scheduled_for,
                is_catchup=True,
            )
        )

    assert outcome == scheduler_module.DELIVERY_OUTCOME_SENT_UNRECORDED
    assert len(bot.messages) == 1
    assert mark_calls == [((77, scheduled_for), {"final_status": None})]
    assert "reminder_id=77" in caplog.text
    assert "database_state=missing" in caplog.text


@pytest.mark.parametrize(
    ("database_state", "expected_outcome"),
    [
        ("already_handled", "stale_weather_skipped"),
        ("missing", "stale_weather_unrecorded"),
    ],
)
def test_stale_weather_skip_requires_recorded_or_newer_watermark(
    monkeypatch,
    database_state,
    expected_outcome,
) -> None:
    scheduled_for = datetime.now(timezone.utc) - timedelta(hours=7)
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_reminder_occurrence_handling_state",
        lambda *args: database_state,
    )

    outcome = asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            FakeBot(),
            build_reminder_data(reminder_kind=REMINDER_KIND_WEATHER),
            scheduled_for,
            is_catchup=True,
        )
    )

    assert outcome == expected_outcome


def test_run_scheduled_reminder_reloads_row_and_skips_handled_occurrence(
    monkeypatch,
) -> None:
    delivered = []
    reminder = build_reminder_data()
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: {"id": reminder_id},
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminder,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_latest_unhandled_run_at",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        lambda *args, **kwargs: delivered.append((args, kwargs)),
    )

    asyncio.run(scheduler_module.run_scheduled_reminder(FakeBot(), reminder.id))

    assert delivered == []


def test_old_scheduled_job_does_nothing_after_reminder_deletion(monkeypatch) -> None:
    delivered = []
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        lambda *args, **kwargs: delivered.append((args, kwargs)),
    )

    asyncio.run(scheduler_module.run_scheduled_reminder(FakeBot(), 42))

    assert delivered == []


def test_run_scheduled_reminder_delivers_exact_latest_occurrence(monkeypatch) -> None:
    reminder = build_reminder_data(reminder_id=7)
    scheduled_for = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)
    delivered = []

    async def fake_deliver(bot, received_reminder, received_run, *, is_catchup):
        delivered.append((received_reminder.id, received_run, is_catchup))
        return "sent"

    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: {"id": reminder_id},
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminder,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_latest_unhandled_run_at",
        lambda *args, **kwargs: scheduled_for,
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )

    asyncio.run(scheduler_module.run_scheduled_reminder(FakeBot(), reminder.id))

    assert delivered == [(7, scheduled_for, False)]


def test_restore_catches_up_last_runs_and_continues_after_error(
    monkeypatch,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    reminders = {
        "first": build_reminder_data(reminder_id=1, reminder_text="Первое"),
        "second": build_reminder_data(reminder_id=2, reminder_text="Второе"),
        "second_updated": build_reminder_data(
            reminder_id=2,
            reminder_text="Второе",
            last_handled_at=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        ),
        "legacy": build_reminder_data(
            reminder_id=3,
            schedule_type="once",
            start_at=datetime(2026, 6, 1, 10, 0),
            tracking_started_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
            interval_days=None,
        ),
        "future": build_reminder_data(
            reminder_id=4,
            schedule_type="once",
            start_at=datetime(2026, 7, 19, 10, 0),
            interval_days=None,
        ),
        "past": build_reminder_data(
            reminder_id=5,
            schedule_type="once",
            start_at=datetime(2026, 7, 18, 11, 0),
            interval_days=None,
        ),
    }
    fake_scheduler = FakeScheduler()
    delivered = []
    missed = []

    async def fake_deliver(bot, reminder, scheduled_for, *, is_catchup):
        delivered.append((reminder.id, scheduled_for, is_catchup))
        if reminder.id == 1:
            raise RuntimeError("first catch-up failed")
        return "sent"

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: list(reminders),
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminders[row],
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_as_missed",
        lambda reminder_id: missed.append(reminder_id),
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: "second_updated" if reminder_id == 2 else None,
    )

    asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    reminder_jobs = [job for job in fake_scheduler.jobs if job["id"].isdigit()]
    assert {job["id"] for job in reminder_jobs} == {"1", "2", "4"}
    assert all(job["next_run_time"] > fixed_now for job in reminder_jobs)
    regular_jobs = [job for job in reminder_jobs if job["id"] in {"1", "2"}]
    assert {job["next_run_time"] for job in regular_jobs} == {
        datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    }
    assert missed == [3]
    assert [item[0] for item in delivered] == [1, 2, 5]
    assert delivered[0][1] == datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)
    assert delivered[1][1] == datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)
    assert delivered[2][1] == datetime(2026, 7, 18, 11, 0, tzinfo=timezone.utc)
    assert {job["id"] for job in fake_scheduler.jobs} >= {
        "weather-report-prefetch",
        "reminder-message-deletion-cleanup",
    }


def test_restore_waits_for_catchup_before_registering_close_future_run(
    monkeypatch,
) -> None:
    class MutableDateTime(datetime):
        current = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current.replace(tzinfo=None)
            return cls.current.astimezone(tz)

    reminder_states = {
        "initial": build_reminder_data(
            start_at=datetime(2026, 7, 1, 12, 1),
            last_handled_at=datetime(2026, 7, 16, 12, 1, tzinfo=timezone.utc),
        ),
        "after_july_17": build_reminder_data(
            start_at=datetime(2026, 7, 1, 12, 1),
            last_handled_at=datetime(2026, 7, 17, 12, 1, tzinfo=timezone.utc),
        ),
        "after_july_18": build_reminder_data(
            start_at=datetime(2026, 7, 1, 12, 1),
            last_handled_at=datetime(2026, 7, 18, 12, 1, tzinfo=timezone.utc),
        ),
    }
    fake_scheduler = FakeScheduler()
    first_catchup_started = asyncio.Event()
    allow_first_catchup_to_finish = asyncio.Event()
    second_catchup_started = asyncio.Event()
    allow_second_catchup_to_finish = asyncio.Event()
    delivered = []
    reload_rows = iter(["after_july_17", "after_july_18"])
    reload_calls = []

    async def delayed_deliver(bot, received, scheduled_for, *, is_catchup):
        delivered.append(scheduled_for)
        assert received.id == 1
        assert is_catchup
        assert not any(job["id"].isdigit() for job in fake_scheduler.jobs)
        if len(delivered) == 1:
            first_catchup_started.set()
            await allow_first_catchup_to_finish.wait()
        else:
            second_catchup_started.set()
            await allow_second_catchup_to_finish.wait()
        assert not any(job["id"].isdigit() for job in fake_scheduler.jobs)
        return "sent"

    def fake_reload(reminder_id):
        reload_calls.append(reminder_id)
        return next(reload_rows)

    monkeypatch.setattr(scheduler_module, "datetime", MutableDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: ["initial"],
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminder_states[row],
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        delayed_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        fake_reload,
    )

    async def run_scenario() -> None:
        restore_task = asyncio.create_task(
            scheduler_module.restore_active_reminders(FakeBot())
        )
        await first_catchup_started.wait()
        assert not any(job["id"].isdigit() for job in fake_scheduler.jobs)
        MutableDateTime.current = datetime(
            2026,
            7,
            18,
            12,
            2,
            tzinfo=timezone.utc,
        )
        allow_first_catchup_to_finish.set()
        await second_catchup_started.wait()
        assert not any(job["id"].isdigit() for job in fake_scheduler.jobs)
        allow_second_catchup_to_finish.set()
        await restore_task

    asyncio.run(run_scenario())

    assert delivered == [
        datetime(2026, 7, 17, 12, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 18, 12, 1, tzinfo=timezone.utc),
    ]
    assert reload_calls == [1, 1]
    reminder_jobs = [job for job in fake_scheduler.jobs if job["id"].isdigit()]
    assert len(reminder_jobs) == 1
    assert reminder_jobs[0]["next_run_time"] == datetime(
        2026,
        7,
        19,
        12,
        1,
        tzinfo=timezone.utc,
    )


def test_restore_reloads_regular_reminder_after_recorded_catchup(
    monkeypatch,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    reminders = {
        "initial": build_reminder_data(
            last_handled_at=datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc),
        ),
        "updated": build_reminder_data(
            last_handled_at=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        ),
    }
    fake_scheduler = FakeScheduler()
    reload_calls = []
    delivered = []

    async def fake_deliver(bot, reminder, scheduled_for, *, is_catchup):
        delivered.append(scheduled_for)
        return scheduler_module.DELIVERY_OUTCOME_SENT

    def fake_reload(reminder_id):
        reload_calls.append(reminder_id)
        return "updated"

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: ["initial"],
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminders[row],
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        fake_reload,
    )

    asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    assert delivered == [datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)]
    assert reload_calls == [1]
    reminder_jobs = [job for job in fake_scheduler.jobs if job["id"] == "1"]
    assert reminder_jobs[0]["next_run_time"] == datetime(
        2026,
        7,
        19,
        10,
        0,
        tzinfo=timezone.utc,
    )


def test_restore_does_not_schedule_regular_reminder_that_became_inactive(
    monkeypatch,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    reminder = build_reminder_data(
        last_handled_at=datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc),
    )
    fake_scheduler = FakeScheduler()
    delivered = []
    reload_calls = []

    async def fake_deliver(bot, received, scheduled_for, *, is_catchup):
        delivered.append(scheduled_for)
        return scheduler_module.DELIVERY_OUTCOME_SENT

    def fake_reload(reminder_id):
        reload_calls.append(reminder_id)
        return None

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(scheduler_module, "get_all_active_reminders", lambda: [1])
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminder,
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        fake_reload,
    )

    asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    assert delivered == [datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)]
    assert reload_calls == [1]
    assert not any(job["id"].isdigit() for job in fake_scheduler.jobs)


def test_restore_sent_unrecorded_does_not_repeat_catchup(
    monkeypatch,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    reminder = build_reminder_data(
        last_handled_at=datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc),
    )
    fake_scheduler = FakeScheduler()
    delivered = []

    async def fake_deliver(bot, received, scheduled_for, *, is_catchup):
        delivered.append(scheduled_for)
        return scheduler_module.DELIVERY_OUTCOME_SENT_UNRECORDED

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(scheduler_module, "get_all_active_reminders", lambda: [1])
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminder,
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: (_ for _ in ()).throw(
            AssertionError("Unrecorded catch-up must not reload for redelivery.")
        ),
    )

    asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    assert delivered == [datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)]
    reminder_jobs = [job for job in fake_scheduler.jobs if job["id"] == "1"]
    assert reminder_jobs[0]["next_run_time"] == datetime(
        2026,
        7,
        19,
        10,
        0,
        tzinfo=timezone.utc,
    )


def test_restore_catchup_limit_stops_pathological_cycle(
    monkeypatch,
    caplog,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    reminder = build_reminder_data()
    fake_scheduler = FakeScheduler()
    delivered = []
    calculation_calls = []

    def pathological_calculation(received, *, now):
        calculation_calls.append(received.id)
        return fixed_now - timedelta(minutes=len(calculation_calls))

    async def fake_deliver(bot, received, scheduled_for, *, is_catchup):
        delivered.append(scheduled_for)
        return scheduler_module.DELIVERY_OUTCOME_SENT

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(scheduler_module, "REMINDER_RESTORE_CATCHUP_LIMIT", 2)
    monkeypatch.setattr(scheduler_module, "get_all_active_reminders", lambda: [1])
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminder,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_latest_unhandled_run_at",
        pathological_calculation,
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: 1,
    )

    with caplog.at_level("ERROR"):
        asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    assert len(delivered) == 2
    assert calculation_calls == [1, 1, 1]
    assert "stage=catchup_limit limit=2" in caplog.text
    assert not any(job["id"].isdigit() for job in fake_scheduler.jobs)


def test_restore_catches_iteration_created_during_repeated_catchup(
    monkeypatch,
) -> None:
    class MutableDateTime(datetime):
        current = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current.replace(tzinfo=None)
            return cls.current.astimezone(tz)

    reminder_states = {
        day: build_reminder_data(
            start_at=datetime(2026, 7, 1, 12, 1),
            last_handled_at=datetime(2026, 7, day, 12, 1, tzinfo=timezone.utc),
        )
        for day in (16, 17, 18, 19)
    }
    fake_scheduler = FakeScheduler()
    delivered = []
    reload_days = iter((17, 18, 19))

    async def fake_deliver(bot, reminder, scheduled_for, *, is_catchup):
        delivered.append(scheduled_for)
        if len(delivered) == 1:
            MutableDateTime.current = datetime(
                2026,
                7,
                18,
                12,
                2,
                tzinfo=timezone.utc,
            )
        elif len(delivered) == 2:
            MutableDateTime.current = datetime(
                2026,
                7,
                19,
                12,
                2,
                tzinfo=timezone.utc,
            )
        return scheduler_module.DELIVERY_OUTCOME_SENT

    monkeypatch.setattr(scheduler_module, "datetime", MutableDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(scheduler_module, "get_all_active_reminders", lambda: [16])
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda day: reminder_states[day],
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: next(reload_days),
    )

    asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    assert delivered == [
        datetime(2026, 7, 17, 12, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 18, 12, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 19, 12, 1, tzinfo=timezone.utc),
    ]
    reminder_jobs = [job for job in fake_scheduler.jobs if job["id"] == "1"]
    assert reminder_jobs[0]["next_run_time"] == datetime(
        2026,
        7,
        20,
        12,
        1,
        tzinfo=timezone.utc,
    )


def test_restore_mapping_error_does_not_block_next_or_maintenance_jobs(
    monkeypatch,
    caplog,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    future = build_reminder_data(
        reminder_id=2,
        chat_id=202,
        schedule_type="once",
        start_at=datetime(2026, 7, 19, 10, 0),
        interval_days=None,
    )
    rows = [
        {"id": 1, "chat_id": 101},
        {"id": 2, "chat_id": 202},
    ]
    fake_scheduler = FakeScheduler()

    def fake_build(row):
        if row["id"] == 1:
            raise ValueError("invalid reminder row")
        return future

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(scheduler_module, "get_all_active_reminders", lambda: rows)
    monkeypatch.setattr(scheduler_module, "build_reminder_read_data", fake_build)

    with caplog.at_level("ERROR"):
        asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    job_ids = {job["id"] for job in fake_scheduler.jobs}
    assert job_ids >= {
        "2",
        "weather-report-prefetch",
        "reminder-message-deletion-cleanup",
    }
    assert "reminder_id=1 chat_id=101 stage=mapping error_type=ValueError" in (
        caplog.text
    )


def test_restore_calculation_error_does_not_block_next_reminder(
    monkeypatch,
    caplog,
) -> None:
    fixed_now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    reminders = {
        1: build_reminder_data(reminder_id=1, chat_id=101),
        2: build_reminder_data(
            reminder_id=2,
            chat_id=202,
            schedule_type="once",
            start_at=datetime(2026, 7, 19, 10, 0),
            interval_days=None,
        ),
    }
    fake_scheduler = FakeScheduler()
    real_calculation = scheduler_module.get_latest_unhandled_run_at

    def fake_calculation(reminder, *, now):
        if reminder.id == 1:
            raise RuntimeError("invalid trigger")
        return real_calculation(reminder, now=now)

    monkeypatch.setattr(scheduler_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: [
            {"id": 1, "chat_id": 101},
            {"id": 2, "chat_id": 202},
        ],
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminders[row["id"]],
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_latest_unhandled_run_at",
        fake_calculation,
    )

    with caplog.at_level("ERROR"):
        asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    assert {job["id"] for job in fake_scheduler.jobs} >= {
        "2",
        "weather-report-prefetch",
        "reminder-message-deletion-cleanup",
    }
    assert (
        "reminder_id=1 chat_id=101 stage=catchup_calculation error_type=RuntimeError"
    ) in caplog.text


def test_future_once_becomes_catchup_while_previous_reminder_is_processed(
    monkeypatch,
) -> None:
    class MutableDateTime(datetime):
        current = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current.replace(tzinfo=None)
            return cls.current.astimezone(tz)

    repeating = build_reminder_data(
        reminder_id=1,
        start_at=datetime(2026, 7, 1, 10, 0),
        last_handled_at=datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc),
    )
    repeating_updated = build_reminder_data(
        reminder_id=1,
        start_at=datetime(2026, 7, 1, 10, 0),
        last_handled_at=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
    )
    once = build_reminder_data(
        reminder_id=2,
        schedule_type="once",
        start_at=datetime(2026, 7, 18, 12, 0, 30),
        interval_days=None,
    )
    reminders = {1: repeating, 2: once}
    fake_scheduler = FakeScheduler()
    delivered = []

    async def fake_deliver(bot, reminder, scheduled_for, *, is_catchup):
        delivered.append((reminder.id, scheduled_for, is_catchup))
        if reminder.id == 1:
            MutableDateTime.current = datetime(
                2026,
                7,
                18,
                12,
                1,
                tzinfo=timezone.utc,
            )
        return "sent"

    monkeypatch.setattr(scheduler_module, "datetime", MutableDateTime)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: [
            {"id": 1, "chat_id": 100},
            {"id": 2, "chat_id": 100},
        ],
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda row: reminders[row["id"]],
    )
    monkeypatch.setattr(
        scheduler_module,
        "deliver_reminder_occurrence",
        fake_deliver,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_active_reminder_from_db",
        lambda reminder_id: (
            {"id": 1, "chat_id": 100, "reloaded": True} if reminder_id == 1 else None
        ),
    )

    def map_initial_or_reloaded(row):
        if row.get("reloaded"):
            return repeating_updated
        return reminders[row["id"]]

    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        map_initial_or_reloaded,
    )

    asyncio.run(scheduler_module.restore_active_reminders(FakeBot()))

    assert [item[0] for item in delivered] == [1, 2]
    assert delivered[1][1] == datetime(
        2026,
        7,
        18,
        12,
        0,
        30,
        tzinfo=timezone.utc,
    )
    assert not any(job["id"] == "2" for job in fake_scheduler.jobs)


def test_build_reminder_message_returns_text_for_text_reminder() -> None:
    assert (
        build_reminder_message(
            reminder_text="Тест text",
            reminder_kind=REMINDER_KIND_TEXT,
        )
        == "Тест text"
    )


def test_build_reminder_message_builds_weather_report(monkeypatch) -> None:
    calls = []

    def fake_build_weather_report(raw_locations: str) -> str:
        calls.append(raw_locations)
        return "<b>Прогноз погоды на сегодня</b>\n\n☁️ <b>Екатеринбург</b>"

    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        fake_build_weather_report,
    )

    assert (
        build_reminder_message(
            reminder_text="Екатеринбург",
            reminder_kind=REMINDER_KIND_WEATHER,
        )
        == "<b>Прогноз погоды на сегодня</b>\n\n☁️ <b>Екатеринбург</b>"
    )
    assert calls == ["Екатеринбург"]


def test_build_reminder_message_returns_readable_weather_validation_error(
    monkeypatch,
) -> None:
    def fake_build_weather_report(raw_locations: str) -> str:
        raise ValueError("weather_locations are required.")

    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        fake_build_weather_report,
    )

    assert (
        build_reminder_message(
            reminder_text="",
            reminder_kind=REMINDER_KIND_WEATHER,
        )
        == "Не смог подготовить прогноз погоды.\n"
        "weather_locations are required."
    )


def test_build_reminder_message_returns_readable_weather_service_error(
    monkeypatch,
) -> None:
    def fake_build_weather_report(raw_locations: str) -> str:
        raise scheduler_module.WeatherServiceError(
            "Погодный сервис временно недоступен."
        )

    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        fake_build_weather_report,
    )

    assert (
        build_reminder_message(
            reminder_text="Екатеринбург",
            reminder_kind=REMINDER_KIND_WEATHER,
        )
        == "Не смог получить прогноз погоды.\n"
        "Погодный сервис временно недоступен."
    )


def test_schedule_monthly_day_reminder_adds_cron_job(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    start_at = datetime(2026, 6, 11, 12, 12)

    schedule_reminder(
        bot=FakeBot(),
        reminder_id=7,
        chat_id=100,
        reminder_text="Тест monthly day",
        schedule_type="monthly_day",
        start_at=start_at,
        month_day=11,
    )

    job = fake_scheduler.jobs[0]

    assert job["trigger"] == "cron"
    assert job["day"] == 11
    assert job["hour"] == 12
    assert job["minute"] == 12
    assert job["start_date"] == start_at
    assert job["id"] == "7"


def test_schedule_healthcheck_adds_interval_job(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    bot = FakeBot()

    schedule_healthcheck(
        bot=bot,
        chat_id=100,
        interval_minutes=360,
    )

    assert len(fake_scheduler.jobs) == 1

    job = fake_scheduler.jobs[0]

    assert job["func"] == send_healthcheck
    assert job["trigger"] == "interval"
    assert job["minutes"] == 360
    assert job["args"] == [bot, 100]
    assert job["id"] == "healthcheck"
    assert job["replace_existing"] is True
    assert "next_run_time" in job


def test_send_healthcheck_sends_status_message(monkeypatch) -> None:
    class FakeHealthScheduler:
        running = True

        def get_jobs(self):
            return [object(), object(), object()]

    bot = FakeBot()

    monkeypatch.setattr(scheduler_module, "scheduler", FakeHealthScheduler())
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: [object(), object()],
    )
    monkeypatch.setattr(scheduler_module, "count_active_chats", lambda: 1)

    asyncio.run(
        send_healthcheck(
            bot=bot,
            chat_id=100,
        )
    )

    assert len(bot.messages) == 1

    message = bot.messages[0]

    assert message["chat_id"] == 100
    assert "✅ Бот работает." in message["text"]
    assert "Время сервера UTC:" in message["text"]
    assert "Scheduler: running" in message["text"]
    assert "Запланированных jobs: 3" in message["text"]
    assert "Активных напоминаний в базе: 2" in message["text"]
    assert "Чатов с активными напоминаниями: 1" in message["text"]


def test_schedule_weather_report_prefetch_adds_minutely_job(monkeypatch) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)

    scheduler_module.schedule_weather_report_prefetch()

    assert len(fake_scheduler.jobs) == 1

    job = fake_scheduler.jobs[0]

    assert job["func"] == scheduler_module.prefetch_weather_reports
    assert job["trigger"] == "interval"
    assert job["minutes"] == 1
    assert job["id"] == "weather-report-prefetch"
    assert job["replace_existing"] is True
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    assert "next_run_time" in job


def test_prefetch_weather_reports_saves_report_for_upcoming_reminder(
    monkeypatch,
) -> None:
    scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=4)
    reminder_data = SimpleNamespace(
        id=12,
        reminder_kind=REMINDER_KIND_WEATHER,
        reminder_text="Екатеринбург; Хургада",
    )
    build_calls = []
    saved_reports = []

    monkeypatch.setattr(
        scheduler_module,
        "delete_expired_prepared_weather_reports",
        lambda now: None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: [object()],
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda reminder: reminder_data,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_next_run_at",
        lambda reminder_id: scheduled_for,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_prepared_weather_report",
        lambda *args: None,
    )

    def fake_build_weather_report(
        raw_locations: str,
        *,
        target_time_utc: datetime,
        raise_on_error: bool,
        request_attempts: int,
    ) -> str:
        build_calls.append(
            {
                "raw_locations": raw_locations,
                "target_time_utc": target_time_utc,
                "raise_on_error": raise_on_error,
                "request_attempts": request_attempts,
            }
        )
        return "Подготовленный прогноз"

    def fake_save_prepared_weather_report(
        reminder_id: int,
        report_scheduled_for: datetime,
        reminder_text: str,
        report_html: str,
    ) -> None:
        saved_reports.append(
            {
                "reminder_id": reminder_id,
                "scheduled_for": report_scheduled_for,
                "reminder_text": reminder_text,
                "report_html": report_html,
            }
        )

    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        fake_build_weather_report,
    )
    monkeypatch.setattr(
        scheduler_module,
        "save_prepared_weather_report",
        fake_save_prepared_weather_report,
    )

    asyncio.run(scheduler_module.prefetch_weather_reports())

    assert build_calls == [
        {
            "raw_locations": "Екатеринбург; Хургада",
            "target_time_utc": scheduled_for,
            "raise_on_error": True,
            "request_attempts": 1,
        }
    ]
    assert saved_reports == [
        {
            "reminder_id": 12,
            "scheduled_for": scheduled_for,
            "reminder_text": "Екатеринбург; Хургада",
            "report_html": "Подготовленный прогноз",
        }
    ]


def test_prefetch_weather_reports_does_not_save_failed_report(monkeypatch) -> None:
    scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=4)
    reminder_data = SimpleNamespace(
        id=12,
        reminder_kind=REMINDER_KIND_WEATHER,
        reminder_text="Екатеринбург",
    )
    saved_reports = []

    monkeypatch.setattr(
        scheduler_module,
        "delete_expired_prepared_weather_reports",
        lambda now: None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_all_active_reminders",
        lambda: [object()],
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_read_data",
        lambda reminder: reminder_data,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_next_run_at",
        lambda reminder_id: scheduled_for,
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_prepared_weather_report",
        lambda *args: None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            scheduler_module.WeatherServiceError("Погодный сервис временно недоступен.")
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "save_prepared_weather_report",
        lambda *args: saved_reports.append(args),
    )

    asyncio.run(scheduler_module.prefetch_weather_reports())

    assert saved_reports == []


def test_send_repeating_weather_reminder_uses_prepared_report_and_deletes_it(
    monkeypatch,
) -> None:
    bot = FakeBot()
    deleted_reports = []
    prepared_report = {
        "scheduled_for_utc": "2026-07-07T04:30:00+00:00",
        "report_html": "<b>Подготовленный прогноз</b>",
    }

    monkeypatch.setattr(
        scheduler_module,
        "get_prepared_weather_report",
        lambda *args: prepared_report,
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_reminder_message",
        lambda *args: (_ for _ in ()).throw(
            AssertionError(
                "Не должен выполняться новый запрос погоды при готовом отчёте."
            )
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "delete_prepared_weather_report",
        lambda reminder_id, scheduled_for_utc: deleted_reports.append(
            {
                "reminder_id": reminder_id,
                "scheduled_for_utc": scheduled_for_utc,
            }
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: True,
    )

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_id=12,
                reminder_text="Екатеринбург",
                reminder_kind=REMINDER_KIND_WEATHER,
            ),
            datetime.now(timezone.utc),
            is_catchup=False,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": "<b>Подготовленный прогноз</b>",
            "parse_mode": "HTML",
        }
    ]
    assert deleted_reports == [
        {
            "reminder_id": 12,
            "scheduled_for_utc": "2026-07-07T04:30:00+00:00",
        }
    ]


def test_successful_send_with_auto_delete_enqueues_message(monkeypatch) -> None:
    bot = FakeBot()
    queued_messages = []

    def fake_enqueue_reminder_message_deletion(**kwargs) -> bool:
        queued_messages.append(kwargs)
        return True

    monkeypatch.setattr(
        scheduler_module,
        "enqueue_reminder_message_deletion",
        fake_enqueue_reminder_message_deletion,
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: True,
    )

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_id=2,
                reminder_text="Тест repeating",
                delete_after_two_days=True,
            ),
            datetime.now(timezone.utc),
            is_catchup=True,
        )
    )

    assert len(bot.messages) == 1
    assert queued_messages == [
        {
            "reminder_id": 2,
            "chat_id": 100,
            "message_id": 1,
            "sent_at": bot.sent_at,
            "delete_at": bot.sent_at + timedelta(hours=47, minutes=45),
        }
    ]


def test_successful_send_without_auto_delete_does_not_enqueue(monkeypatch) -> None:
    bot = FakeBot()

    monkeypatch.setattr(
        scheduler_module,
        "enqueue_reminder_message_deletion",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Disabled auto-delete must not enqueue a message.")
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: True,
    )

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_id=2,
                reminder_text="Тест repeating",
            ),
            datetime.now(timezone.utc),
            is_catchup=False,
        )
    )

    assert len(bot.messages) == 1


def test_send_error_does_not_enqueue_message(monkeypatch) -> None:
    class FailingBot(FakeBot):
        async def send_message(self, **kwargs):
            raise RuntimeError("Telegram send failed")

    queued_messages = []
    handled = []
    monkeypatch.setattr(
        scheduler_module,
        "enqueue_reminder_message_deletion",
        lambda **kwargs: queued_messages.append(kwargs),
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: handled.append((args, kwargs)) or True,
    )

    with pytest.raises(RuntimeError, match="Telegram send failed"):
        asyncio.run(
            scheduler_module.deliver_reminder_occurrence(
                FailingBot(),
                build_reminder_data(
                    reminder_id=2,
                    reminder_text="Тест repeating",
                    delete_after_two_days=True,
                ),
                datetime.now(timezone.utc),
                is_catchup=False,
            )
        )

    assert queued_messages == []
    assert handled == []


def test_queue_write_error_does_not_resend_or_block_once_status(
    monkeypatch,
) -> None:
    bot = FakeBot()
    enqueue_attempts = []
    handled = []

    def fail_enqueue(**kwargs) -> bool:
        enqueue_attempts.append(kwargs)
        raise sqlite3.OperationalError("database is locked")

    async def skip_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(
        scheduler_module,
        "enqueue_reminder_message_deletion",
        fail_enqueue,
    )
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", skip_sleep)
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: handled.append((args, kwargs)) or True,
    )
    scheduled_for = datetime.now(timezone.utc)

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_text="Тест once",
                schedule_type="once",
                interval_days=None,
                delete_after_two_days=True,
            ),
            scheduled_for,
            is_catchup=False,
        )
    )

    assert len(bot.messages) == 1
    assert len(enqueue_attempts) == scheduler_module.MESSAGE_DELETION_ENQUEUE_ATTEMPTS
    assert handled == [((1, scheduled_for), {"final_status": "sent"})]


def test_weather_error_message_is_enqueued_when_telegram_accepts_it(
    monkeypatch,
) -> None:
    bot = FakeBot()
    queued_messages = []
    monkeypatch.setattr(
        scheduler_module,
        "get_prepared_weather_report",
        lambda *args: None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "build_weather_report",
        lambda raw_locations: (_ for _ in ()).throw(
            scheduler_module.WeatherServiceError("Сервис временно недоступен.")
        ),
    )
    monkeypatch.setattr(
        scheduler_module,
        "enqueue_reminder_message_deletion",
        lambda **kwargs: queued_messages.append(kwargs) or True,
    )
    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_occurrence_handled",
        lambda *args, **kwargs: True,
    )

    asyncio.run(
        scheduler_module.deliver_reminder_occurrence(
            bot,
            build_reminder_data(
                reminder_id=12,
                reminder_text="Екатеринбург",
                reminder_kind=REMINDER_KIND_WEATHER,
                delete_after_two_days=True,
            ),
            datetime.now(timezone.utc),
            is_catchup=False,
        )
    )

    assert "Не смог получить прогноз погоды" in bot.messages[0]["text"]
    assert queued_messages[0]["message_id"] == 1


def build_message_deletion_row(
    *,
    queue_id: int = 1,
    message_id: int = 501,
    sent_at: datetime,
    delete_at: datetime | None = None,
    delete_attempts: int = 0,
) -> dict[str, object]:
    actual_delete_at = delete_at or (sent_at + scheduler_module.MESSAGE_DELETION_DELAY)
    return {
        "id": queue_id,
        "reminder_id": 12,
        "chat_id": 100,
        "message_id": message_id,
        "sent_at_utc": sent_at.isoformat(timespec="seconds"),
        "delete_at_utc": actual_delete_at.isoformat(timespec="seconds"),
        "delete_attempts": delete_attempts,
        "next_attempt_at_utc": actual_delete_at.isoformat(timespec="seconds"),
        "last_error": None,
    }


def test_message_is_not_deleted_before_delete_at(monkeypatch) -> None:
    bot = FakeBot()
    now = datetime.now(timezone.utc)
    row = build_message_deletion_row(sent_at=now - timedelta(hours=1))
    rescheduled = []
    monkeypatch.setattr(
        scheduler_module,
        "reschedule_reminder_message_deletion",
        lambda **kwargs: rescheduled.append(kwargs),
    )

    asyncio.run(scheduler_module.process_reminder_message_deletion(bot, row))

    assert bot.deleted_messages == []
    assert rescheduled[0]["next_attempt_at"] == scheduler_module.parse_utc_datetime(
        row["delete_at_utc"]
    )


def test_message_is_deleted_at_delete_at(monkeypatch) -> None:
    bot = FakeBot()
    sent_at = datetime.now(timezone.utc) - timedelta(hours=47, minutes=46)
    row = build_message_deletion_row(sent_at=sent_at)
    removed_ids = []
    monkeypatch.setattr(
        scheduler_module,
        "delete_reminder_message_deletion",
        lambda queue_id: removed_ids.append(queue_id),
    )

    asyncio.run(scheduler_module.process_reminder_message_deletion(bot, row))

    assert bot.deleted_messages == [{"chat_id": 100, "message_id": 501}]
    assert removed_ids == [1]


def test_message_not_found_is_idempotent_success(monkeypatch) -> None:
    class MissingMessageBot(FakeBot):
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            raise TelegramBadRequest(
                method=DeleteMessage(chat_id=chat_id, message_id=message_id),
                message="message to delete not found",
            )

    sent_at = datetime.now(timezone.utc) - timedelta(hours=47, minutes=46)
    row = build_message_deletion_row(sent_at=sent_at)
    removed_ids = []
    monkeypatch.setattr(
        scheduler_module,
        "delete_reminder_message_deletion",
        lambda queue_id: removed_ids.append(queue_id),
    )

    asyncio.run(
        scheduler_module.process_reminder_message_deletion(
            MissingMessageBot(),
            row,
        )
    )

    assert removed_ids == [1]


def test_temporary_delete_error_is_rescheduled(monkeypatch) -> None:
    class NetworkFailureBot(FakeBot):
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            raise TelegramNetworkError(
                method=DeleteMessage(chat_id=chat_id, message_id=message_id),
                message="network unavailable",
            )

    sent_at = datetime.now(timezone.utc) - timedelta(hours=47, minutes=46)
    row = build_message_deletion_row(sent_at=sent_at)
    rescheduled = []
    monkeypatch.setattr(
        scheduler_module,
        "reschedule_reminder_message_deletion",
        lambda **kwargs: rescheduled.append(kwargs),
    )

    asyncio.run(
        scheduler_module.process_reminder_message_deletion(
            NetworkFailureBot(),
            row,
        )
    )

    assert rescheduled[0]["delete_attempts"] == 1
    assert "network unavailable" in rescheduled[0]["last_error"]
    assert (
        timedelta(seconds=50)
        <= (rescheduled[0]["next_attempt_at"] - datetime.now(timezone.utc))
        <= timedelta(seconds=60)
    )


def test_retry_after_is_respected(monkeypatch) -> None:
    class RetryAfterBot(FakeBot):
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            raise TelegramRetryAfter(
                method=DeleteMessage(chat_id=chat_id, message_id=message_id),
                message="Too Many Requests",
                retry_after=120,
            )

    sent_at = datetime.now(timezone.utc) - timedelta(hours=47, minutes=46)
    row = build_message_deletion_row(sent_at=sent_at)
    rescheduled = []
    monkeypatch.setattr(
        scheduler_module,
        "reschedule_reminder_message_deletion",
        lambda **kwargs: rescheduled.append(kwargs),
    )

    asyncio.run(
        scheduler_module.process_reminder_message_deletion(RetryAfterBot(), row)
    )

    assert (
        timedelta(seconds=110)
        <= (rescheduled[0]["next_attempt_at"] - datetime.now(timezone.utc))
        <= timedelta(seconds=120)
    )


def test_terminal_delete_error_removes_queue_item(monkeypatch) -> None:
    class ForbiddenBot(FakeBot):
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            raise TelegramForbiddenError(
                method=DeleteMessage(chat_id=chat_id, message_id=message_id),
                message="bot was blocked",
            )

    sent_at = datetime.now(timezone.utc) - timedelta(hours=47, minutes=46)
    row = build_message_deletion_row(sent_at=sent_at)
    removed_ids = []
    monkeypatch.setattr(
        scheduler_module,
        "delete_reminder_message_deletion",
        lambda queue_id: removed_ids.append(queue_id),
    )

    asyncio.run(scheduler_module.process_reminder_message_deletion(ForbiddenBot(), row))

    assert removed_ids == [1]


def test_expired_message_is_removed_without_telegram_call(monkeypatch) -> None:
    bot = FakeBot()
    sent_at = datetime.now(timezone.utc) - timedelta(hours=48, seconds=1)
    row = build_message_deletion_row(sent_at=sent_at)
    removed_ids = []
    monkeypatch.setattr(
        scheduler_module,
        "delete_reminder_message_deletion",
        lambda queue_id: removed_ids.append(queue_id),
    )

    asyncio.run(scheduler_module.process_reminder_message_deletion(bot, row))

    assert bot.deleted_messages == []
    assert removed_ids == [1]


def test_cleanup_error_for_one_message_does_not_block_next(monkeypatch) -> None:
    class PartiallyFailingBot(FakeBot):
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            if message_id == 501:
                raise TelegramForbiddenError(
                    method=DeleteMessage(chat_id=chat_id, message_id=message_id),
                    message="bot was blocked",
                )
            return await super().delete_message(chat_id, message_id)

    sent_at = datetime.now(timezone.utc) - timedelta(hours=47, minutes=46)
    rows = [
        build_message_deletion_row(
            queue_id=1,
            message_id=501,
            sent_at=sent_at,
        ),
        build_message_deletion_row(
            queue_id=2,
            message_id=502,
            sent_at=sent_at,
        ),
    ]
    removed_ids = []
    monkeypatch.setattr(
        scheduler_module,
        "get_due_reminder_message_deletions",
        lambda *args, **kwargs: rows,
    )
    monkeypatch.setattr(
        scheduler_module,
        "delete_reminder_message_deletion",
        lambda queue_id: removed_ids.append(queue_id),
    )

    bot = PartiallyFailingBot()
    asyncio.run(scheduler_module.cleanup_reminder_message_deletion_queue(bot))

    assert removed_ids == [1, 2]
    assert bot.deleted_messages == [{"chat_id": 100, "message_id": 502}]


def test_schedule_reminder_message_deletion_cleanup_adds_minutely_job(
    monkeypatch,
) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    bot = FakeBot()

    scheduler_module.schedule_reminder_message_deletion_cleanup(bot)

    assert len(fake_scheduler.jobs) == 1
    job = fake_scheduler.jobs[0]
    assert job["func"] == scheduler_module.cleanup_reminder_message_deletion_queue
    assert job["trigger"] == "interval"
    assert job["minutes"] == 1
    assert job["args"] == [bot]
    assert job["id"] == "reminder-message-deletion-cleanup"
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    assert "next_run_time" in job


def test_cleanup_with_empty_persistent_queue_does_nothing(monkeypatch) -> None:
    bot = FakeBot()
    monkeypatch.setattr(
        scheduler_module,
        "get_due_reminder_message_deletions",
        lambda *args, **kwargs: [],
    )

    asyncio.run(scheduler_module.cleanup_reminder_message_deletion_queue(bot))

    assert bot.deleted_messages == []


def test_persistent_queue_is_processed_after_restart_and_only_once(
    monkeypatch,
    tmp_path,
) -> None:
    test_db_path = tmp_path / "test_reminders.db"
    monkeypatch.setattr(database_module, "DB_PATH", test_db_path)
    database_module.init_db()

    sent_at = datetime.now(timezone.utc) - timedelta(hours=47, minutes=46)
    database_module.enqueue_reminder_message_deletion(
        reminder_id=12,
        chat_id=100,
        message_id=501,
        sent_at=sent_at,
        delete_at=sent_at + scheduler_module.MESSAGE_DELETION_DELAY,
    )

    # A second initialization represents a process restart over the same SQLite file.
    database_module.init_db()
    bot = FakeBot()

    asyncio.run(scheduler_module.cleanup_reminder_message_deletion_queue(bot))
    asyncio.run(scheduler_module.cleanup_reminder_message_deletion_queue(bot))

    assert bot.deleted_messages == [{"chat_id": 100, "message_id": 501}]
    assert (
        database_module.get_due_reminder_message_deletions(
            datetime.now(timezone.utc),
            limit=10,
        )
        == []
    )
