from collections.abc import Iterator
from datetime import datetime
import json
from time import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app import api as api_module
from app import api_auth as api_auth_module
from app.api import app
from app.api_auth import TMA_INIT_DATA_HEADER, require_matching_chat_id
from app.reminder_models import ReminderReadData
from app.tma_auth import calculate_init_data_hash
from app.tma_launch import create_tma_launch_token

BOT_TOKEN = "123456789:test-token"


def build_launch_token_for_chat(chat_id: int) -> str:
    return create_tma_launch_token(
        chat_id=chat_id,
        chat_type="group",
        chat_title="Home",
        secret=BOT_TOKEN,
        now=1_700_000_000,
        max_age_seconds=1_000_000_000,
    )


def build_signed_init_data_for_chat(chat_id: int) -> str:
    fields = {
        "auth_date": str(int(time())),
        "query_id": "AAEAAAE",
        "user": json.dumps(
            {
                "id": 123,
                "first_name": "Eugene",
            },
            separators=(",", ":"),
        ),
        "chat": json.dumps(
            {
                "id": chat_id,
                "type": "group",
                "title": "Home",
            },
            separators=(",", ":"),
        ),
        "chat_type": "group",
        "start_param": build_launch_token_for_chat(chat_id),
    }
    fields["hash"] = calculate_init_data_hash(
        fields,
        bot_token=BOT_TOKEN,
    )

    return urlencode(fields)


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


@pytest.fixture
def authenticated_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(api_auth_module, "BOT_TOKEN", BOT_TOKEN)

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

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


def test_tma_static_index_is_served(client: TestClient) -> None:
    response = client.get("/tma/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Напоминания" in response.text
    assert "./app.js" in response.text


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


def test_tma_context_endpoint_requires_tma_auth_without_dependency_override() -> None:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/tma/context")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


def test_reminder_options_endpoint_requires_tma_auth_without_dependency_override() -> (
    None
):
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/tma/reminder-options")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


def test_tma_bootstrap_endpoint_requires_tma_auth_without_dependency_override() -> None:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/tma/bootstrap")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


def test_tma_reminder_preview_endpoint_requires_tma_auth_without_dependency_override() -> (
    None
):
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/api/tma/reminder-preview",
                json=build_create_reminder_request(),
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


def test_tma_reminders_endpoint_requires_tma_auth_without_dependency_override() -> None:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/tma/reminders")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        (
            "post",
            "/api/tma/reminders",
            {
                "reminder_text": "Проверить релиз",
                "schedule_type": "every_days",
                "start_at": "2099-06-10T12:12:00",
                "timezone_name": "Asia/Yekaterinburg",
                "interval_days": 3,
            },
        ),
        (
            "put",
            "/api/tma/timezone",
            {
                "timezone_name": "Europe/Moscow",
            },
        ),
        (
            "put",
            "/api/tma/reminders/42",
            {
                "reminder_text": "Проверить релиз",
                "schedule_type": "every_days",
                "start_at": "2099-06-10T12:12:00",
                "timezone_name": "Asia/Yekaterinburg",
                "interval_days": 3,
            },
        ),
        (
            "delete",
            "/api/tma/reminders/42",
            None,
        ),
    ],
)
def test_tma_scoped_write_endpoints_require_tma_auth_without_dependency_override(
    method: str,
    path: str,
    json_body: dict[str, object] | None,
) -> None:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()

    request_kwargs = {}
    if json_body is not None:
        request_kwargs["json"] = json_body

    try:
        with TestClient(app) as test_client:
            response = getattr(test_client, method)(path, **request_kwargs)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


def test_tma_context_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.get(
        "/api/tma/context",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

    assert response.status_code == 200
    assert requested_chat_ids == [100]
    assert response.json() == {
        "auth_date": response.json()["auth_date"],
        "user": {
            "id": 123,
            "first_name": "Eugene",
        },
        "chat": {
            "id": 100,
            "type": "group",
            "title": "Home",
        },
        "chat_id": 100,
        "timezone_name": "Asia/Yekaterinburg",
        "chat_type": "group",
        "start_param": build_launch_token_for_chat(100),
    }


def test_tma_bootstrap_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_timezone_chat_ids: list[int] = []
    requested_reminder_chat_ids: list[int] = []

    def fake_get_chat_timezone_name(chat_id: int) -> str:
        requested_timezone_chat_ids.append(chat_id)
        return "Asia/Yekaterinburg"

    def fake_list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
        requested_reminder_chat_ids.append(chat_id)
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
        "get_chat_timezone_name",
        fake_get_chat_timezone_name,
    )
    monkeypatch.setattr(
        api_module,
        "list_active_reminders_for_chat",
        fake_list_active_reminders_for_chat,
    )

    response = authenticated_client.get(
        "/api/tma/bootstrap",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

    assert response.status_code == 200
    assert requested_timezone_chat_ids == [100]
    assert requested_reminder_chat_ids == [100]

    response_json = response.json()

    assert response_json["context"] == {
        "auth_date": response_json["context"]["auth_date"],
        "user": {
            "id": 123,
            "first_name": "Eugene",
        },
        "chat": {
            "id": 100,
            "type": "group",
            "title": "Home",
        },
        "chat_id": 100,
        "timezone_name": "Asia/Yekaterinburg",
        "chat_type": "group",
        "start_param": build_launch_token_for_chat(100),
    }
    assert [
        option["value"]
        for option in response_json["reminder_options"]["schedule_types"]
    ] == [
        "once",
        "yearly_date",
        "every_days",
        "every_week",
        "monthly_weekday",
        "monthly_day",
    ]
    assert response_json["active_reminders"] == [
        {
            "id": 42,
            "chat_id": 100,
            "reminder_text": "Проверить релиз",
            "schedule_type": "every_days",
            "start_at": "2099-06-10T12:12:00",
            "timezone_name": "Asia/Yekaterinburg",
            "is_repeating": True,
            "period": "каждые 3 дн.",
            "interval_days": 3,
            "interval_weeks": None,
            "day_of_week": None,
            "month_week_number": None,
            "month_day": None,
        }
    ]


def test_tma_reminder_preview_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/tma/reminder-preview",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "reminder_text": "Проверить релиз",
        "schedule_type": "every_days",
        "start_at": "2099-06-10T12:12:00+05:00",
        "timezone_name": "Asia/Yekaterinburg",
        "is_repeating": True,
        "period": "каждые 3 дн.",
    }


