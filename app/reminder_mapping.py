from datetime import datetime, timezone
from typing import Any

from app.config import APP_TIMEZONE_NAME
from app.constants import REMINDER_KIND_TEXT
from app.reminder_models import ReminderReadData


def get_optional_int(value: object) -> int | None:
    if value is None:
        return None

    return int(value)


def get_optional_str(value: object) -> str | None:
    if value is None:
        return None

    return str(value)


def get_timezone_name_from_row(value: object) -> str:
    if value is None:
        return APP_TIMEZONE_NAME

    return str(value)


def get_reminder_kind_from_row(value: object) -> str:
    if value is None:
        return REMINDER_KIND_TEXT

    return str(value)


def get_bool_from_row(value: object) -> bool:
    if value is None:
        return False

    return bool(int(value))


def get_optional_row_value(reminder: Any, key: str) -> object:
    try:
        return reminder[key]
    except (IndexError, KeyError):
        return None


def parse_utc_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def parse_optional_utc_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    return parse_utc_datetime(value)


def build_reminder_read_data(reminder: Any) -> ReminderReadData:
    return ReminderReadData(
        id=int(reminder["id"]),
        chat_id=int(reminder["chat_id"]),
        reminder_text=str(reminder["text"]),
        schedule_type=str(reminder["schedule_type"]),
        start_at=datetime.fromisoformat(str(reminder["start_at"])),
        timezone_name=get_timezone_name_from_row(reminder["timezone"]),
        delivery_tracking_started_at_utc=parse_utc_datetime(
            reminder["delivery_tracking_started_at_utc"]
        ),
        last_handled_scheduled_for_utc=parse_optional_utc_datetime(
            reminder["last_handled_scheduled_for_utc"]
        ),
        reminder_kind=get_reminder_kind_from_row(reminder["reminder_kind"]),
        delete_after_two_days=get_bool_from_row(
            get_optional_row_value(reminder, "delete_after_two_days")
        ),
        interval_days=get_optional_int(reminder["interval_days"]),
        interval_weeks=get_optional_int(reminder["interval_weeks"]),
        day_of_week=get_optional_str(reminder["day_of_week"]),
        month_week_number=get_optional_int(reminder["month_week_number"]),
        month_day=get_optional_int(reminder["month_day"]),
    )
