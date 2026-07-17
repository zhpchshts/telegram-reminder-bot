from dataclasses import dataclass
from datetime import datetime

from app.constants import REMINDER_KIND_TEXT


@dataclass(frozen=True, slots=True)
class ReminderCreateData:
    reminder_text: str
    schedule_type: str
    start_at: datetime
    timezone_name: str
    reminder_kind: str = REMINDER_KIND_TEXT
    delete_after_two_days: bool = False
    interval_days: int | None = None
    interval_weeks: int | None = None
    day_of_week: str | None = None
    month_week_number: int | None = None
    month_day: int | None = None


@dataclass(frozen=True, slots=True)
class ReminderReadData:
    id: int
    chat_id: int
    reminder_text: str
    schedule_type: str
    start_at: datetime
    timezone_name: str
    delivery_tracking_started_at_utc: datetime
    last_handled_scheduled_for_utc: datetime | None = None
    reminder_kind: str = REMINDER_KIND_TEXT
    delete_after_two_days: bool = False
    interval_days: int | None = None
    interval_weeks: int | None = None
    day_of_week: str | None = None
    month_week_number: int | None = None
    month_day: int | None = None
