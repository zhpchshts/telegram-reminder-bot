from datetime import datetime

import pytest

from app import api as api_module
from app.api import app, get_chat_reminders, health
from app.api_models import ReminderResponse
from app.reminder_models import ReminderReadData


def test_health_returns_ok() -> None:
    assert health() == {"status": "ok"}


def test_get_chat_reminders_returns_response_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_at = datetime(2099, 6, 10, 12, 12)
    requested_chat_ids: list[int] = []

    reminders = [
        ReminderReadData(
            id=42,
            chat_id=100,
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=start_at,
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        )
    ]

    def fake_list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
        requested_chat_ids.append(chat_id)
        return reminders

    monkeypatch.setattr(
        api_module,
        "list_active_reminders_for_chat",
        fake_list_active_reminders_for_chat,
    )

    result = get_chat_reminders(chat_id=100)

    assert requested_chat_ids == [100]
    assert result == [
        ReminderResponse(
            id=42,
            chat_id=100,
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=start_at,
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        )
    ]


def test_api_registers_initial_routes() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/health" in route_paths
    assert "/api/chats/{chat_id}/reminders" in route_paths
