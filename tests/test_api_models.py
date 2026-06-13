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
    TmaContextResponse,
    build_tma_context_response,
    ReminderFormOptionsResponse,
    ReminderScheduleTypeOption,
    WeekdayOption,
    build_reminder_form_options_response,
    TmaBootstrapResponse,
    build_tma_bootstrap_response,
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


def test_build_tma_context_response() -> None:
    result = build_tma_context_response(
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


def test_build_reminder_form_options_response() -> None:
    result = build_reminder_form_options_response()

    assert result == ReminderFormOptionsResponse(
        schedule_types=[
            ReminderScheduleTypeOption(
                value="once",
                label="Одноразовое напоминание",
                required_fields=[],
            ),
            ReminderScheduleTypeOption(
                value="every_days",
                label="Каждые N дней",
                required_fields=["interval_days"],
            ),
            ReminderScheduleTypeOption(
                value="every_week",
                label="Каждые N недель по дню недели",
                required_fields=["interval_weeks", "day_of_week"],
            ),
            ReminderScheduleTypeOption(
                value="monthly_weekday",
                label="Каждый месяц в N-й день недели",
                required_fields=["month_week_number", "day_of_week"],
            ),
            ReminderScheduleTypeOption(
                value="monthly_day",
                label="Каждый месяц в день месяца",
                required_fields=["month_day"],
            ),
        ],
        weekdays=[
            WeekdayOption(value="MONDAY", label="Понедельник"),
            WeekdayOption(value="TUESDAY", label="Вторник"),
            WeekdayOption(value="WEDNESDAY", label="Среда"),
            WeekdayOption(value="THURSDAY", label="Четверг"),
            WeekdayOption(value="FRIDAY", label="Пятница"),
            WeekdayOption(value="SATURDAY", label="Суббота"),
            WeekdayOption(value="SUNDAY", label="Воскресенье"),
        ],
        month_week_numbers=[1, 2, 3, 4, 5],
        month_days=list(range(1, 32)),
    )


def test_build_tma_bootstrap_response() -> None:
    start_at = datetime(2099, 6, 10, 12, 12)

    result = build_tma_bootstrap_response(
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
        active_reminders=[
            ReminderReadData(
                id=42,
                chat_id=100,
                reminder_text="Проверить релиз",
                schedule_type="every_days",
                start_at=start_at,
                timezone_name="Asia/Yekaterinburg",
                interval_days=3,
            )
        ],
    )

    assert result == TmaBootstrapResponse(
        context=TmaContextResponse(
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
        ),
        reminder_options=build_reminder_form_options_response(),
        active_reminders=[
            ReminderResponse(
                id=42,
                chat_id=100,
                reminder_text="Проверить релиз",
                schedule_type="every_days",
                start_at=start_at,
                timezone_name="Asia/Yekaterinburg",
                interval_days=3,
            )
        ],
    )
