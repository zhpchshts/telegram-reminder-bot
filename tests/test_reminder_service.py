from zoneinfo import ZoneInfoNotFoundError
from datetime import datetime, timezone
import pytest

from app import reminder_service as reminder_service_module
from app.constants import REMINDER_KIND_TEXT, REMINDER_KIND_WEATHER
from app.reminder_service import (
    ReminderSchedulingError,
    build_active_reminders_list_text_for_chat,
    build_created_reminder_text,
    create_scheduled_reminder,
    delete_active_reminder_for_chat,
    list_active_reminders_for_chat,
    set_chat_timezone_for_chat,
    update_active_reminder_for_chat,
    validate_reminder_create_data,
)
from app.reminder_models import ReminderCreateData, ReminderReadData

TEST_DELIVERY_TRACKING_STARTED_AT = datetime.fromisoformat("2026-07-01T00:00:00+00:00")


class FakeScheduler:
    def __init__(self, job: object | None) -> None:
        self.job = job
        self.get_job_ids: list[str] = []
        self.removed_job_ids: list[str] = []

    def get_job(self, job_id: str) -> object | None:
        self.get_job_ids.append(job_id)
        return self.job

    def remove_job(self, job_id: str) -> None:
        self.removed_job_ids.append(job_id)


def patch_reminder_lookup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reminder: object | None,
    deleted_ids: list[int],
) -> None:
    def fake_delete_active_reminder_for_chat_in_db(
        reminder_id: int,
        chat_id: int,
    ) -> bool:
        if reminder is None:
            return False
        deleted_ids.append(reminder_id)
        return True

    monkeypatch.setattr(
        reminder_service_module,
        "delete_active_reminder_for_chat_in_db",
        fake_delete_active_reminder_for_chat_in_db,
    )


def test_delete_active_reminder_for_chat_returns_false_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler(job=object())
    deleted_ids: list[int] = []

    monkeypatch.setattr(reminder_service_module, "scheduler", fake_scheduler)
    patch_reminder_lookup(monkeypatch, reminder=None, deleted_ids=deleted_ids)

    result = delete_active_reminder_for_chat(reminder_id=42, chat_id=100)

    assert result is False
    assert fake_scheduler.get_job_ids == []
    assert fake_scheduler.removed_job_ids == []
    assert deleted_ids == []


def test_delete_active_reminder_for_chat_removes_job_and_marks_deleted_when_job_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler(job=object())
    deleted_ids: list[int] = []

    monkeypatch.setattr(reminder_service_module, "scheduler", fake_scheduler)
    patch_reminder_lookup(monkeypatch, reminder=object(), deleted_ids=deleted_ids)

    result = delete_active_reminder_for_chat(reminder_id=42, chat_id=100)

    assert result is True
    assert fake_scheduler.get_job_ids == ["42"]
    assert fake_scheduler.removed_job_ids == ["42"]
    assert deleted_ids == [42]


def test_delete_active_reminder_for_chat_marks_deleted_when_job_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler(job=None)
    deleted_ids: list[int] = []

    monkeypatch.setattr(reminder_service_module, "scheduler", fake_scheduler)
    patch_reminder_lookup(monkeypatch, reminder=object(), deleted_ids=deleted_ids)

    result = delete_active_reminder_for_chat(reminder_id=42, chat_id=100)

    assert result is True
    assert fake_scheduler.get_job_ids == ["42"]
    assert fake_scheduler.removed_job_ids == []
    assert deleted_ids == [42]


def test_build_active_reminders_list_text_for_chat_returns_none_when_no_reminders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
        assert chat_id == 100
        return []

    def fake_format_next_run_line(
        reminder_id: int,
        timezone_name: str | None = None,
    ) -> str:
        raise AssertionError("format_next_run_line should not be called")

    def fake_format_reminder_read_data_for_list(
        reminder: ReminderReadData,
        next_run_line: str,
    ) -> str:
        raise AssertionError("format_reminder_read_data_for_list should not be called")

    monkeypatch.setattr(
        reminder_service_module,
        "list_active_reminders_for_chat",
        fake_list_active_reminders_for_chat,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_next_run_line",
        fake_format_next_run_line,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_reminder_read_data_for_list",
        fake_format_reminder_read_data_for_list,
    )

    result = build_active_reminders_list_text_for_chat(chat_id=100)

    assert result is None


