import asyncio
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import handlers
from app.reminder_models import ReminderCreateData
from app.reminder_parsing import ReminderParseError, ReminderParseResult

CHAT_ID = 100
TIMEZONE_NAME = "Asia/Yekaterinburg"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
BOT = object()


@dataclass(frozen=True, slots=True)
class CreateCommandCase:
    handler_name: str
    parser_name: str
    command_text: str
    parse_result: ReminderParseResult


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=CHAT_ID)
        self.answers: list[tuple[str, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs))


def make_datetime(
    year: int,
    month: int,
    day: int,
    hour: int = 12,
    minute: int = 12,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TIMEZONE)


CREATE_COMMAND_CASES = [
    CreateCommandCase(
        handler_name="remind",
        parser_name="parse_remind_command",
        command_text="/remind 2099-06-10 12:12 Одноразово проверить релиз",
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Одноразово проверить релиз",
                schedule_type="once",
                start_at=make_datetime(2099, 6, 10),
                timezone_name=TIMEZONE_NAME,
            ),
            reject_past_heading="Дата и время должны быть в будущем.",
        ),
    ),
    CreateCommandCase(
        handler_name="every_days",
        parser_name="parse_every_days_command",
        command_text="/every_days 3 12:12 Каждые три дня",
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждые три дня",
                schedule_type="every_days",
                start_at=make_datetime(2099, 1, 1),
                timezone_name=TIMEZONE_NAME,
                interval_days=3,
            ),
        ),
    ),
    CreateCommandCase(
        handler_name="every_days_from",
        parser_name="parse_every_days_from_command",
        command_text=("/every_days_from 3 2099-06-10 12:12 Каждые три дня с 10 июня"),
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждые три дня с 10 июня",
                schedule_type="every_days",
                start_at=make_datetime(2099, 6, 10),
                timezone_name=TIMEZONE_NAME,
                interval_days=3,
            ),
            reject_past_heading="Дата и время старта должны быть в будущем.",
        ),
    ),
    CreateCommandCase(
        handler_name="every_week",
        parser_name="parse_every_week_command",
        command_text="/every_week 2 sun 12:12 Каждое второе воскресенье",
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждое второе воскресенье",
                schedule_type="every_week",
                start_at=make_datetime(2099, 1, 4),
                timezone_name=TIMEZONE_NAME,
                interval_weeks=2,
                day_of_week="SUN",
            ),
        ),
    ),
    CreateCommandCase(
        handler_name="every_week_from",
        parser_name="parse_every_week_from_command",
        command_text=(
            "/every_week_from 2 sun 2099-06-10 12:12 "
            "Каждое второе воскресенье с 10 июня"
        ),
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждое второе воскресенье с 10 июня",
                schedule_type="every_week",
                start_at=make_datetime(2099, 6, 14),
                timezone_name=TIMEZONE_NAME,
                interval_weeks=2,
                day_of_week="SUN",
            ),
            reject_past_heading=(
                "Дата и время первого срабатывания должны быть в будущем."
            ),
            reject_past_show_candidate=True,
        ),
    ),
    CreateCommandCase(
        handler_name="monthly_weekday",
        parser_name="parse_monthly_weekday_command",
        command_text="/monthly_weekday 1 mon 12:12 Первый понедельник месяца",
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Первый понедельник месяца",
                schedule_type="monthly_weekday",
                start_at=make_datetime(2099, 1, 5),
                timezone_name=TIMEZONE_NAME,
                day_of_week="MON",
                month_week_number=1,
            ),
        ),
    ),
    CreateCommandCase(
        handler_name="monthly_weekday_from",
        parser_name="parse_monthly_weekday_from_command",
        command_text=(
            "/monthly_weekday_from 1 mon 2099-07-01 12:12 "
            "Первый понедельник месяца с июля"
        ),
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Первый понедельник месяца с июля",
                schedule_type="monthly_weekday",
                start_at=make_datetime(2099, 7, 6),
                timezone_name=TIMEZONE_NAME,
                day_of_week="MON",
                month_week_number=1,
            ),
            reject_past_heading=(
                "Дата и время первого срабатывания должны быть в будущем."
            ),
            reject_past_show_candidate=True,
        ),
    ),
    CreateCommandCase(
        handler_name="monthly_day",
        parser_name="parse_monthly_day_command",
        command_text="/monthly_day 11 12:12 Оплатить интернет",
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Оплатить интернет",
                schedule_type="monthly_day",
                start_at=make_datetime(2099, 1, 11),
                timezone_name=TIMEZONE_NAME,
                month_day=11,
            ),
        ),
    ),
    CreateCommandCase(
        handler_name="monthly_day_from",
        parser_name="parse_monthly_day_from_command",
        command_text="/monthly_day_from 11 2099-07-01 12:12 Оплатить интернет с июля",
        parse_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Оплатить интернет с июля",
                schedule_type="monthly_day",
                start_at=make_datetime(2099, 7, 11),
                timezone_name=TIMEZONE_NAME,
                month_day=11,
            ),
            reject_past_heading=(
                "Дата и время первого срабатывания должны быть в будущем."
            ),
            reject_past_show_candidate=True,
        ),
    ),
]


