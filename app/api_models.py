from datetime import datetime

from pydantic import BaseModel

from app.reminder_models import ReminderReadData


class ReminderResponse(BaseModel):
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


def build_reminder_response(reminder: ReminderReadData) -> ReminderResponse:
    return ReminderResponse(
        id=reminder.id,
        chat_id=reminder.chat_id,
        reminder_text=reminder.reminder_text,
        schedule_type=reminder.schedule_type,
        start_at=reminder.start_at,
        timezone_name=reminder.timezone_name,
        interval_days=reminder.interval_days,
        interval_weeks=reminder.interval_weeks,
        day_of_week=reminder.day_of_week,
        month_week_number=reminder.month_week_number,
        month_day=reminder.month_day,
    )


class ChatTimezoneResponse(BaseModel):
    chat_id: int
    timezone_name: str


class ChatTimezoneUpdateRequest(BaseModel):
    timezone_name: str


class DeleteReminderResponse(BaseModel):
    id: int
    chat_id: int
    deleted: bool