def test_build_active_reminders_list_text_for_chat_returns_formatted_reminders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reminders = [
        ReminderReadData(
            id=1,
            chat_id=100,
            reminder_text="Первое",
            schedule_type="once",
            start_at=datetime(2099, 6, 10, 12, 12),
            timezone_name="Asia/Yekaterinburg",
            delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
        ),
        ReminderReadData(
            id=2,
            chat_id=100,
            reminder_text="Второе",
            schedule_type="every_days",
            start_at=datetime(2099, 6, 11, 12, 12),
            timezone_name="Europe/Moscow",
            delivery_tracking_started_at_utc=TEST_DELIVERY_TRACKING_STARTED_AT,
            interval_days=3,
        ),
    ]
    requested_chat_ids: list[int] = []
    next_run_calls: list[tuple[int, str | None]] = []
    formatted_reminders: list[tuple[int, str]] = []

    def fake_list_active_reminders_for_chat(chat_id: int) -> list[ReminderReadData]:
        requested_chat_ids.append(chat_id)
        return reminders

    def fake_format_next_run_line(
        reminder_id: int,
        timezone_name: str | None = None,
    ) -> str:
        next_run_calls.append((reminder_id, timezone_name))
        return f"next {reminder_id} / {timezone_name}"

    def fake_format_reminder_read_data_for_list(
        reminder: ReminderReadData,
        next_run_line: str,
    ) -> str:
        formatted_reminders.append((reminder.id, next_run_line))
        return f"reminder {reminder.id} / {next_run_line}"

    monkeypatch.setattr(
        reminder_service_module,
        "list_active_reminders_for_chat",
        fake_list_active_reminders_for_chat,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_next_run_line",
        fake_format_next_run_line,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_reminder_read_data_for_list",
        fake_format_reminder_read_data_for_list,
    )

    result = build_active_reminders_list_text_for_chat(chat_id=100)

    assert result == (
        "Активные напоминания в этом чате\n"
        "\n\n"
        "reminder 1 / next 1 / Asia/Yekaterinburg"
        "\n\n"
        "reminder 2 / next 2 / Europe/Moscow"
    )
    assert requested_chat_ids == [100]
    assert next_run_calls == [
        (1, "Asia/Yekaterinburg"),
        (2, "Europe/Moscow"),
    ]
    assert formatted_reminders == [
        (1, "next 1 / Asia/Yekaterinburg"),
        (2, "next 2 / Europe/Moscow"),
    ]


def test_create_scheduled_reminder_creates_db_record_and_schedules_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_calls: list[dict[str, object]] = []
    scheduled_calls: list[dict[str, object]] = []
    bot = object()
    start_at = datetime(2026, 6, 10, 12, 12)

    def fake_create_reminder_in_db(**kwargs: object) -> int:
        created_calls.append(kwargs)
        return 42

    def fake_schedule_reminder(**kwargs: object) -> None:
        scheduled_calls.append(kwargs)

    monkeypatch.setattr(
        reminder_service_module,
        "create_reminder_in_db",
        fake_create_reminder_in_db,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "schedule_reminder",
        fake_schedule_reminder,
    )

    result = create_scheduled_reminder(
        bot=bot,
        chat_id=100,
        data=ReminderCreateData(
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=start_at,
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        ),
    )

    assert result == 42
    assert created_calls == [
        {
            "chat_id": 100,
            "reminder_text": "Проверить релиз",
            "reminder_kind": REMINDER_KIND_TEXT,
            "delete_after_two_days": False,
            "requires_completion": False,
            "repeat_interval_minutes": None,
            "schedule_type": "every_days",
            "start_at": start_at,
            "interval_days": 3,
            "interval_weeks": None,
            "day_of_week": None,
            "month_week_number": None,
            "month_day": None,
            "timezone": "Asia/Yekaterinburg",
        }
    ]
    assert scheduled_calls == [
        {
            "bot": bot,
            "reminder_id": 42,
            "chat_id": 100,
            "reminder_text": "Проверить релиз",
            "reminder_kind": REMINDER_KIND_TEXT,
            "delete_after_two_days": False,
            "requires_completion": False,
            "repeat_interval_minutes": None,
            "schedule_type": "every_days",
            "start_at": start_at,
            "interval_days": 3,
            "interval_weeks": None,
            "day_of_week": None,
            "month_week_number": None,
            "month_day": None,
            "timezone_name": "Asia/Yekaterinburg",
        }
    ]


def test_set_chat_timezone_for_chat_returns_false_when_timezone_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_calls: list[dict[str, object]] = []

    def fake_zone_info(timezone_name: str) -> None:
        raise ZoneInfoNotFoundError(timezone_name)

    def fake_set_chat_timezone(**kwargs: object) -> None:
        set_calls.append(kwargs)

    monkeypatch.setattr(reminder_service_module, "ZoneInfo", fake_zone_info)
    monkeypatch.setattr(
        reminder_service_module,
        "set_chat_timezone",
        fake_set_chat_timezone,
    )

    result = set_chat_timezone_for_chat(
        chat_id=100,
        timezone_name="Invalid/Timezone",
    )

    assert result is False
    assert set_calls == []