@pytest.fixture(autouse=True)
def patch_chat_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_chat_timezone_name(chat_id: int) -> str:
        assert chat_id == CHAT_ID
        return TIMEZONE_NAME

    monkeypatch.setattr(
        handlers,
        "get_chat_timezone_name",
        fake_get_chat_timezone_name,
    )


@pytest.mark.parametrize(
    "case",
    CREATE_COMMAND_CASES,
    ids=[case.handler_name for case in CREATE_COMMAND_CASES],
)
def test_create_commands_use_parser_result(
    monkeypatch: pytest.MonkeyPatch,
    case: CreateCommandCase,
) -> None:
    captured_data: list[ReminderCreateData] = []
    captured_reject_calls: list[dict[str, object]] = []
    message = FakeMessage(case.command_text)

    def fake_parser(
        command_text: str | None, timezone_name: str
    ) -> ReminderParseResult:
        assert command_text == case.command_text
        assert timezone_name == TIMEZONE_NAME
        return case.parse_result

    async def fake_reject_past_datetime(
        message_arg: FakeMessage,
        *,
        start_at: datetime,
        heading: str,
        timezone_name: str,
        show_candidate: bool = False,
    ) -> bool:
        assert message_arg is message
        captured_reject_calls.append(
            {
                "start_at": start_at,
                "heading": heading,
                "timezone_name": timezone_name,
                "show_candidate": show_candidate,
            }
        )
        return False

    async def fake_create_schedule_and_confirm(
        message_arg: FakeMessage,
        bot: object,
        *,
        data: ReminderCreateData,
    ) -> None:
        assert message_arg is message
        assert bot is BOT
        captured_data.append(data)

    monkeypatch.setattr(handlers, case.parser_name, fake_parser)
    monkeypatch.setattr(
        handlers,
        "reject_past_datetime",
        fake_reject_past_datetime,
    )
    monkeypatch.setattr(
        handlers,
        "create_schedule_and_confirm",
        fake_create_schedule_and_confirm,
    )

    handler = getattr(handlers, case.handler_name)

    asyncio.run(handler(message, bot=BOT))

    assert captured_data == [case.parse_result.data]
    assert message.answers == []

    if case.parse_result.reject_past_heading:
        assert captured_reject_calls == [
            {
                "start_at": case.parse_result.data.start_at,
                "heading": case.parse_result.reject_past_heading,
                "timezone_name": TIMEZONE_NAME,
                "show_candidate": case.parse_result.reject_past_show_candidate,
            }
        ]
    else:
        assert captured_reject_calls == []


def test_create_command_answers_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = FakeMessage("/every_days")

    def fake_parser(
        command_text: str | None, timezone_name: str
    ) -> ReminderParseResult:
        assert command_text == "/every_days"
        assert timezone_name == TIMEZONE_NAME
        raise ReminderParseError("Не хватает данных.")

    async def fake_create_schedule_and_confirm(
        message_arg: FakeMessage,
        bot: object,
        *,
        data: ReminderCreateData,
    ) -> None:
        raise AssertionError("Reminder must not be created after parse error.")

    monkeypatch.setattr(handlers, "parse_every_days_command", fake_parser)
    monkeypatch.setattr(
        handlers,
        "create_schedule_and_confirm",
        fake_create_schedule_and_confirm,
    )

    asyncio.run(handlers.every_days(message, bot=BOT))

    assert message.answers == [
        (
            "Не хватает данных.\n\n"
            "Формат:\n"
            "/every_days N ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/every_days 3 12:12 Каждые три дня",
            {},
        )
    ]
