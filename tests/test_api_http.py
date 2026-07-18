from collections.abc import Iterator
from datetime import datetime
import json
from time import time
from urllib.parse import urlencode
import importlib.metadata

import tzdata


import pytest
from fastapi.testclient import TestClient

from app import api as api_module
from app import api_auth as api_auth_module
from app.api import app
from app.api_auth import TMA_INIT_DATA_HEADER, require_matching_chat_id
from app.constants import REMINDER_KIND_TEXT
from app.reminder_models import ReminderReadData
from app.reminder_service import ReminderSchedulingError
from app.tma_auth import calculate_init_data_hash
from app.tma_launch import create_tma_launch_token

BOT_TOKEN = "123456789:test-token"
TEST_DELIVERY_TRACKING_STARTED_AT = datetime.fromisoformat("2026-07-01T00:00:00+00:00")


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


def expected_reminder_options_response() -> dict[str, object]:
    return {
        "schedule_types": [
            {
                "value": "once",
                "label": "Одноразовое напоминание",
                "required_fields": [],
            },
            {
                "value": "yearly_date",
                "label": "Каждый год в дату",
                "required_fields": [],
            },
            {
                "value": "every_days",
                "label": "Каждые N дней",
                "required_fields": ["interval_days"],
            },
            {
                "value": "every_week",
                "label": "Каждые N недель по дню недели",
                "required_fields": ["interval_weeks", "day_of_week"],
            },
            {
                "value": "monthly_weekday",
                "label": "Каждый месяц в N-й день недели",
                "required_fields": ["month_week_number", "day_of_week"],
            },
            {
                "value": "monthly_day",
                "label": "Каждый месяц в день месяца",
                "required_fields": ["month_day"],
            },
        ],
        "weekdays": [
            {"value": "MON", "label": "Понедельник"},
            {"value": "TUE", "label": "Вторник"},
            {"value": "WED", "label": "Среда"},
            {"value": "THU", "label": "Четверг"},
            {"value": "FRI", "label": "Пятница"},
            {"value": "SAT", "label": "Суббота"},
            {"value": "SUN", "label": "Воскресенье"},
        ],
        "month_week_numbers": [1, 2, 3, 4, 5],
        "month_days": list(range(1, 32)),
        "completion_repeat_intervals": [
            {"value": 15, "label": "15 минут"},
            {"value": 30, "label": "30 минут"},
            {"value": 60, "label": "1 час"},
            {"value": 120, "label": "2 часа"},
            {"value": 240, "label": "4 часа"},
            {"value": 480, "label": "8 часов"},
            {"value": 720, "label": "12 часов"},
            {"value": 1440, "label": "24 часа"},
        ],
        "completion_reminder_text_max_length": 3900,
    }


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


def test_health_endpoint_returns_status_and_active_chats_count(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.count_active_chats", lambda: 0)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "active_chats_count": 0,
        "tzdata_package_version": importlib.metadata.version("tzdata"),
        "tzdata_iana_version": tzdata.IANA_VERSION,
    }


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


