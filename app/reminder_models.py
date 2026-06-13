from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReminderCreateData:
    reminder_text: str
    schedule_type: str
    start_at: datetime
    timezone_name: str
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
    interval_days: int | None = None
    interval_weeks: int | None = None
    day_of_week: str | None = None
    month_week_number: int | None = None
    month_day: int | None = None
