import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import handlers
from app.reminder_models import ReminderCreateData


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=100)
        self.answers: list[tuple[str, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs))


@dataclass(frozen=True, slots=True)
class CreateCommandCase:
    command_text: str
    handler: Callable[[FakeMessage, object], Awaitable[None]]
    expected_data: ReminderCreateData


@pytest.mark.parametrize(
    "case",
    [
        CreateCommandCase(
            command_text="/remind 2099-06-10 12:12 Проверить статус релиза",
            handler=handlers.remind,
            expected_data=ReminderCreateData(
                reminder_text="Проверить статус релиза",
                schedule_type="once",
                start_at=datetime(
                    2099,
                    6,
                    10,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
            ),
        ),
        CreateCommandCase(
            command_text="/every_days 3 12:12 Каждые три дня",
            handler=handlers.every_days,
            expected_data=ReminderCreateData(
                reminder_text="Каждые три дня",
                schedule_type="every_days",
                start_at=datetime(
                    2090,
                    1,
                    1,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                interval_days=3,
            ),
        ),
        CreateCommandCase(
            command_text=(
                "/every_days_from 3 2099-06-10 12:12 Каждые три дня с 10 июня"
            ),
            handler=handlers.every_days_from,
            expected_data=ReminderCreateData(
                reminder_text="Каждые три дня с 10 июня",
                schedule_type="every_days",
                start_at=datetime(
                    2099,
                    6,
                    10,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                interval_days=3,
            ),
        ),
        CreateCommandCase(
            command_text="/every_week 2 SUN 12:12 Каждое второе воскресенье",
            handler=handlers.every_week,
            expected_data=ReminderCreateData(
                reminder_text="Каждое второе воскресенье",
                schedule_type="every_week",
                start_at=datetime(
                    2090,
                    1,
                    1,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                interval_weeks=2,
                day_of_week="SUN",
            ),
        ),
        CreateCommandCase(
            command_text=(
                "/every_week_from 2 SUN 2099-06-14 12:12 "
                "Каждое второе воскресенье с даты"
            ),
            handler=handlers.every_week_from,
            expected_data=ReminderCreateData(
                reminder_text="Каждое второе воскресенье с даты",
                schedule_type="every_week",
                start_at=datetime(
                    2099,
                    6,
                    14,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                interval_weeks=2,
                day_of_week="SUN",
            ),
        ),
        CreateCommandCase(
            command_text="/monthly_weekday 1 MON 12:12 Первый понедельник",
            handler=handlers.monthly_weekday,
            expected_data=ReminderCreateData(
                reminder_text="Первый понедельник",
                schedule_type="monthly_weekday",
                start_at=datetime(
                    2090,
                    1,
                    1,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                month_week_number=1,
                day_of_week="MON",
            ),
        ),
        CreateCommandCase(
            command_text=(
                "/monthly_weekday_from 1 MON 2099-07-01 12:12 "
                "Первый понедельник месяца с июля"
            ),
            handler=handlers.monthly_weekday_from,
            expected_data=ReminderCreateData(
                reminder_text="Первый понедельник месяца с июля",
                schedule_type="monthly_weekday",
                start_at=datetime(
                    2099,
                    7,
                    6,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                month_week_number=1,
                day_of_week="MON",
            ),
        ),
        CreateCommandCase(
            command_text="/monthly_day 11 12:12 Оплатить интернет",
            handler=handlers.monthly_day,
            expected_data=ReminderCreateData(
                reminder_text="Оплатить интернет",
                schedule_type="monthly_day",
                start_at=datetime(
                    2090,
                    1,
                    1,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                month_day=11,
            ),
        ),
        CreateCommandCase(
            command_text=(
                "/monthly_day_from 11 2099-07-01 12:12 Оплатить интернет с июля"
            ),
            handler=handlers.monthly_day_from,
            expected_data=ReminderCreateData(
                reminder_text="Оплатить интернет с июля",
                schedule_type="monthly_day",
                start_at=datetime(
                    2099,
                    7,
                    11,
                    12,
                    12,
                    tzinfo=ZoneInfo("Asia/Yekaterinburg"),
                ),
                timezone_name="Asia/Yekaterinburg",
                month_day=11,
            ),
        ),
    ],
)
def test_create_commands_build_expected_reminder_data(
    monkeypatch: pytest.MonkeyPatch,
    case: CreateCommandCase,
) -> None:
    captured_data: list[ReminderCreateData] = []
    message = FakeMessage(case.command_text)

    def fake_get_chat_timezone_name(chat_id: int) -> str:
        assert chat_id == 100
        return "Asia/Yekaterinburg"

    def fake_get_nearest_future_datetime_for_time(
        time_text: str,
        *,
        timezone: ZoneInfo,
    ) -> datetime:
        assert time_text == "12:12"
        assert timezone == ZoneInfo("Asia/Yekaterinburg")
        return datetime(2090, 1, 1, 12, 12, tzinfo=timezone)

    def fake_get_nearest_future_weekday_datetime(
        day_of_week: str,
        time_text: str,
        *,
        timezone: ZoneInfo,
    ) -> datetime:
        assert day_of_week == "SUN"
        assert time_text == "12:12"
        assert timezone == ZoneInfo("Asia/Yekaterinburg")
        return datetime(2090, 1, 1, 12, 12, tzinfo=timezone)

    def fake_get_nearest_monthly_weekday_datetime(
        *,
        month_week_number: int,
        day_of_week: str,
        time_text: str,
        timezone: ZoneInfo,
    ) -> datetime:
        assert month_week_number == 1
        assert day_of_week == "MON"
        assert time_text == "12:12"
        assert timezone == ZoneInfo("Asia/Yekaterinburg")
        return datetime(2090, 1, 1, 12, 12, tzinfo=timezone)

    def fake_get_nearest_monthly_day_datetime(
        *,
        month_day: int,
        time_text: str,
        timezone: ZoneInfo,
    ) -> datetime:
        assert month_day == 11
        assert time_text == "12:12"
        assert timezone == ZoneInfo("Asia/Yekaterinburg")
        return datetime(2090, 1, 1, 12, 12, tzinfo=timezone)

    async def fake_create_schedule_and_confirm(
        message: FakeMessage,
        bot: object,
        *,
        data: ReminderCreateData,
    ) -> None:
        captured_data.append(data)

    monkeypatch.setattr(
        handlers,
        "get_chat_timezone_name",
        fake_get_chat_timezone_name,
    )
    monkeypatch.setattr(
        handlers,
        "get_nearest_future_datetime_for_time",
        fake_get_nearest_future_datetime_for_time,
    )
    monkeypatch.setattr(
        handlers,
        "get_nearest_future_weekday_datetime",
        fake_get_nearest_future_weekday_datetime,
    )
    monkeypatch.setattr(
        handlers,
        "get_nearest_monthly_weekday_datetime",
        fake_get_nearest_monthly_weekday_datetime,
    )
    monkeypatch.setattr(
        handlers,
        "get_nearest_monthly_day_datetime",
        fake_get_nearest_monthly_day_datetime,
    )
    monkeypatch.setattr(
        handlers,
        "create_schedule_and_confirm",
        fake_create_schedule_and_confirm,
    )

    asyncio.run(case.handler(message, object()))

    assert captured_data == [case.expected_data]
    assert message.answers == []
