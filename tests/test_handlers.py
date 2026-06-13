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
    def __init__(
        self,
        text: str,
        *,
        chat_type: str = "private",
        chat_title: str | None = None,
    ) -> None:
        self.text = text
        self.chat = SimpleNamespace(
            id=CHAT_ID,
            type=chat_type,
            title=chat_title,
        )
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


def test_timezone_command_answers_current_timezone() -> None:
    message = FakeMessage("/timezone")

    asyncio.run(handlers.timezone_command(message))

    assert len(message.answers) == 1

    answer_text, kwargs = message.answers[0]

    assert "Текущая таймзона этого чата:" in answer_text
    assert TIMEZONE_NAME in answer_text
    assert "/timezone Asia/Yekaterinburg" in answer_text
    assert "link_preview_options" in kwargs


def test_timezone_command_updates_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_calls: list[dict[str, object]] = []

    def fake_set_chat_timezone_for_chat(
        *,
        chat_id: int,
        timezone_name: str,
    ) -> bool:
        captured_calls.append(
            {
                "chat_id": chat_id,
                "timezone_name": timezone_name,
            }
        )
        return True

    monkeypatch.setattr(
        handlers,
        "set_chat_timezone_for_chat",
        fake_set_chat_timezone_for_chat,
    )

    message = FakeMessage("/timezone Europe/Moscow")

    asyncio.run(handlers.timezone_command(message))

    assert captured_calls == [
        {
            "chat_id": CHAT_ID,
            "timezone_name": "Europe/Moscow",
        }
    ]
    assert message.answers == [
        (
            "Таймзона этого чата обновлена.\n\n"
            "Теперь новые напоминания будут создаваться в таймзоне: Europe/Moscow\n\n"
            "Уже созданные напоминания останутся в той таймзоне, "
            "которая была установлена на момент их создания.",
            {},
        )
    ]


def test_timezone_command_answers_invalid_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_set_chat_timezone_for_chat(
        *,
        chat_id: int,
        timezone_name: str,
    ) -> bool:
        assert chat_id == CHAT_ID
        assert timezone_name == "Wrong/Timezone"
        return False

    monkeypatch.setattr(
        handlers,
        "set_chat_timezone_for_chat",
        fake_set_chat_timezone_for_chat,
    )

    message = FakeMessage("/timezone Wrong/Timezone")

    asyncio.run(handlers.timezone_command(message))

    assert len(message.answers) == 1

    answer_text, kwargs = message.answers[0]

    assert answer_text.startswith("Не смог распознать таймзону.")
    assert "/timezone Asia/Yekaterinburg" in answer_text
    assert "link_preview_options" in kwargs


def test_app_command_answers_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(handlers, "TMA_DIRECT_URL", None)

    message = FakeMessage("/app")

    asyncio.run(handlers.app_command(message))

    assert message.answers == [
        (
            "Mini App пока не настроен.\n\n"
            "Администратору нужно задать переменную окружения TMA_DIRECT_URL.",
            {},
        )
    ]


def test_app_command_sends_direct_link_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[dict[str, object]] = []

    def fake_create_tma_launch_token(
        *,
        chat_id: int,
        chat_type: str,
        secret: str,
        chat_title: str | None = None,
    ) -> str:
        captured_calls.append(
            {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "chat_title": chat_title,
                "secret": secret,
            }
        )
        return "signed-token"

    monkeypatch.setattr(
        handlers,
        "TMA_DIRECT_URL",
        "https://t.me/ZhpchshtsReminderBot?startapp=",
    )
    monkeypatch.setattr(handlers, "BOT_TOKEN", "test-bot-token")
    monkeypatch.setattr(
        handlers,
        "create_tma_launch_token",
        fake_create_tma_launch_token,
    )

    message = FakeMessage(
        "/app",
        chat_type="supergroup",
        chat_title="Home",
    )

    asyncio.run(handlers.app_command(message))

    assert captured_calls == [
        {
            "chat_id": CHAT_ID,
            "chat_type": "supergroup",
            "chat_title": "Home",
            "secret": "test-bot-token",
        }
    ]
    assert len(message.answers) == 1

    answer_text, kwargs = message.answers[0]

    assert answer_text == "Открой интерфейс управления напоминаниями:"

    reply_markup = kwargs["reply_markup"]
    button = reply_markup.inline_keyboard[0][0]

    assert button.text == "Открыть Mini App"
    assert button.url == "https://t.me/ZhpchshtsReminderBot?startapp=signed-token"
    assert button.web_app is None


def test_delete_reminder_deletes_active_reminder_for_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[dict[str, int]] = []

    def fake_delete_active_reminder_for_chat(
        *,
        reminder_id: int,
        chat_id: int,
    ) -> bool:
        captured_calls.append(
            {
                "reminder_id": reminder_id,
                "chat_id": chat_id,
            }
        )
        return True

    monkeypatch.setattr(
        handlers,
        "delete_active_reminder_for_chat",
        fake_delete_active_reminder_for_chat,
    )

    message = FakeMessage("/delete 123")

    asyncio.run(handlers.delete_reminder(message))

    assert captured_calls == [
        {
            "reminder_id": 123,
            "chat_id": CHAT_ID,
        }
    ]
    assert message.answers == [("Напоминание #123 удалено.", {})]


def test_delete_reminder_answers_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_delete_active_reminder_for_chat(
        *,
        reminder_id: int,
        chat_id: int,
    ) -> bool:
        assert reminder_id == 123
        assert chat_id == CHAT_ID
        return False

    monkeypatch.setattr(
        handlers,
        "delete_active_reminder_for_chat",
        fake_delete_active_reminder_for_chat,
    )

    message = FakeMessage("/delete 123")

    asyncio.run(handlers.delete_reminder(message))

    assert message.answers == [
        ("Не нашёл активное напоминание с ID 123 в этом чате.", {})
    ]


def test_delete_reminder_answers_missing_id() -> None:
    message = FakeMessage("/delete")

    asyncio.run(handlers.delete_reminder(message))

    assert message.answers == [
        (
            "Укажи ID напоминания.\n\nФормат:\n/delete ID\n\nПример:\n/delete 1",
            {},
        )
    ]


def test_delete_reminder_answers_non_integer_id() -> None:
    message = FakeMessage("/delete abc")

    asyncio.run(handlers.delete_reminder(message))

    assert message.answers == [
        (
            "ID должен быть числом.\nНапример: /delete 1",
            {},
        )
    ]
