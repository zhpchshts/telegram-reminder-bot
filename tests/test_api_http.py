from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import api as api_module
from app.api import app
from app.reminder_models import ReminderReadData
from app.api_auth import require_matching_chat_id


@pytest.fixture
def client() -> Iterator[TestClient]:
    def fake_require_matching_chat_id(chat_id: int) -> int:
        return chat_id

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[require_matching_chat_id] = fake_require_matching_chat_id

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_requires_tma_auth_without_dependency_override() -> None:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/chats/100/reminders")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


def test_get_chat_reminders_endpoint_returns_json(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_chat_ids: list[int] = []

    def fake_list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
        requested_chat_ids.append(chat_id)
        return [
            ReminderReadData(
                id=42,
                chat_id=100,
                reminder_text="Проверить релиз",
                schedule_type="every_days",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                interval_days=3,
            )
        ]

    monkeypatch.setattr(
        api_module,
        "list_active_reminders_for_chat",
        fake_list_active_reminders_for_chat,
    )

    response = client.get("/api/chats/100/reminders")

    assert response.status_code == 200
    assert requested_chat_ids == [100]
    assert response.json() == [
        {
            "id": 42,
            "chat_id": 100,
            "reminder_text": "Проверить релиз",
            "schedule_type": "every_days",
            "start_at": "2099-06-10T12:12:00",
            "timezone_name": "Asia/Yekaterinburg",
            "interval_days": 3,
            "interval_weeks": None,
            "day_of_week": None,
            "month_week_number": None,
            "month_day": None,
        }
    ]


def test_get_chat_timezone_endpoint_returns_json(
    client: TestClient,
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

    response = client.get("/api/chats/100/timezone")

    assert response.status_code == 200
    assert requested_chat_ids == [100]
    assert response.json() == {
        "chat_id": 100,
        "timezone_name": "Asia/Yekaterinburg",
    }


def test_update_chat_timezone_endpoint_returns_json(
    client: TestClient,
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

    response = client.put(
        "/api/chats/100/timezone",
        json={"timezone_name": "Europe/Moscow"},
    )

    assert response.status_code == 200
    assert captured_calls == [
        {
            "chat_id": 100,
            "timezone_name": "Europe/Moscow",
        }
    ]
    assert response.json() == {
        "chat_id": 100,
        "timezone_name": "Europe/Moscow",
    }


def test_update_chat_timezone_endpoint_rejects_invalid_timezone(
    client: TestClient,
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

    response = client.put(
        "/api/chats/100/timezone",
        json={"timezone_name": "Wrong/Timezone"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid timezone name."}


def test_delete_chat_reminder_endpoint_returns_json(
    client: TestClient,
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

    response = client.delete("/api/chats/100/reminders/42")

    assert response.status_code == 200
    assert captured_calls == [
        {
            "reminder_id": 42,
            "chat_id": 100,
        }
    ]
    assert response.json() == {
        "id": 42,
        "chat_id": 100,
        "deleted": True,
    }


def test_delete_chat_reminder_endpoint_rejects_unknown_reminder(
    client: TestClient,
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

    response = client.delete("/api/chats/100/reminders/42")

    assert response.status_code == 404
    assert response.json() == {"detail": "Reminder not found."}


def build_create_reminder_request(
    *,
    reminder_text: str = "Проверить релиз",
    schedule_type: str = "every_days",
    start_at: str = "2099-06-10T12:12:00",
    timezone_name: str = "Asia/Yekaterinburg",
    interval_days: int | None = 3,
) -> dict[str, object]:
    return {
        "reminder_text": reminder_text,
        "schedule_type": schedule_type,
        "start_at": start_at,
        "timezone_name": timezone_name,
        "interval_days": interval_days,
    }


def test_create_chat_reminder_endpoint_returns_json(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = object()
    app.state.bot = bot

    captured_calls: list[dict[str, object]] = []

    def fake_create_scheduled_reminder(
        *,
        bot,
        chat_id: int,
        data,
    ) -> int:
        captured_calls.append(
            {
                "bot": bot,
                "chat_id": chat_id,
                "data": data,
            }
        )
        return 42

    monkeypatch.setattr(
        api_module,
        "create_scheduled_reminder",
        fake_create_scheduled_reminder,
    )

    response = client.post(
        "/api/chats/100/reminders",
        json=build_create_reminder_request(),
    )

    assert response.status_code == 201
    assert len(captured_calls) == 1
    assert captured_calls[0]["bot"] is bot
    assert captured_calls[0]["chat_id"] == 100

    data = captured_calls[0]["data"]
    assert data.reminder_text == "Проверить релиз"
    assert data.schedule_type == "every_days"
    assert data.timezone_name == "Asia/Yekaterinburg"
    assert data.interval_days == 3

    response_json = response.json()
    assert response_json["id"] == 42
    assert response_json["chat_id"] == 100
    assert response_json["reminder_text"] == "Проверить релиз"
    assert response_json["schedule_type"] == "every_days"
    assert response_json["start_at"].startswith("2099-06-10T12:12:00")
    assert response_json["timezone_name"] == "Asia/Yekaterinburg"
    assert response_json["interval_days"] == 3
    assert response_json["interval_weeks"] is None
    assert response_json["day_of_week"] is None
    assert response_json["month_week_number"] is None
    assert response_json["month_day"] is None


def test_create_chat_reminder_endpoint_requires_configured_bot(
    client: TestClient,
) -> None:
    app.state.bot = None

    response = client.post(
        "/api/chats/100/reminders",
        json=build_create_reminder_request(),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Bot is not configured for API."}


def test_create_chat_reminder_endpoint_rejects_invalid_timezone(
    client: TestClient,
) -> None:
    app.state.bot = object()

    response = client.post(
        "/api/chats/100/reminders",
        json=build_create_reminder_request(
            timezone_name="Wrong/Timezone",
        ),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid timezone name."}


def test_create_chat_reminder_endpoint_rejects_start_at_in_past(
    client: TestClient,
) -> None:
    app.state.bot = object()

    response = client.post(
        "/api/chats/100/reminders",
        json=build_create_reminder_request(
            start_at="2000-01-01T00:00:00",
            timezone_name="UTC",
        ),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "start_at must be in the future."}


def test_create_chat_reminder_endpoint_returns_service_validation_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.state.bot = object()

    def fake_create_scheduled_reminder(
        *,
        bot,
        chat_id: int,
        data,
    ) -> int:
        raise ValueError("reminder_text is required.")

    monkeypatch.setattr(
        api_module,
        "create_scheduled_reminder",
        fake_create_scheduled_reminder,
    )

    response = client.post(
        "/api/chats/100/reminders",
        json=build_create_reminder_request(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "reminder_text is required."}
