import asyncio
from datetime import datetime

import pytest

from app import scheduler as scheduler_module
from app.scheduler import (
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

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
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
    assert job["args"][1:] == [100, "Тест once", 1]


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
            reminder_id=1,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": "Напоминание #1:\n\nТест once",
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
            reminder_id=2,
        )
    )

    assert bot.messages == [
        {
            "chat_id": 100,
            "text": "Повторяющееся напоминание #2:\n\nТест repeating",
        }
    ]


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
