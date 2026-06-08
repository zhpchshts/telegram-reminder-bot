from datetime import datetime

from app.schedule_calculations import (
    add_months,
    find_nth_weekday_in_month,
    get_first_weekday_datetime_on_or_after_date,
    get_month_day_range_for_week_number,
    get_monthly_weekday_datetime_on_or_after,
    parse_datetime,
    parse_time,
)


def test_parse_time() -> None:
    result = parse_time("12:12")

    assert result.hour == 12
    assert result.minute == 12


def test_parse_datetime() -> None:
    result = parse_datetime("2026-06-10", "12:12")

    assert result == datetime(2026, 6, 10, 12, 12)


def test_add_months_inside_same_year() -> None:
    assert add_months(2026, 6, 1) == (2026, 7)


def test_add_months_across_year_boundary() -> None:
    assert add_months(2026, 12, 1) == (2027, 1)


def test_get_month_day_range_for_week_number() -> None:
    assert get_month_day_range_for_week_number(1) == "1-7"
    assert get_month_day_range_for_week_number(2) == "8-14"
    assert get_month_day_range_for_week_number(5) == "29-31"


def test_find_first_monday_in_month() -> None:
    result = find_nth_weekday_in_month(
        year=2026,
        month=6,
        month_week_number=1,
        day_of_week="MON",
        time_text="12:12",
    )

    assert result == datetime(2026, 6, 1, 12, 12)


def test_find_fifth_monday_in_month_when_exists() -> None:
    result = find_nth_weekday_in_month(
        year=2026,
        month=6,
        month_week_number=5,
        day_of_week="MON",
        time_text="12:12",
    )

    assert result == datetime(2026, 6, 29, 12, 12)


def test_find_fifth_monday_in_month_when_not_exists() -> None:
    result = find_nth_weekday_in_month(
        year=2026,
        month=2,
        month_week_number=5,
        day_of_week="MON",
        time_text="12:12",
    )

    assert result is None


def test_get_first_weekday_datetime_on_or_after_same_day() -> None:
    result = get_first_weekday_datetime_on_or_after_date(
        day_of_week="MON",
        date_text="2026-06-08",
        time_text="12:12",
    )

    assert result == datetime(2026, 6, 8, 12, 12)


def test_get_first_weekday_datetime_on_or_after_shifted() -> None:
    result = get_first_weekday_datetime_on_or_after_date(
        day_of_week="MON",
        date_text="2026-06-09",
        time_text="12:12",
    )

    assert result == datetime(2026, 6, 15, 12, 12)


def test_get_monthly_weekday_datetime_on_or_after_current_month() -> None:
    result = get_monthly_weekday_datetime_on_or_after(
        month_week_number=1,
        day_of_week="MON",
        time_text="12:12",
        lower_bound=datetime(2026, 6, 1, 12, 0),
    )

    assert result == datetime(2026, 6, 1, 12, 12)


def test_get_monthly_weekday_datetime_on_or_after_next_month() -> None:
    result = get_monthly_weekday_datetime_on_or_after(
        month_week_number=1,
        day_of_week="MON",
        time_text="12:12",
        lower_bound=datetime(2026, 6, 2, 12, 0),
    )

    assert result == datetime(2026, 7, 6, 12, 12)