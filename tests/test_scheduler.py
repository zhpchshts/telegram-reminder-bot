import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import scheduler as scheduler_module
from app.constants import REMINDER_KIND_TEXT, REMINDER_KIND_WEATHER
from app.scheduler import (
    build_reminder_message,
    format_next_run_line,
    schedule_healthcheck,
    schedule_reminder,
    send_healthcheck,
    send_once_reminder,
    send_repeating_reminder,
)


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

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
    ) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
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
    assert job["args"][1:] == [100, "Тест once", REMINDER_KIND_TEXT, 1]


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
    marked_ids = []

    monkeypatch.setattr(
        scheduler_module,
        "mark_reminder_as_sent",
        lambda reminder_id: marked_ids.append(reminder_id),
    )

    asyncio.run(
        send_once_reminder(
            bot=bot,
            chat_id=100,
            reminder_text="Тест once",
            reminder_kind=REMINDER_KIND_TEXT,
            reminder_id=1,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": "Тест once",
            "parse_mode": None,
        }
    ]
    assert marked_ids == [1]


def test_send_repeating_reminder_sends_message() -> None:
    bot = FakeBot()

    asyncio.run(
        send_repeating_reminder(
            bot=bot,
            chat_id=100,
            reminder_text="Тест repeating",
            reminder_kind=REMINDER_KIND_TEXT,
            reminder_id=2,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": "Тест repeating",
            "parse_mode": None,
        }
    ]


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

    asyncio.run(
        send_repeating_reminder(
            bot=bot,
            chat_id=100,
            reminder_text="Екатеринбург",
            reminder_kind=REMINDER_KIND_WEATHER,
            reminder_id=2,
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

    asyncio.run(
        send_repeating_reminder(
            bot=bot,
            chat_id=100,
            reminder_text="Екатеринбург",
            reminder_kind=REMINDER_KIND_WEATHER,
            reminder_id=12,
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
