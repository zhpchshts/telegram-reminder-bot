from datetime import datetime

from app.schedule_calculations import (
    add_months,
    find_nth_weekday_in_month,
    get_first_weekday_datetime_on_or_after_date,
    get_month_day_range_for_week_number,
    get_monthly_weekday_datetime_on_or_after,
    parse_datetime,
    parse_time,
    get_nearest_future_datetime_for_time,
    get_nearest_future_weekday_datetime,
    get_nearest_monthly_weekday_datetime,
    get_monthly_day_datetime_on_or_after,
    get_nearest_monthly_day_datetime,
    get_yearly_datetime_on_or_after,
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


def test_get_nearest_future_datetime_for_time_same_day_future() -> None:
    result = get_nearest_future_datetime_for_time(
        "12:12",
        now=datetime(2026, 6, 8, 10, 0),
    )

    assert result == datetime(2026, 6, 8, 12, 12)


def test_get_nearest_future_datetime_for_time_next_day_when_time_passed() -> None:
    result = get_nearest_future_datetime_for_time(
        "12:12",
        now=datetime(2026, 6, 8, 13, 0),
    )

    assert result == datetime(2026, 6, 9, 12, 12)


def test_get_nearest_future_weekday_datetime_same_day_future() -> None:
    result = get_nearest_future_weekday_datetime(
        "MON",
        "12:12",
        now=datetime(2026, 6, 8, 10, 0),
    )

    assert result == datetime(2026, 6, 8, 12, 12)


def test_get_nearest_future_weekday_datetime_next_week_when_time_passed() -> None:
    result = get_nearest_future_weekday_datetime(
        "MON",
        "12:12",
        now=datetime(2026, 6, 8, 13, 0),
    )

    assert result == datetime(2026, 6, 15, 12, 12)


def test_get_nearest_future_weekday_datetime_next_weekday() -> None:
    result = get_nearest_future_weekday_datetime(
        "WED",
        "12:12",
        now=datetime(2026, 6, 8, 10, 0),
    )

    assert result == datetime(2026, 6, 10, 12, 12)


def test_get_nearest_monthly_weekday_datetime_current_month() -> None:
    result = get_nearest_monthly_weekday_datetime(
        month_week_number=1,
        day_of_week="MON",
        time_text="12:12",
        now=datetime(2026, 6, 1, 12, 0),
    )

    assert result == datetime(2026, 6, 1, 12, 12)


def test_get_nearest_monthly_weekday_datetime_next_month_when_current_passed() -> None:
    result = get_nearest_monthly_weekday_datetime(
        month_week_number=1,
        day_of_week="MON",
        time_text="12:12",
        now=datetime(2026, 6, 2, 12, 0),
    )

    assert result == datetime(2026, 7, 6, 12, 12)


def test_get_monthly_day_datetime_on_or_after_current_month() -> None:
    result = get_monthly_day_datetime_on_or_after(
        month_day=11,
        time_text="12:12",
        lower_bound=datetime(2026, 6, 1, 10, 0),
    )

    assert result == datetime(2026, 6, 11, 12, 12)


def test_get_monthly_day_datetime_on_or_after_next_month_when_day_passed() -> None:
    result = get_monthly_day_datetime_on_or_after(
        month_day=11,
        time_text="12:12",
        lower_bound=datetime(2026, 6, 12, 10, 0),
    )

    assert result == datetime(2026, 7, 11, 12, 12)


def test_get_monthly_day_datetime_on_or_after_skips_month_without_day() -> None:
    result = get_monthly_day_datetime_on_or_after(
        month_day=31,
        time_text="12:12",
        lower_bound=datetime(2026, 4, 1, 10, 0),
    )

    assert result == datetime(2026, 5, 31, 12, 12)


def test_get_nearest_monthly_day_datetime_current_month() -> None:
    result = get_nearest_monthly_day_datetime(
        month_day=11,
        time_text="12:12",
        now=datetime(2026, 6, 1, 10, 0),
    )

    assert result == datetime(2026, 6, 11, 12, 12)


def test_get_yearly_datetime_on_or_after_uses_selected_date_in_lower_bound_year() -> (
    None
):
    result = get_yearly_datetime_on_or_after(
        selected_start_at=datetime(2000, 11, 12, 9, 30),
        lower_bound=datetime(2026, 6, 29, 10, 0),
    )

    assert result == datetime(2026, 11, 12, 9, 30)


def test_get_yearly_datetime_on_or_after_moves_to_next_year_when_time_has_passed() -> (
    None
):
    result = get_yearly_datetime_on_or_after(
        selected_start_at=datetime(2000, 6, 29, 9, 30),
        lower_bound=datetime(2026, 6, 29, 10, 0),
    )

    assert result == datetime(2027, 6, 29, 9, 30)


def test_get_yearly_datetime_on_or_after_skips_non_leap_years() -> None:
    result = get_yearly_datetime_on_or_after(
        selected_start_at=datetime(2024, 2, 29, 9, 30),
        lower_bound=datetime(2025, 3, 1, 10, 0),
    )

    assert result == datetime(2028, 2, 29, 9, 30)