def test_tma_reminder_preview_endpoint_rejects_invalid_schedule_data(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/tma/reminder-preview",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(
            interval_days=None,
        ),
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "interval_days must be greater than or equal to 1.",
    }


def test_get_chat_reminders_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.get(
        "/api/chats/100/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

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
            "is_repeating": True,
            "period": "каждые 3 дн.",
            "interval_days": 3,
            "interval_weeks": None,
            "day_of_week": None,
            "month_week_number": None,
            "month_day": None,
        }
    ]


def test_chat_endpoint_rejects_tma_init_data_from_another_chat(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_chat_ids: list[int] = []

    def fake_list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
        requested_chat_ids.append(chat_id)
        return []

    monkeypatch.setattr(
        api_module,
        "list_active_reminders_for_chat",
        fake_list_active_reminders_for_chat,
    )

    response = authenticated_client.get(
        "/api/chats/100/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=200),
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Telegram init data chat_id does not match requested chat_id.",
    }
    assert requested_chat_ids == []


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
            "is_repeating": True,
            "period": "каждые 3 дн.",
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


def test_get_tma_reminders_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.get(
        "/api/tma/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

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
            "is_repeating": True,
            "period": "каждые 3 дн.",
            "interval_days": 3,
            "interval_weeks": None,
            "day_of_week": None,
            "month_week_number": None,
            "month_day": None,
        }
    ]


def test_create_tma_reminder_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.post(
        "/api/tma/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
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
    assert response_json["is_repeating"] is True
    assert response_json["period"] == "каждые 3 дн."
    assert response_json["interval_days"] == 3
    assert response_json["interval_weeks"] is None
    assert response_json["day_of_week"] is None
    assert response_json["month_week_number"] is None
    assert response_json["month_day"] is None


def test_get_tma_timezone_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.get(
        "/api/tma/timezone",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

    assert response.status_code == 200
    assert requested_chat_ids == [100]
    assert response.json() == {
        "chat_id": 100,
        "timezone_name": "Asia/Yekaterinburg",
    }


def test_update_tma_timezone_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.put(
        "/api/tma/timezone",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
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


def test_delete_tma_reminder_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.delete(
        "/api/tma/reminders/42",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

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


def test_create_tma_reminder_endpoint_requires_configured_bot(
    authenticated_client: TestClient,
) -> None:
    app.state.bot = None

    response = authenticated_client.post(
        "/api/tma/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Bot is not configured for API."}


def test_create_tma_reminder_endpoint_rejects_invalid_timezone(
    authenticated_client: TestClient,
) -> None:
    app.state.bot = object()

    response = authenticated_client.post(
        "/api/tma/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(
            timezone_name="Wrong/Timezone",
        ),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid timezone name."}


def test_create_tma_reminder_endpoint_rejects_start_at_in_past(
    authenticated_client: TestClient,
) -> None:
    app.state.bot = object()

    response = authenticated_client.post(
        "/api/tma/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(
            start_at="2000-01-01T00:00:00",
            timezone_name="UTC",
        ),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "start_at must be in the future."}


def test_create_tma_reminder_endpoint_returns_service_validation_error(
    authenticated_client: TestClient,
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

    response = authenticated_client.post(
        "/api/tma/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "reminder_text is required."}


def test_update_tma_timezone_endpoint_rejects_invalid_timezone(
    authenticated_client: TestClient,
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

    response = authenticated_client.put(
        "/api/tma/timezone",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json={"timezone_name": "Wrong/Timezone"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid timezone name."}


def test_delete_tma_reminder_endpoint_rejects_unknown_reminder(
    authenticated_client: TestClient,
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

    response = authenticated_client.delete(
        "/api/tma/reminders/42",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Reminder not found."}


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
    assert response_json["is_repeating"] is True
    assert response_json["period"] == "каждые 3 дн."
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


def test_create_chat_reminder_endpoint_accepts_valid_tma_init_data(
    authenticated_client: TestClient,
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

    response = authenticated_client.post(
        "/api/chats/100/reminders",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
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
    assert response_json["is_repeating"] is True
    assert response_json["period"] == "каждые 3 дн."
    assert response_json["interval_days"] == 3
    assert response_json["interval_weeks"] is None
    assert response_json["day_of_week"] is None
    assert response_json["month_week_number"] is None
    assert response_json["month_day"] is None
