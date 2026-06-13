from datetime import datetime

import pytest
from fastapi import HTTPException, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import api as api_module
from app.api import (
    app,
    configure_cors,
    create_chat_reminder,
    delete_chat_reminder,
    get_chat_reminders,
    get_chat_timezone,
    get_reminder_form_options,
    get_tma_context,
    health,
    update_chat_timezone,
    get_tma_bootstrap,
    create_tma_reminder,
    delete_tma_reminder,
    get_tma_reminders,
    get_tma_timezone,
    update_tma_timezone,
    preview_tma_reminder,
)
from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderCreateRequest,
    ReminderFormOptionsResponse,
    ReminderResponse,
    TmaContextResponse,
    TmaBootstrapResponse,
    ReminderPreviewResponse,
)
from app.reminder_models import ReminderCreateData, ReminderReadData

BOT = object()


class FakeTelegramInitData:
    auth_date = 1_700_000_000
    user = {
        "id": 123,
        "first_name": "Eugene",
    }
    chat = {
        "id": 100,
        "type": "group",
        "title": "Home",
    }
    chat_type = "group"
    start_param = "chat_100"


def test_health_returns_ok() -> None:
    assert health() == {"status": "ok"}


def test_configure_cors_skips_empty_origins() -> None:
    fastapi_app = FastAPI()

    configure_cors(fastapi_app, [])

    assert fastapi_app.user_middleware == []


def test_configure_cors_adds_cors_middleware() -> None:
    fastapi_app = FastAPI()

    configure_cors(
        fastapi_app,
        ["https://example.com", "https://tma.example.com"],
    )

    assert len(fastapi_app.user_middleware) == 1

    middleware = fastapi_app.user_middleware[0]

    assert middleware.cls is CORSMiddleware
    assert middleware.kwargs["allow_origins"] == [
        "https://example.com",
        "https://tma.example.com",
    ]
    assert middleware.kwargs["allow_credentials"] is True
    assert middleware.kwargs["allow_methods"] == ["*"]
    assert middleware.kwargs["allow_headers"] == ["*"]


