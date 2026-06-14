from datetime import datetime

from app.formatting import (
    format_datetime_ru,
    format_period_line,
    format_reminder_read_data_for_list,
)
from app.reminder_models import ReminderReadData


def test_format_datetime_ru() -> None:
    result = format_datetime_ru(datetime(2026, 6, 8, 12, 12))

    assert result == "08 июня в 12:12"


def test_format_period_line_once() -> None:
    result = format_period_line(schedule_type="once")

    assert result == "один раз"


def test_format_period_line_every_days() -> None:
    result = format_period_line(
        schedule_type="every_days",
        interval_days=3,
    )

    assert result == "каждые 3 дн."


def test_format_period_line_every_week() -> None:
    result = format_period_line(
        schedule_type="every_week",
        interval_weeks=2,
        day_of_week="SUN",
    )

    assert result == "каждые 2 нед. по воскресеньям"


def test_format_period_line_monthly_weekday() -> None:
    result = format_period_line(
        schedule_type="monthly_weekday",
        month_week_number=1,
        day_of_week="MON",
    )

    assert result == "каждый 1-й понедельник месяца"


def test_format_period_line_monthly_day() -> None:
    result = format_period_line(
        schedule_type="monthly_day",
        month_day=11,
    )

    assert result == "каждый месяц 11 числа"


def test_format_period_line_yearly_date() -> None:
    result = format_period_line(
        schedule_type="yearly_date",
        start_at=datetime(2026, 8, 14, 9, 0),
    )

    assert result == "каждый год 14 августа"


def test_format_reminder_read_data_for_list_every_days() -> None:
    reminder = ReminderReadData(
        id=11,
        chat_id=100,
        reminder_text="Тест every days",
        schedule_type="every_days",
        start_at=datetime(2026, 6, 8, 12, 12),
        timezone_name="Asia/Yekaterinburg",
        interval_days=3,
    )

    result = format_reminder_read_data_for_list(
        reminder,
        "Следующее срабатывание: 11 июня в 12:12",
    )

    assert result == (
        "<b>Тест every days</b>\n"
        "ID: `11`\n"
        "Период: каждые 3 дн.\n"
        "Первое срабатывание: 08 июня в 12:12\n"
        "Следующее срабатывание: 11 июня в 12:12\n"
        "Таймзона: `Asia/Yekaterinburg`"
    )


def test_format_reminder_read_data_for_list_yearly_date() -> None:
    reminder = ReminderReadData(
        id=12,
        chat_id=100,
        reminder_text="Поздравить с днём рождения",
        schedule_type="yearly_date",
        start_at=datetime(2026, 8, 14, 9, 0),
        timezone_name="Asia/Yekaterinburg",
    )

    result = format_reminder_read_data_for_list(
        reminder,
        "Следующее срабатывание: 14 августа в 09:00",
    )

    assert result == (
        "<b>Поздравить с днём рождения</b>\n"
        "ID: `12`\n"
        "Период: каждый год 14 августа\n"
        "Первое срабатывание: 14 августа в 09:00\n"
        "Следующее срабатывание: 14 августа в 09:00\n"
        "Таймзона: `Asia/Yekaterinburg`"
    )
