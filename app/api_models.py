from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.reminder_models import ReminderCreateData, ReminderReadData


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


class ReminderCreateRequest(BaseModel):
    reminder_text: str
    schedule_type: str
    start_at: datetime
    timezone_name: str
    interval_days: int | None = None
    interval_weeks: int | None = None
    day_of_week: str | None = None
    month_week_number: int | None = None
    month_day: int | None = None


class ChatTimezoneResponse(BaseModel):
    chat_id: int
    timezone_name: str


class ChatTimezoneUpdateRequest(BaseModel):
    timezone_name: str


class DeleteReminderResponse(BaseModel):
    id: int
    chat_id: int
    deleted: bool


def normalize_start_at(
    start_at: datetime,
    timezone_name: str,
) -> datetime:
    timezone = ZoneInfo(timezone_name)

    if start_at.tzinfo is None:
        return start_at.replace(tzinfo=timezone)

    return start_at.astimezone(timezone)


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


def build_reminder_create_data(
    request: ReminderCreateRequest,
) -> ReminderCreateData:
    return ReminderCreateData(
        reminder_text=request.reminder_text,
        schedule_type=request.schedule_type,
        start_at=normalize_start_at(request.start_at, request.timezone_name),
        timezone_name=request.timezone_name,
        interval_days=request.interval_days,
        interval_weeks=request.interval_weeks,
        day_of_week=request.day_of_week,
        month_week_number=request.month_week_number,
        month_day=request.month_day,
    )


def build_created_reminder_response(
    *,
    reminder_id: int,
    chat_id: int,
    data: ReminderCreateData,
) -> ReminderResponse:
    return ReminderResponse(
        id=reminder_id,
        chat_id=chat_id,
        reminder_text=data.reminder_text,
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        timezone_name=data.timezone_name,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
    )