def test_get_tma_context_returns_response(
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

    result = get_tma_context(
        init_data=FakeTelegramInitData(),
        chat_id=100,
    )

    assert requested_chat_ids == [100]
    assert result == TmaContextResponse(
        auth_date=1_700_000_000,
        user={
            "id": 123,
            "first_name": "Eugene",
        },
        chat={
            "id": 100,
            "type": "group",
            "title": "Home",
        },
        chat_id=100,
        timezone_name="Asia/Yekaterinburg",
        chat_type="group",
        start_param="chat_100",
    )


def test_get_reminder_form_options_returns_response() -> None:
    result = get_reminder_form_options()

    assert isinstance(result, ReminderFormOptionsResponse)
    assert [option.value for option in result.schedule_types] == [
        "once",
        "every_days",
        "every_week",
        "monthly_weekday",
        "monthly_day",
    ]
    assert [weekday.value for weekday in result.weekdays] == [
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    ]
    assert result.month_week_numbers == [1, 2, 3, 4, 5]
    assert result.month_days == list(range(1, 32))


def test_get_tma_bootstrap_returns_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_at = datetime(2099, 6, 10, 12, 12)
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
                start_at=start_at,
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

    result = get_tma_bootstrap(
        init_data=FakeTelegramInitData(),
        chat_id=100,
    )

    assert requested_timezone_chat_ids == [100]
    assert requested_reminder_chat_ids == [100]
    assert isinstance(result, TmaBootstrapResponse)
    assert result.context == TmaContextResponse(
        auth_date=1_700_000_000,
        user={
            "id": 123,
            "first_name": "Eugene",
        },
        chat={
            "id": 100,
            "type": "group",
            "title": "Home",
        },
        chat_id=100,
        timezone_name="Asia/Yekaterinburg",
        chat_type="group",
        start_param="chat_100",
    )
    assert [option.value for option in result.reminder_options.schedule_types] == [
        "once",
        "every_days",
        "every_week",
        "monthly_weekday",
        "monthly_day",
    ]
    assert result.active_reminders == [
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


def test_get_tma_reminders_returns_response_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_at = datetime(2099, 6, 10, 12, 12)
    requested_chat_ids: list[int] = []

    def fake_list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
        requested_chat_ids.append(chat_id)
        return [
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

    monkeypatch.setattr(
        api_module,
        "list_active_reminders_for_chat",
        fake_list_active_reminders_for_chat,
    )

    result = get_tma_reminders(chat_id=100)

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


def test_preview_tma_reminder_returns_normalized_preview() -> None:
    result = preview_tma_reminder(
        request=ReminderCreateRequest(
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=datetime(2099, 6, 10, 12, 12),
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        ),
        _chat_id=100,
    )

    assert result == ReminderPreviewResponse(
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=datetime.fromisoformat("2099-06-10T12:12:00+05:00"),
        timezone_name="Asia/Yekaterinburg",
        is_repeating=True,
        period="каждые 3 дн.",
    )


def test_create_tma_reminder_returns_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[dict[str, object]] = []

    def fake_create_scheduled_reminder(
        *,
        bot: object,
        chat_id: int,
        data: ReminderCreateData,
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

    result = create_tma_reminder(
        chat_id=100,
        request=ReminderCreateRequest(
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=datetime(2099, 6, 10, 12, 12),
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        ),
        bot=BOT,
    )

    expected_data = ReminderCreateData(
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=datetime.fromisoformat("2099-06-10T12:12:00+05:00"),
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )

    assert captured_calls == [
        {
            "bot": BOT,
            "chat_id": 100,
            "data": expected_data,
        }
    ]
    assert result == ReminderResponse(
        id=42,
        chat_id=100,
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=expected_data.start_at,
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )


def test_get_tma_timezone_returns_response(
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

    result = get_tma_timezone(chat_id=100)

    assert requested_chat_ids == [100]
    assert result == ChatTimezoneResponse(
        chat_id=100,
        timezone_name="Asia/Yekaterinburg",
    )


def test_update_tma_timezone_returns_response(
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

    result = update_tma_timezone(
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


def test_delete_tma_reminder_returns_response(
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

    result = delete_tma_reminder(chat_id=100, reminder_id=42)

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

    result = get_chat_reminders(authorized_chat_id=100)

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


def test_create_chat_reminder_returns_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[dict[str, object]] = []

    def fake_create_scheduled_reminder(
        *,
        bot: object,
        chat_id: int,
        data: ReminderCreateData,
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

    result = create_chat_reminder(
        authorized_chat_id=100,
        request=ReminderCreateRequest(
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=datetime(2099, 6, 10, 12, 12),
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        ),
        bot=BOT,
    )

    expected_data = ReminderCreateData(
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=datetime.fromisoformat("2099-06-10T12:12:00+05:00"),
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )

    assert captured_calls == [
        {
            "bot": BOT,
            "chat_id": 100,
            "data": expected_data,
        }
    ]
    assert result == ReminderResponse(
        id=42,
        chat_id=100,
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=expected_data.start_at,
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )


def test_create_chat_reminder_rejects_invalid_timezone() -> None:
    with pytest.raises(HTTPException) as error:
        create_chat_reminder(
            authorized_chat_id=100,
            request=ReminderCreateRequest(
                reminder_text="Проверить релиз",
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Wrong/Timezone",
            ),
            bot=BOT,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Invalid timezone name."


def test_create_chat_reminder_rejects_past_start_at() -> None:
    with pytest.raises(HTTPException) as error:
        create_chat_reminder(
            authorized_chat_id=100,
            request=ReminderCreateRequest(
                reminder_text="Проверить релиз",
                schedule_type="once",
                start_at=datetime(2000, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            bot=BOT,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "start_at must be in the future."


def test_create_chat_reminder_rejects_invalid_schedule_data() -> None:
    with pytest.raises(HTTPException) as error:
        create_chat_reminder(
            authorized_chat_id=100,
            request=ReminderCreateRequest(
                reminder_text="Проверить релиз",
                schedule_type="every_days",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            bot=BOT,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "interval_days must be greater than or equal to 1."


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

    result = get_chat_timezone(authorized_chat_id=100)

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
        authorized_chat_id=100,
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
            authorized_chat_id=100,
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

    result = delete_chat_reminder(authorized_chat_id=100, reminder_id=42)

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
        delete_chat_reminder(authorized_chat_id=100, reminder_id=42)

    assert error.value.status_code == 404
    assert error.value.detail == "Reminder not found."


def test_api_registers_initial_routes() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/health" in route_paths
    assert "/api/chats/{chat_id}/reminders" in route_paths
    assert "/api/chats/{chat_id}/timezone" in route_paths
    assert "/api/chats/{chat_id}/reminders/{reminder_id}" in route_paths
    assert "/api/tma/context" in route_paths
    assert "/api/tma/reminder-options" in route_paths
    assert "/api/tma/bootstrap" in route_paths
    assert "/api/tma/reminders" in route_paths
    assert "/api/tma/timezone" in route_paths
    assert "/api/tma/reminders/{reminder_id}" in route_paths
    assert "/api/tma/reminder-preview" in route_paths
