from datetime import UTC, datetime

from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderCreateRequest,
    ReminderResponse,
    build_created_reminder_response,
    build_reminder_create_data,
    build_reminder_response,
    normalize_start_at,
)
from app.reminder_models import ReminderCreateData, ReminderReadData


def test_build_reminder_response() -> None:
    start_at = datetime(2099, 6, 10, 12, 12)

    result = build_reminder_response(
        ReminderReadData(
            id=42,
            chat_id=100,
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=start_at,
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        )
    )

    assert result == ReminderResponse(
        id=42,
        chat_id=100,
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=start_at,
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )


def test_normalize_start_at_adds_timezone_to_naive_datetime() -> None:
    result = normalize_start_at(
        datetime(2099, 6, 10, 12, 12),
        "Asia/Yekaterinburg",
    )

    assert result.tzinfo is not None
    assert result.isoformat() == "2099-06-10T12:12:00+05:00"


def test_normalize_start_at_converts_aware_datetime_to_timezone() -> None:
    result = normalize_start_at(
        datetime(2099, 6, 10, 7, 12, tzinfo=UTC),
        "Asia/Yekaterinburg",
    )

    assert result.isoformat() == "2099-06-10T12:12:00+05:00"


def test_build_reminder_create_data() -> None:
    result = build_reminder_create_data(
        ReminderCreateRequest(
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=datetime(2099, 6, 10, 12, 12),
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        )
    )

    assert result == ReminderCreateData(
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=datetime.fromisoformat("2099-06-10T12:12:00+05:00"),
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )


def test_build_created_reminder_response() -> None:
    start_at = datetime.fromisoformat("2099-06-10T12:12:00+05:00")

    result = build_created_reminder_response(
        reminder_id=42,
        chat_id=100,
        data=ReminderCreateData(
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=start_at,
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        ),
    )

    assert result == ReminderResponse(
        id=42,
        chat_id=100,
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=start_at,
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )


def test_chat_timezone_response() -> None:
    assert ChatTimezoneResponse(
        chat_id=100,
        timezone_name="Asia/Yekaterinburg",
    ).model_dump() == {
        "chat_id": 100,
        "timezone_name": "Asia/Yekaterinburg",
    }


def test_chat_timezone_update_request() -> None:
    assert ChatTimezoneUpdateRequest(
        timezone_name="Europe/Moscow",
    ).model_dump() == {
        "timezone_name": "Europe/Moscow",
    }


def test_delete_reminder_response() -> None:
    assert DeleteReminderResponse(
        id=42,
        chat_id=100,
        deleted=True,
    ).model_dump() == {
        "id": 42,
        "chat_id": 100,
        "deleted": True,
    }
