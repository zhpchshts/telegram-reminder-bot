from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import api as api_module
from app.api import app
from app.reminder_models import ReminderReadData


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
