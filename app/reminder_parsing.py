from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.constants import VALID_WEEKDAYS
from app.reminder_models import ReminderCreateData
from app.schedule_calculations import (
    get_first_weekday_datetime_on_or_after_date,
    get_monthly_day_datetime_on_or_after,
    get_monthly_weekday_datetime_on_or_after,
    get_nearest_future_datetime_for_time,
    get_nearest_future_weekday_datetime,
    get_nearest_monthly_day_datetime,
    get_nearest_monthly_weekday_datetime,
    parse_datetime,
)


@dataclass(frozen=True, slots=True)
class ReminderParseResult:
    data: ReminderCreateData
    reject_past_heading: str | None = None
    reject_past_show_candidate: bool = False


class ReminderParseError(ValueError):
    pass


def split_command_text(
    command_text: str | None,
    *,
    maxsplit: int,
    min_parts: int,
) -> list[str]:
    if not command_text:
        raise ReminderParseError("Не вижу текст команды.")

    parts = command_text.split(maxsplit=maxsplit)

    if len(parts) < min_parts:
        raise ReminderParseError("Не хватает данных.")

    return parts


def parse_min_int(
    value: str,
    *,
    min_value: int = 1,
    max_value: int | None = None,
    parse_error: str = "N должно быть целым числом.",
    range_error: str = "N должно быть больше или равно 1.",
) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ReminderParseError(parse_error) from error

    if result < min_value or (max_value is not None and result > max_value):
        raise ReminderParseError(range_error)

    return result


def normalize_weekday(day_of_week: str) -> str:
    normalized_day = day_of_week.upper()

    if normalized_day not in VALID_WEEKDAYS:
        raise ReminderParseError("Не понял день недели.")

    return normalized_day


def parse_remind_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    del now

    parts = split_command_text(
        command_text,
        maxsplit=3,
        min_parts=4,
    )
    timezone = ZoneInfo(timezone_name)

    try:
        start_at = parse_datetime(parts[1], parts[2], timezone)
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать дату и время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[3],
            schedule_type="once",
            start_at=start_at,
            timezone_name=timezone_name,
        ),
        reject_past_heading="Дата и время должны быть в будущем.",
    )


def parse_every_days_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    parts = split_command_text(
        command_text,
        maxsplit=3,
        min_parts=4,
    )
    interval_days = parse_min_int(parts[1])
    timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_nearest_future_datetime_for_time(
            parts[2],
            now=now,
            timezone=timezone,
        )
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[3],
            schedule_type="every_days",
            start_at=start_at,
            timezone_name=timezone_name,
            interval_days=interval_days,
        ),
    )


def parse_every_days_from_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    del now

    parts = split_command_text(
        command_text,
        maxsplit=4,
        min_parts=5,
    )
    interval_days = parse_min_int(parts[1])
    timezone = ZoneInfo(timezone_name)

    try:
        start_at = parse_datetime(parts[2], parts[3], timezone)
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать дату и время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[4],
            schedule_type="every_days",
            start_at=start_at,
            timezone_name=timezone_name,
            interval_days=interval_days,
        ),
        reject_past_heading="Дата и время старта должны быть в будущем.",
    )


def parse_every_week_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    parts = split_command_text(
        command_text,
        maxsplit=4,
        min_parts=5,
    )
    interval_weeks = parse_min_int(parts[1])
    day_of_week = normalize_weekday(parts[2])
    timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_nearest_future_weekday_datetime(
            day_of_week,
            parts[3],
            now=now,
            timezone=timezone,
        )
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[4],
            schedule_type="every_week",
            start_at=start_at,
            timezone_name=timezone_name,
            interval_weeks=interval_weeks,
            day_of_week=day_of_week,
        ),
    )


def parse_every_week_from_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    del now

    parts = split_command_text(
        command_text,
        maxsplit=5,
        min_parts=6,
    )
    interval_weeks = parse_min_int(parts[1])
    day_of_week = normalize_weekday(parts[2])
    timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_first_weekday_datetime_on_or_after_date(
            day_of_week=day_of_week,
            date_text=parts[3],
            time_text=parts[4],
            timezone=timezone,
        )
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать дату или время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[5],
            schedule_type="every_week",
            start_at=start_at,
            timezone_name=timezone_name,
            interval_weeks=interval_weeks,
            day_of_week=day_of_week,
        ),
        reject_past_heading="Дата и время первого срабатывания должны быть в будущем.",
        reject_past_show_candidate=True,
    )