def test_set_chat_timezone_for_chat_saves_timezone_when_timezone_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated_timezones: list[str] = []
    set_calls: list[dict[str, object]] = []

    def fake_zone_info(timezone_name: str) -> None:
        validated_timezones.append(timezone_name)

    def fake_set_chat_timezone(**kwargs: object) -> None:
        set_calls.append(kwargs)

    monkeypatch.setattr(reminder_service_module, "ZoneInfo", fake_zone_info)
    monkeypatch.setattr(
        reminder_service_module,
        "set_chat_timezone",
        fake_set_chat_timezone,
    )

    result = set_chat_timezone_for_chat(
        chat_id=100,
        timezone_name="Asia/Yekaterinburg",
    )

    assert result is True
    assert validated_timezones == ["Asia/Yekaterinburg"]
    assert set_calls == [
        {
            "chat_id": 100,
            "timezone": "Asia/Yekaterinburg",
        }
    ]


def test_build_created_reminder_text_for_once_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_at = datetime(2026, 6, 10, 12, 12)

    def fake_format_datetime_ru(value: datetime, timezone_name: str) -> str:
        assert value == start_at
        assert timezone_name == "Asia/Yekaterinburg"
        return "10.06.2026 12:12"

    def fake_format_next_run_line(
        reminder_id: int,
        timezone_name: str | None = None,
    ) -> str:
        assert reminder_id == 42
        assert timezone_name == "Asia/Yekaterinburg"
        return "Следующее срабатывание: 10.06.2026 12:12"

    monkeypatch.setattr(
        reminder_service_module,
        "format_datetime_ru",
        fake_format_datetime_ru,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_next_run_line",
        fake_format_next_run_line,
    )

    result = build_created_reminder_text(
        reminder_id=42,
        data=ReminderCreateData(
            reminder_text="Проверить релиз",
            schedule_type="once",
            start_at=start_at,
            timezone_name="Asia/Yekaterinburg",
        ),
    )

    assert result == (
        "Одноразовое напоминание создано.\n"
        "\n"
        "ID: 42\n"
        "Таймзона: Asia/Yekaterinburg\n"
        "Первое срабатывание: 10.06.2026 12:12\n"
        "Следующее срабатывание: 10.06.2026 12:12\n"
        "Текст: Проверить релиз"
    )


def test_build_created_reminder_text_for_repeating_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_at = datetime(2026, 6, 10, 12, 12)
    period_calls: list[dict[str, object]] = []

    def fake_format_period_line(**kwargs: object) -> str:
        period_calls.append(kwargs)
        return "каждые 3 дня"

    def fake_format_datetime_ru(value: datetime, timezone_name: str) -> str:
        assert value == start_at
        assert timezone_name == "Asia/Yekaterinburg"
        return "10.06.2026 12:12"

    def fake_format_next_run_line(
        reminder_id: int,
        timezone_name: str | None = None,
    ) -> str:
        assert reminder_id == 42
        assert timezone_name == "Asia/Yekaterinburg"
        return "Следующее срабатывание: 13.06.2026 12:12"

    monkeypatch.setattr(
        reminder_service_module,
        "format_period_line",
        fake_format_period_line,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_datetime_ru",
        fake_format_datetime_ru,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_next_run_line",
        fake_format_next_run_line,
    )

    result = build_created_reminder_text(
        reminder_id=42,
        data=ReminderCreateData(
            reminder_text="Проверить релиз",
            schedule_type="every_days",
            start_at=start_at,
            timezone_name="Asia/Yekaterinburg",
            interval_days=3,
        ),
    )

    assert result == (
        "Повторяющееся напоминание создано.\n"
        "\n"
        "ID: 42\n"
        "Период: каждые 3 дня\n"
        "Таймзона: Asia/Yekaterinburg\n"
        "Первое срабатывание: 10.06.2026 12:12\n"
        "Следующее срабатывание: 13.06.2026 12:12\n"
        "Текст: Проверить релиз"
    )
    assert period_calls == [
        {
            "schedule_type": "every_days",
            "interval_days": 3,
            "interval_weeks": None,
            "day_of_week": None,
            "month_week_number": None,
            "month_day": None,
        }
    ]


