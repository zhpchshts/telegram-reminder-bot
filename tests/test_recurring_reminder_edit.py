from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import api as api_module
from app.api import (
    build_validated_reminder_update_data,
    preview_tma_reminder,
)
from app.api_models import (
    ReminderCreateRequest,
    ReminderPreviewRequest,
)
from app.reminder_models import ReminderReadData


TIMEZONE_NAME = "Asia/Yekaterinburg"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
TEST_DELIVERY_TRACKING_STARTED_AT = datetime.fromisoformat("2026-07-01T00:00:00+00:00")


def build_current_reminder(
    *,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
) -> ReminderReadData:
    return ReminderReadData(
        id=42,
        chat_id=100,
        reminder_text="Проверить релиз",
        schedule_type=schedule_type,
        start_at=start_at,
        timezone_name=TIMEZONE_NAME,
        delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
        month_day=month_day,
    )


def test_repeating_every_days_edit_preserves_anchor_date_and_updates_time() -> None:
    current_reminder = build_current_reminder(
        schedule_type="every_days",
        start_at=datetime(2024, 1, 5, 10, 0, tzinfo=TIMEZONE),
        interval_days=7,
    )
    request = ReminderCreateRequest(
        reminder_text="Проверить релиз",
        schedule_type="every_days",
        start_at=datetime(2099, 12, 31, 9, 30),
        timezone_name=TIMEZONE_NAME,
        interval_days=7,
    )

    data = build_validated_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )

    assert data.start_at == datetime(2024, 1, 5, 9, 30, tzinfo=TIMEZONE)
    assert data.interval_days == 7


def test_repeating_weekly_edit_rebuilds_anchor_for_changed_weekday() -> None:
    current_reminder = build_current_reminder(
        schedule_type="every_week",
        start_at=datetime(2024, 1, 3, 10, 0, tzinfo=TIMEZONE),
        interval_weeks=2,
        day_of_week="WED",
    )
    request = ReminderCreateRequest(
        reminder_text="Проверить релиз",
        schedule_type="every_week",
        start_at=datetime(2099, 12, 31, 9, 30),
        timezone_name=TIMEZONE_NAME,
        interval_weeks=2,
        day_of_week="MON",
    )

    data = build_validated_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )

    assert data.start_at == datetime(2024, 1, 8, 9, 30, tzinfo=TIMEZONE)
    assert data.day_of_week == "MON"
    assert data.interval_weeks == 2


def test_repeating_monthly_day_edit_rebuilds_anchor_for_changed_day() -> None:
    current_reminder = build_current_reminder(
        schedule_type="monthly_day",
        start_at=datetime(2024, 1, 15, 10, 0, tzinfo=TIMEZONE),
        month_day=15,
    )
    request = ReminderCreateRequest(
        reminder_text="Проверить релиз",
        schedule_type="monthly_day",
        start_at=datetime(2099, 12, 31, 9, 30),
        timezone_name=TIMEZONE_NAME,
        month_day=10,
    )

    data = build_validated_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )

    assert data.start_at == datetime(2024, 2, 10, 9, 30, tzinfo=TIMEZONE)
    assert data.month_day == 10


def test_repeating_yearly_edit_uses_selected_month_and_day_without_reference_year() -> (
    None
):
    current_reminder = build_current_reminder(
        schedule_type="yearly_date",
        start_at=datetime(2023, 6, 1, 10, 0, tzinfo=TIMEZONE),
    )
    request = ReminderCreateRequest(
        reminder_text="Проверить релиз",
        schedule_type="yearly_date",
        start_at=datetime(2000, 2, 29, 9, 30),
        timezone_name=TIMEZONE_NAME,
    )

    data = build_validated_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )

    assert data.start_at == datetime(2024, 2, 29, 9, 30, tzinfo=TIMEZONE)


def test_repeating_edit_preview_returns_calculated_next_run_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_reminder = build_current_reminder(
        schedule_type="every_days",
        start_at=datetime(2024, 1, 5, 10, 0, tzinfo=TIMEZONE),
        interval_days=7,
    )
    expected_next_run_at = datetime(2026, 7, 3, 9, 30, tzinfo=TIMEZONE)

    monkeypatch.setattr(
        api_module,
        "get_active_reminder_for_chat",
        lambda *, reminder_id, chat_id: (
            current_reminder if reminder_id == 42 and chat_id == 100 else None
        ),
    )
    monkeypatch.setattr(
        api_module,
        "get_next_run_at_for_schedule",
        lambda **_kwargs: expected_next_run_at,
    )

    result = preview_tma_reminder(
        request=ReminderPreviewRequest(
            reminder_id=42,
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=datetime(2099, 12, 31, 9, 30),
            timezone_name=TIMEZONE_NAME,
            interval_days=7,
        ),
        _chat_id=100,
    )

    assert result.start_at == datetime(2024, 1, 5, 9, 30, tzinfo=TIMEZONE)
    assert result.next_run_at == expected_next_run_at


def test_repeating_monthly_weekday_edit_rebuilds_anchor_for_changed_weekday() -> None:
    current_reminder = build_current_reminder(
        schedule_type="monthly_weekday",
        start_at=datetime(2024, 1, 1, 10, 0, tzinfo=TIMEZONE),
        day_of_week="MON",
        month_week_number=1,
    )
    request = ReminderCreateRequest(
        reminder_text="Проверить релиз",
        schedule_type="monthly_weekday",
        start_at=datetime(2099, 12, 31, 9, 30),
        timezone_name=TIMEZONE_NAME,
        day_of_week="TUE",
        month_week_number=2,
    )

    data = build_validated_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )

    assert data.start_at == datetime(2024, 1, 9, 9, 30, tzinfo=TIMEZONE)
    assert data.day_of_week == "TUE"
    assert data.month_week_number == 2