def test_tma_reminder_options_endpoint_returns_contract(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get(
        "/api/tma/reminder-options",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
    )

    assert response.status_code == 200
    assert response.json() == expected_reminder_options_response()


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
                reminder_kind=REMINDER_KIND_TEXT,
                delete_after_two_days=True,
                schedule_type="every_days",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
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
    assert response_json["reminder_options"] == expected_reminder_options_response()
    assert response_json["active_reminders"] == [
        {
            "id": 42,
            "chat_id": 100,
            "reminder_text": "Проверить релиз",
            "reminder_kind": REMINDER_KIND_TEXT,
            "delete_after_two_days": True,
            "requires_completion": False,
            "repeat_interval_minutes": None,
            "awaiting_completion": False,
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
        "reminder_kind": REMINDER_KIND_TEXT,
        "delete_after_two_days": False,
        "requires_completion": False,
        "repeat_interval_minutes": None,
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
                reminder_kind=REMINDER_KIND_TEXT,
                delete_after_two_days=True,
                schedule_type="every_days",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
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
            "reminder_kind": REMINDER_KIND_TEXT,
            "delete_after_two_days": True,
            "requires_completion": False,
            "repeat_interval_minutes": None,
            "awaiting_completion": False,
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
                reminder_kind=REMINDER_KIND_TEXT,
                schedule_type="every_days",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
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
            "reminder_kind": REMINDER_KIND_TEXT,
            "delete_after_two_days": False,
            "requires_completion": False,
            "repeat_interval_minutes": None,
            "awaiting_completion": False,
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
    reminder_kind: str = REMINDER_KIND_TEXT,
    delete_after_two_days: bool = False,
    schedule_type: str = "every_days",
    start_at: str = "2099-06-10T12:12:00",
    timezone_name: str = "Asia/Yekaterinburg",
    interval_days: int | None = 3,
) -> dict[str, object]:
    return {
        "reminder_text": reminder_text,
        "reminder_kind": reminder_kind,
        "delete_after_two_days": delete_after_two_days,
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
                reminder_kind=REMINDER_KIND_TEXT,
                delete_after_two_days=True,
                schedule_type="every_days",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
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
            "reminder_kind": REMINDER_KIND_TEXT,
            "delete_after_two_days": True,
            "requires_completion": False,
            "repeat_interval_minutes": None,
            "awaiting_completion": False,
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
        json=build_create_reminder_request(delete_after_two_days=True),
    )

    assert response.status_code == 201
    assert len(captured_calls) == 1
    assert captured_calls[0]["bot"] is bot
    assert captured_calls[0]["chat_id"] == 100

    data = captured_calls[0]["data"]
    assert data.reminder_text == "Проверить релиз"
    assert data.reminder_kind == REMINDER_KIND_TEXT
    assert data.delete_after_two_days is True
    assert data.schedule_type == "every_days"
    assert data.timezone_name == "Asia/Yekaterinburg"
    assert data.interval_days == 3

    response_json = response.json()

    assert response_json["id"] == 42
    assert response_json["chat_id"] == 100
    assert response_json["reminder_text"] == "Проверить релиз"
    assert response_json["reminder_kind"] == REMINDER_KIND_TEXT
    assert response_json["delete_after_two_days"] is True
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


def test_update_tma_reminder_endpoint_preserves_auto_delete_setting(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = object()
    app.state.bot = bot
    current_reminder = ReminderReadData(
        id=42,
        chat_id=100,
        reminder_text="Старый текст",
        reminder_kind=REMINDER_KIND_TEXT,
        delete_after_two_days=False,
        schedule_type="every_days",
        start_at=datetime(2099, 6, 10, 12, 12),
        timezone_name="Asia/Yekaterinburg",
        delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
        interval_days=3,
    )
    captured_data = []

    monkeypatch.setattr(
        api_module,
        "get_active_reminder_for_chat",
        lambda **kwargs: current_reminder,
    )

    def fake_update_active_reminder_for_chat(*, bot, reminder_id, chat_id, data):
        captured_data.append(data)
        return ReminderReadData(
            id=reminder_id,
            chat_id=chat_id,
            reminder_text=data.reminder_text,
            reminder_kind=data.reminder_kind,
            delete_after_two_days=data.delete_after_two_days,
            schedule_type=data.schedule_type,
            start_at=data.start_at,
            timezone_name=data.timezone_name,
            delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
            interval_days=data.interval_days,
        )

    monkeypatch.setattr(
        api_module,
        "update_active_reminder_for_chat",
        fake_update_active_reminder_for_chat,
    )

    response = authenticated_client.put(
        "/api/tma/reminders/42",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(delete_after_two_days=True),
    )

    assert response.status_code == 200
    assert len(captured_data) == 1
    assert captured_data[0].delete_after_two_days is True
    assert response.json()["delete_after_two_days"] is True


def test_update_tma_reminder_reports_rescheduling_failure(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.state.bot = object()
    current_reminder = ReminderReadData(
        id=42,
        chat_id=100,
        reminder_text="Старый текст",
        schedule_type="every_days",
        start_at=datetime(2099, 6, 10, 12, 12),
        timezone_name="Asia/Yekaterinburg",
        delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
        interval_days=3,
    )
    monkeypatch.setattr(
        api_module,
        "get_active_reminder_for_chat",
        lambda **kwargs: current_reminder,
    )

    def fail_update(**kwargs):
        raise ReminderSchedulingError(
            "Reminder was updated in the database, but rescheduling failed."
        )

    monkeypatch.setattr(
        api_module,
        "update_active_reminder_for_chat",
        fail_update,
    )

    response = authenticated_client.put(
        "/api/tma/reminders/42",
        headers={
            TMA_INIT_DATA_HEADER: build_signed_init_data_for_chat(chat_id=100),
        },
        json=build_create_reminder_request(),
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Reminder was updated, but rescheduling failed.",
    }


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


def test_tma_static_files_disable_cache() -> None:
    response = TestClient(app).get("/tma/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


def test_non_tma_response_keeps_default_cache_headers() -> None:
    response = TestClient(app).get("/not-tma")

    assert response.status_code == 404
    assert "cache-control" not in response.headers
    assert "pragma" not in response.headers
    assert "expires" not in response.headers
