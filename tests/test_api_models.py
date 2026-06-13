from datetime import datetime

from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderResponse,
    build_reminder_response,
)
from app.reminder_models import ReminderReadData


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
