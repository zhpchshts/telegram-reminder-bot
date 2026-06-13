from datetime import datetime

import pytest
from fastapi import HTTPException

from app import api as api_module
from app.api import (
    app,
    delete_chat_reminder,
    get_chat_reminders,
    get_chat_timezone,
    health,
    update_chat_timezone,
)
from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderResponse,
)
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


def test_get_chat_timezone_returns_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_chat_ids: list[int] = []

    def fake_get_chat_timezone_name(chat_id: int) -> str:
        requested_chat_ids.append(chat_id)
        return "Asia/Yekaterinburg"

    monkeypatch.setattr(
        api_module,
        "get_chat_timezone_name",
        fake_get_chat_timezone_name,
    )

    result = get_chat_timezone(chat_id=100)

    assert requested_chat_ids == [100]
    assert result == ChatTimezoneResponse(
        chat_id=100,
        timezone_name="Asia/Yekaterinburg",
    )


def test_update_chat_timezone_returns_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        api_module,
        "set_chat_timezone_for_chat",
        fake_set_chat_timezone_for_chat,
    )

    result = update_chat_timezone(
        chat_id=100,
        request=ChatTimezoneUpdateRequest(timezone_name="Europe/Moscow"),
    )

    assert captured_calls == [
        {
            "chat_id": 100,
            "timezone_name": "Europe/Moscow",
        }
    ]
    assert result == ChatTimezoneResponse(
        chat_id=100,
        timezone_name="Europe/Moscow",
    )


def test_update_chat_timezone_rejects_invalid_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_set_chat_timezone_for_chat(
        *,
        chat_id: int,
        timezone_name: str,
    ) -> bool:
        assert chat_id == 100
        assert timezone_name == "Wrong/Timezone"
        return False

    monkeypatch.setattr(
        api_module,
        "set_chat_timezone_for_chat",
        fake_set_chat_timezone_for_chat,
    )

    with pytest.raises(HTTPException) as error:
        update_chat_timezone(
            chat_id=100,
            request=ChatTimezoneUpdateRequest(timezone_name="Wrong/Timezone"),
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Invalid timezone name."


def test_delete_chat_reminder_returns_response(
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
        api_module,
        "delete_active_reminder_for_chat",
        fake_delete_active_reminder_for_chat,
    )

    result = delete_chat_reminder(chat_id=100, reminder_id=42)

    assert captured_calls == [
        {
            "reminder_id": 42,
            "chat_id": 100,
        }
    ]
    assert result == DeleteReminderResponse(
        id=42,
        chat_id=100,
        deleted=True,
    )


def test_delete_chat_reminder_rejects_unknown_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_delete_active_reminder_for_chat(
        *,
        reminder_id: int,
        chat_id: int,
    ) -> bool:
        assert reminder_id == 42
        assert chat_id == 100
        return False

    monkeypatch.setattr(
        api_module,
        "delete_active_reminder_for_chat",
        fake_delete_active_reminder_for_chat,
    )

    with pytest.raises(HTTPException) as error:
        delete_chat_reminder(chat_id=100, reminder_id=42)

    assert error.value.status_code == 404
    assert error.value.detail == "Reminder not found."


def test_api_registers_initial_routes() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/health" in route_paths
    assert "/api/chats/{chat_id}/reminders" in route_paths
    assert "/api/chats/{chat_id}/timezone" in route_paths
    assert "/api/chats/{chat_id}/reminders/{reminder_id}" in route_paths
