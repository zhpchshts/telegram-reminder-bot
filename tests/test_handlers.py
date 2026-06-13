import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app import handlers
from app.reminder_models import ReminderCreateData


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=100)
        self.answers: list[tuple[str, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs))


def test_every_days_from_uses_text_after_time(
    monkeypatch,
) -> None:
    captured_data: list[ReminderCreateData] = []
    message = FakeMessage(
        "/every_days_from 3 2099-06-10 12:12 Каждые три дня с 10 июня"
    )

    def fake_get_chat_timezone_name(chat_id: int) -> str:
        assert chat_id == 100
        return "Asia/Yekaterinburg"

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
        "create_schedule_and_confirm",
        fake_create_schedule_and_confirm,
    )

    asyncio.run(handlers.every_days_from(message, bot=object()))

    assert captured_data == [
        ReminderCreateData(
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
        )
    ]
    assert message.answers == []