def parse_monthly_weekday_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    parts = split_command_text(
        command_text,
        maxsplit=4,
        min_parts=5,
    )
    month_week_number = parse_min_int(
        parts[1],
        max_value=5,
        parse_error="N должно быть целым числом от 1 до 5.",
        range_error="N должно быть от 1 до 5.",
    )
    day_of_week = normalize_weekday(parts[2])
    timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_nearest_monthly_weekday_datetime(
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=parts[3],
            now=now,
            timezone=timezone,
        )
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[4],
            schedule_type="monthly_weekday",
            start_at=start_at,
            timezone_name=timezone_name,
            month_week_number=month_week_number,
            day_of_week=day_of_week,
        ),
    )


def parse_monthly_weekday_from_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    del now

    parts = split_command_text(
        command_text,
        maxsplit=5,
        min_parts=6,
    )
    month_week_number = parse_min_int(
        parts[1],
        max_value=5,
        parse_error="N должно быть целым числом от 1 до 5.",
        range_error="N должно быть от 1 до 5.",
    )
    day_of_week = normalize_weekday(parts[2])
    timezone = ZoneInfo(timezone_name)

    try:
        lower_bound = parse_datetime(parts[3], parts[4], timezone)
        start_at = get_monthly_weekday_datetime_on_or_after(
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=parts[4],
            lower_bound=lower_bound,
        )
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать дату или время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[5],
            schedule_type="monthly_weekday",
            start_at=start_at,
            timezone_name=timezone_name,
            month_week_number=month_week_number,
            day_of_week=day_of_week,
        ),
        reject_past_heading="Дата и время первого срабатывания должны быть в будущем.",
        reject_past_show_candidate=True,
    )


def parse_monthly_day_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    parts = split_command_text(
        command_text,
        maxsplit=3,
        min_parts=4,
    )
    month_day = parse_min_int(
        parts[1],
        min_value=1,
        max_value=31,
        parse_error="День месяца должен быть целым числом от 1 до 31.",
        range_error="День месяца должен быть от 1 до 31.",
    )
    timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_nearest_monthly_day_datetime(
            month_day=month_day,
            time_text=parts[2],
            now=now,
            timezone=timezone,
        )
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[3],
            schedule_type="monthly_day",
            start_at=start_at,
            timezone_name=timezone_name,
            month_day=month_day,
        ),
    )


def parse_monthly_day_from_command(
    command_text: str | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> ReminderParseResult:
    del now

    parts = split_command_text(
        command_text,
        maxsplit=4,
        min_parts=5,
    )
    month_day = parse_min_int(
        parts[1],
        min_value=1,
        max_value=31,
        parse_error="День месяца должен быть целым числом от 1 до 31.",
        range_error="День месяца должен быть от 1 до 31.",
    )
    timezone = ZoneInfo(timezone_name)

    try:
        lower_bound = parse_datetime(parts[2], parts[3], timezone)
        start_at = get_monthly_day_datetime_on_or_after(
            month_day=month_day,
            time_text=parts[3],
            lower_bound=lower_bound,
        )
    except ValueError as error:
        raise ReminderParseError("Не смог разобрать дату или время.") from error

    return ReminderParseResult(
        data=ReminderCreateData(
            reminder_text=parts[4],
            schedule_type="monthly_day",
            start_at=start_at,
            timezone_name=timezone_name,
            month_day=month_day,
        ),
        reject_past_heading="Дата и время первого срабатывания должны быть в будущем.",
        reject_past_show_candidate=True,
    )


def parse_delete_command(command_text: str | None) -> int:
    parts = split_command_text(
        command_text,
        maxsplit=1,
        min_parts=2,
    )

    try:
        return int(parts[1].strip())
    except ValueError as error:
        raise ReminderParseError("ID должен быть числом.") from error


def parse_timezone_command(command_text: str | None) -> str | None:
    if not command_text:
        raise ReminderParseError("Не вижу текст команды.")

    parts = command_text.split(maxsplit=1)

    if len(parts) == 1:
        return None

    return parts[1].strip()
