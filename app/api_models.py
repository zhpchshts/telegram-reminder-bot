from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.reminder_models import ReminderCreateData, ReminderReadData
from app.formatting import format_period_line


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


class ReminderPreviewResponse(BaseModel):
    reminder_text: str
    schedule_type: str
    start_at: datetime
    timezone_name: str
    is_repeating: bool
    period: str | None = None


class ChatTimezoneResponse(BaseModel):
    chat_id: int
    timezone_name: str


class ChatTimezoneUpdateRequest(BaseModel):
    timezone_name: str


class DeleteReminderResponse(BaseModel):
    id: int
    chat_id: int
    deleted: bool


class TmaContextResponse(BaseModel):
    auth_date: int
    user: dict[str, object] | None = None
    chat: dict[str, object]
    chat_id: int
    timezone_name: str
    chat_type: str | None = None
    start_param: str | None = None


class ReminderScheduleTypeOption(BaseModel):
    value: str
    label: str
    required_fields: list[str]


class WeekdayOption(BaseModel):
    value: str
    label: str


class ReminderFormOptionsResponse(BaseModel):
    schedule_types: list[ReminderScheduleTypeOption]
    weekdays: list[WeekdayOption]
    month_week_numbers: list[int]
    month_days: list[int]


class TmaBootstrapResponse(BaseModel):
    context: TmaContextResponse
    reminder_options: ReminderFormOptionsResponse
    active_reminders: list[ReminderResponse]


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


def build_reminder_preview_response(
    data: ReminderCreateData,
) -> ReminderPreviewResponse:
    period = None

    if data.schedule_type != "once":
        period = format_period_line(
            schedule_type=data.schedule_type,
            interval_days=data.interval_days,
            interval_weeks=data.interval_weeks,
            day_of_week=data.day_of_week,
            month_week_number=data.month_week_number,
            month_day=data.month_day,
        )

    return ReminderPreviewResponse(
        reminder_text=data.reminder_text,
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        timezone_name=data.timezone_name,
        is_repeating=data.schedule_type != "once",
        period=period,
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


def build_tma_context_response(
    *,
    auth_date: int,
    user: dict[str, object] | None,
    chat: dict[str, object],
    chat_id: int,
    timezone_name: str,
    chat_type: str | None,
    start_param: str | None,
) -> TmaContextResponse:
    return TmaContextResponse(
        auth_date=auth_date,
        user=user,
        chat=chat,
        chat_id=chat_id,
        timezone_name=timezone_name,
        chat_type=chat_type,
        start_param=start_param,
    )


def build_reminder_form_options_response() -> ReminderFormOptionsResponse:
    return ReminderFormOptionsResponse(
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


def build_tma_bootstrap_response(
    *,
    auth_date: int,
    user: dict[str, object] | None,
    chat: dict[str, object],
    chat_id: int,
    timezone_name: str,
    chat_type: str | None,
    start_param: str | None,
    active_reminders: list[ReminderReadData],
) -> TmaBootstrapResponse:
    return TmaBootstrapResponse(
        context=build_tma_context_response(
            auth_date=auth_date,
            user=user,
            chat=chat,
            chat_id=chat_id,
            timezone_name=timezone_name,
            chat_type=chat_type,
            start_param=start_param,
        ),
        reminder_options=build_reminder_form_options_response(),
        active_reminders=[
            build_reminder_response(reminder) for reminder in active_reminders
        ],
    )
