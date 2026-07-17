from datetime import datetime, timezone

import pytest

from app.config import APP_TIMEZONE_NAME
from app.constants import REMINDER_KIND_TEXT
from app.reminder_mapping import build_reminder_read_data
from app.reminder_models import ReminderReadData


def test_reminder_read_data_requires_delivery_tracking_start() -> None:
    required_fields = {
        "id": 42,
        "chat_id": 100,
        "reminder_text": "Test",
        "schedule_type": "once",
        "start_at": datetime(2099, 6, 10, 12, 12),
        "timezone_name": "UTC",
    }

    with pytest.raises(TypeError, match="delivery_tracking_started_at_utc"):
        ReminderReadData(**required_fields)


def test_build_reminder_read_data_maps_row_to_read_model() -> None:
    start_at = datetime(2099, 6, 10, 12, 12)

    reminder = {
        "id": 42,
        "chat_id": 100,
        "text": "Проверить релиз",
        "reminder_kind": REMINDER_KIND_TEXT,
        "schedule_type": "every_days",
        "start_at": start_at.isoformat(timespec="seconds"),
        "interval_days": 3,
        "interval_weeks": None,
        "day_of_week": None,
        "month_week_number": None,
        "month_day": None,
        "timezone": "Asia/Yekaterinburg",
        "delete_after_two_days": 1,
        "delivery_tracking_started_at_utc": "2026-07-01T05:00:00",
        "last_handled_scheduled_for_utc": "2026-07-02T10:00:00+05:00",
    }

    assert build_reminder_read_data(reminder) == ReminderReadData(
        id=42,
        chat_id=100,
        reminder_text="Проверить релиз",
        reminder_kind=REMINDER_KIND_TEXT,
        schedule_type="every_days",
        start_at=start_at,
        timezone_name="Asia/Yekaterinburg",
        delivery_tracking_started_at_utc=datetime(
            2026, 7, 1, 5, 0, tzinfo=timezone.utc
        ),
        last_handled_scheduled_for_utc=datetime(2026, 7, 2, 5, 0, tzinfo=timezone.utc),
        delete_after_two_days=True,
        interval_days=3,
    )


def test_build_reminder_read_data_uses_default_timezone_when_row_timezone_is_none() -> (
    None
):
    start_at = datetime(2099, 6, 10, 12, 12)

    reminder = {
        "id": 42,
        "chat_id": 100,
        "text": "Проверить релиз",
        "reminder_kind": None,
        "schedule_type": "once",
        "start_at": start_at.isoformat(timespec="seconds"),
        "interval_days": None,
        "interval_weeks": None,
        "day_of_week": None,
        "month_week_number": None,
        "month_day": None,
        "timezone": None,
        "delete_after_two_days": None,
        "delivery_tracking_started_at_utc": "2026-07-01T05:00:00+00:00",
        "last_handled_scheduled_for_utc": None,
    }

    assert build_reminder_read_data(reminder) == ReminderReadData(
        id=42,
        chat_id=100,
        reminder_text="Проверить релиз",
        reminder_kind=REMINDER_KIND_TEXT,
        schedule_type="once",
        start_at=start_at,
        timezone_name=APP_TIMEZONE_NAME,
        delivery_tracking_started_at_utc=datetime(
            2026, 7, 1, 5, 0, tzinfo=timezone.utc
        ),
        last_handled_scheduled_for_utc=None,
    )