def test_list_active_reminders_for_chat_returns_read_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_at = datetime(2099, 6, 10, 12, 12)
    requested_chat_ids: list[int] = []

    reminders = [
        {
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
            "delivery_tracking_started_at_utc": "2026-07-01T05:00:00+00:00",
            "last_handled_scheduled_for_utc": None,
        }
    ]

    def fake_get_active_reminders_for_chat(chat_id: int) -> list[dict[str, object]]:
        requested_chat_ids.append(chat_id)
        return reminders

    monkeypatch.setattr(
        reminder_service_module,
        "get_active_reminders_for_chat",
        fake_get_active_reminders_for_chat,
    )

    result = list_active_reminders_for_chat(chat_id=100)

    assert requested_chat_ids == [100]
    assert result == [
        ReminderReadData(
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
            last_handled_scheduled_for_utc=None,
            interval_days=3,
        )
    ]


@pytest.mark.parametrize(
    ("data", "error_text"),
    [
        (
            ReminderCreateData(
                reminder_text="",
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "reminder_text is required.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                reminder_kind="unknown",
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "reminder_kind is invalid.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                schedule_type="unknown",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "Unknown schedule_type.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                schedule_type="every_days",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "interval_days must be greater than or equal to 1.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                schedule_type="every_week",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                interval_weeks=2,
                day_of_week="XXX",
            ),
            "day_of_week is invalid.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                schedule_type="monthly_weekday",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                month_week_number=6,
                day_of_week="MON",
            ),
            "month_week_number must be between 1 and 5.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                schedule_type="monthly_day",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
                month_day=32,
            ),
            "month_day must be between 1 and 31.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить погоду",
                reminder_kind=REMINDER_KIND_WEATHER,
                requires_completion=True,
                repeat_interval_minutes=60,
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "Completion is supported only for text reminders.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                delete_after_two_days=True,
                requires_completion=True,
                repeat_interval_minutes=60,
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "Completion and automatic deletion cannot be enabled together.",
        ),
        (
            ReminderCreateData(
                reminder_text="Проверить релиз",
                requires_completion=True,
                repeat_interval_minutes=45,
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "repeat_interval_minutes is invalid.",
        ),
        (
            ReminderCreateData(
                reminder_text="x" * 3901,
                requires_completion=True,
                repeat_interval_minutes=60,
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
            "reminder_text is too long for a completion reminder.",
        ),
    ],
)
def test_validate_reminder_create_data_rejects_invalid_data(
    data: ReminderCreateData,
    error_text: str,
) -> None:
    with pytest.raises(ValueError, match=error_text):
        validate_reminder_create_data(data)


def test_completion_text_at_backend_limit_is_valid() -> None:
    validate_reminder_create_data(
        ReminderCreateData(
            reminder_text="x" * 3900,
            requires_completion=True,
            repeat_interval_minutes=60,
            schedule_type="once",
            start_at=datetime(2099, 6, 10, 12, 12),
            timezone_name="Asia/Yekaterinburg",
        )
    )


def test_create_scheduled_reminder_validates_data_before_db_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_reminder_in_db(**kwargs: object) -> int:
        raise AssertionError("Invalid reminder must not be saved to database.")

    def fake_schedule_reminder(**kwargs: object) -> None:
        raise AssertionError("Invalid reminder must not be scheduled.")

    monkeypatch.setattr(
        reminder_service_module,
        "create_reminder_in_db",
        fake_create_reminder_in_db,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "schedule_reminder",
        fake_schedule_reminder,
    )

    with pytest.raises(ValueError, match="Unknown schedule_type."):
        create_scheduled_reminder(
            bot=object(),
            chat_id=100,
            data=ReminderCreateData(
                reminder_text="Проверить релиз",
                schedule_type="unknown",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
        )


def test_update_reports_failure_when_database_changed_but_rescheduling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reminder = object()
    update_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        reminder_service_module,
        "get_active_reminder_for_chat",
        lambda **kwargs: reminder,
    )

    def fake_update_reminder_in_db(**kwargs: object) -> bool:
        update_calls.append(kwargs)
        return True

    def fake_schedule_reminder(**kwargs: object) -> None:
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(
        reminder_service_module,
        "update_reminder_in_db",
        fake_update_reminder_in_db,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "schedule_reminder",
        fake_schedule_reminder,
    )

    with pytest.raises(ReminderSchedulingError, match="rescheduling failed"):
        update_active_reminder_for_chat(
            bot=object(),
            reminder_id=42,
            chat_id=100,
            data=ReminderCreateData(
                reminder_text="Новый текст",
                schedule_type="once",
                start_at=datetime(2099, 6, 10, 12, 12),
                timezone_name="Asia/Yekaterinburg",
            ),
        )

    assert len(update_calls) == 1
