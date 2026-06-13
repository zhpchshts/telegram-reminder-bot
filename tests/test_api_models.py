from datetime import datetime

from app.api_models import ReminderResponse, build_reminder_response
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
