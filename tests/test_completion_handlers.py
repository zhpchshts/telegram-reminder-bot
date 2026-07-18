import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import completion_handlers as handlers_module


class FakeCallback:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = SimpleNamespace(
            chat=SimpleNamespace(id=100),
            message_id=50,
            date=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        )
        self.from_user = SimpleNamespace(id=200, full_name="Участник")
        self.answers = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


def test_invalid_completion_callback_is_always_answered() -> None:
    callback = FakeCallback("completion_done:not-a-number")

    asyncio.run(handlers_module.completion_done_callback(callback, object()))

    assert callback.answers == ["Не удалось обработать кнопку."]


def test_internal_completion_error_is_always_answered(monkeypatch) -> None:
    async def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(handlers_module, "process_completion_callback", fail)
    callback = FakeCallback("completion_done:1")

    asyncio.run(handlers_module.completion_done_callback(callback, object()))

    assert callback.answers == ["Не удалось обработать кнопку."]


def test_successful_completion_callback_returns_service_text(monkeypatch) -> None:
    async def complete(*args, **kwargs):
        return "Выполнено."

    monkeypatch.setattr(handlers_module, "process_completion_callback", complete)
    callback = FakeCallback("completion_done:1")

    asyncio.run(handlers_module.completion_done_callback(callback, object()))

    assert callback.answers == ["Выполнено."]


@pytest.mark.parametrize(
    "service_text",
    [
        "Уже отмечено выполненным.",
        "Это срабатывание уже неактуально.",
        "Кнопка относится к другому чату.",
        "Напоминание больше не активно.",
    ],
)
def test_every_completion_result_is_answered(monkeypatch, service_text) -> None:
    async def complete(*args, **kwargs):
        return service_text

    monkeypatch.setattr(handlers_module, "process_completion_callback", complete)
    callback = FakeCallback("completion_done:1")

    asyncio.run(handlers_module.completion_done_callback(callback, object()))

    assert callback.answers == [service_text]
