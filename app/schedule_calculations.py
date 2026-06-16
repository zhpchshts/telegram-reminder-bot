import calendar
from datetime import datetime, timedelta, tzinfo

from app.constants import VALID_WEEKDAYS


def parse_time(time_text: str):
    return datetime.strptime(time_text, "%H:%M").time()


def parse_datetime(
    date_text: str,
    time_text: str,
    timezone: tzinfo | None = None,
) -> datetime:
    parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()

    return datetime.combine(
        parsed_date,
        parse_time(time_text),
        tzinfo=timezone,
    )


def get_nearest_future_datetime_for_time(
    time_text: str,
    now: datetime | None = None,
    timezone: tzinfo | None = None,
) -> datetime:
    current_time = now or datetime.now(timezone)

    candidate = datetime.combine(
        current_time.date(),
        parse_time(time_text),
        tzinfo=current_time.tzinfo,
    )

    return candidate if candidate > current_time else candidate + timedelta(days=1)


def get_nearest_future_weekday_datetime(
    day_of_week: str,
    time_text: str,
    now: datetime | None = None,
    timezone: tzinfo | None = None,
) -> datetime:
    current_time = now or datetime.now(timezone)
    target_weekday = VALID_WEEKDAYS[day_of_week]
    days_ahead = (target_weekday - current_time.weekday()) % 7

    candidate = datetime.combine(
        current_time.date() + timedelta(days=days_ahead),
        parse_time(time_text),
        tzinfo=current_time.tzinfo,
    )

    return candidate if candidate > current_time else candidate + timedelta(days=7)


def get_first_weekday_datetime_on_or_after_date(
    day_of_week: str,
    date_text: str,
    time_text: str,
    timezone: tzinfo | None = None,
) -> datetime:
    start_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    target_weekday = VALID_WEEKDAYS[day_of_week]
    days_ahead = (target_weekday - start_date.weekday()) % 7

    return datetime.combine(
        start_date + timedelta(days=days_ahead),
        parse_time(time_text),
        tzinfo=timezone,
    )


def get_month_day_range_for_week_number(month_week_number: int) -> str:
    start_day = (month_week_number - 1) * 7 + 1
    end_day = min(month_week_number * 7, 31)

    return f"{start_day}-{end_day}"


def add_months(year: int, month: int, months_to_add: int) -> tuple[int, int]:
    total_months = year * 12 + (month - 1) + months_to_add

    return total_months // 12, total_months % 12 + 1


def find_nth_weekday_in_month(
    year: int,
    month: int,
    month_week_number: int,
    day_of_week: str,
    time_text: str,
    timezone: tzinfo | None = None,
) -> datetime | None:
    target_weekday = VALID_WEEKDAYS[day_of_week]
    _, days_in_month = calendar.monthrange(year, month)

    occurrence_number = 0

    for day in range(1, days_in_month + 1):
        candidate_date = datetime(year, month, day)

        if candidate_date.weekday() != target_weekday:
            continue

        occurrence_number += 1

        if occurrence_number == month_week_number:
            return datetime.combine(
                candidate_date.date(),
                parse_time(time_text),
                tzinfo=timezone,
            )

    return None


def get_nearest_monthly_weekday_datetime(
    month_week_number: int,
    day_of_week: str,
    time_text: str,
    now: datetime | None = None,
    timezone: tzinfo | None = None,
) -> datetime:
    return get_monthly_weekday_datetime_on_or_after(
        month_week_number=month_week_number,
        day_of_week=day_of_week,
        time_text=time_text,
        lower_bound=now or datetime.now(timezone),
    )


def get_monthly_weekday_datetime_on_or_after(
    month_week_number: int,
    day_of_week: str,
    time_text: str,
    lower_bound: datetime,
) -> datetime:
    for months_to_add in range(60):
        year, month = add_months(
            year=lower_bound.year,
            month=lower_bound.month,
            months_to_add=months_to_add,
        )

        candidate = find_nth_weekday_in_month(
            year=year,
            month=month,
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=time_text,
            timezone=lower_bound.tzinfo,
        )

        if candidate and candidate >= lower_bound:
            return candidate

    raise RuntimeError("Could not find monthly weekday occurrence.")


def get_nearest_monthly_day_datetime(
    month_day: int,
    time_text: str,
    now: datetime | None = None,
    timezone: tzinfo | None = None,
) -> datetime:
    return get_monthly_day_datetime_on_or_after(
        month_day=month_day,
        time_text=time_text,
        lower_bound=now or datetime.now(timezone),
    )


def get_monthly_day_datetime_on_or_after(
    month_day: int,
    time_text: str,
    lower_bound: datetime,
) -> datetime:
    for months_to_add in range(60):
        year, month = add_months(
            year=lower_bound.year,
            month=lower_bound.month,
            months_to_add=months_to_add,
        )

        _, days_in_month = calendar.monthrange(year, month)

        if month_day > days_in_month:
            continue

        candidate = datetime.combine(
            datetime(year, month, month_day).date(),
            parse_time(time_text),
            tzinfo=lower_bound.tzinfo,
        )

        if candidate >= lower_bound:
            return candidate

    raise RuntimeError("Could not find monthly day occurrence.")


def get_schedule_start_at_on_or_after(
    *,
    schedule_type: str,
    start_at: datetime,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
    month_day: int | None = None,
) -> datetime:
    time_text = start_at.strftime("%H:%M")

    if schedule_type == "every_week":
        if day_of_week is None:
            return start_at

        return get_first_weekday_datetime_on_or_after_date(
            day_of_week=day_of_week,
            date_text=start_at.strftime("%Y-%m-%d"),
            time_text=time_text,
            timezone=start_at.tzinfo,
        )

    if schedule_type == "monthly_weekday":
        if month_week_number is None or day_of_week is None:
            return start_at

        return get_monthly_weekday_datetime_on_or_after(
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=time_text,
            lower_bound=start_at,
        )

    if schedule_type == "monthly_day":
        if month_day is None:
            return start_at

        return get_monthly_day_datetime_on_or_after(
            month_day=month_day,
            time_text=time_text,
            lower_bound=start_at,
        )

    return start_at


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value

    return value.astimezone().replace(tzinfo=None)
