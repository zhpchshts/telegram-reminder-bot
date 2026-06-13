from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.reminder_models import ReminderCreateData
from app.reminder_parsing import (
    ReminderParseError,
    ReminderParseResult,
    parse_every_days_command,
    parse_every_days_from_command,
    parse_every_week_command,
    parse_every_week_from_command,
    parse_monthly_day_command,
    parse_monthly_day_from_command,
    parse_monthly_weekday_command,
    parse_monthly_weekday_from_command,
    parse_remind_command,
)

TIMEZONE_NAME = "Asia/Yekaterinburg"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
NOW = datetime(2099, 1, 1, 10, 0, tzinfo=TIMEZONE)

ParseFunction = Callable[
    [str | None, str],
    ReminderParseResult,
]


@dataclass(frozen=True, slots=True)
class ParseCase:
    name: str
    parser: ParseFunction
    command_text: str
    expected_result: ReminderParseResult


def make_datetime(
    year: int,
    month: int,
    day: int,
    hour: int = 12,
    minute: int = 12,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TIMEZONE)


PARSE_CASES = [
    ParseCase(
        name="remind",
        parser=parse_remind_command,
        command_text="/remind 2099-06-10 12:12 Одноразово проверить релиз",
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Одноразово проверить релиз",
                schedule_type="once",
                start_at=make_datetime(2099, 6, 10),
                timezone_name=TIMEZONE_NAME,
            ),
            reject_past_heading="Дата и время должны быть в будущем.",
        ),
    ),
    ParseCase(
        name="every_days",
        parser=parse_every_days_command,
        command_text="/every_days 3 12:12 Каждые три дня",
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждые три дня",
                schedule_type="every_days",
                start_at=make_datetime(2099, 1, 1),
                timezone_name=TIMEZONE_NAME,
                interval_days=3,
            ),
        ),
    ),
    ParseCase(
        name="every_days_from",
        parser=parse_every_days_from_command,
        command_text=("/every_days_from 3 2099-06-10 12:12 Каждые три дня с 10 июня"),
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждые три дня с 10 июня",
                schedule_type="every_days",
                start_at=make_datetime(2099, 6, 10),
                timezone_name=TIMEZONE_NAME,
                interval_days=3,
            ),
            reject_past_heading="Дата и время старта должны быть в будущем.",
        ),
    ),
    ParseCase(
        name="every_week",
        parser=parse_every_week_command,
        command_text="/every_week 2 sun 12:12 Каждое второе воскресенье",
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждое второе воскресенье",
                schedule_type="every_week",
                start_at=make_datetime(2099, 1, 4),
                timezone_name=TIMEZONE_NAME,
                interval_weeks=2,
                day_of_week="SUN",
            ),
        ),
    ),
    ParseCase(
        name="every_week_from",
        parser=parse_every_week_from_command,
        command_text=(
            "/every_week_from 2 sun 2099-06-10 12:12 "
            "Каждое второе воскресенье с 10 июня"
        ),
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Каждое второе воскресенье с 10 июня",
                schedule_type="every_week",
                start_at=make_datetime(2099, 6, 14),
                timezone_name=TIMEZONE_NAME,
                interval_weeks=2,
                day_of_week="SUN",
            ),
            reject_past_heading=(
                "Дата и время первого срабатывания должны быть в будущем."
            ),
            reject_past_show_candidate=True,
        ),
    ),
    ParseCase(
        name="monthly_weekday",
        parser=parse_monthly_weekday_command,
        command_text="/monthly_weekday 1 mon 12:12 Первый понедельник месяца",
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Первый понедельник месяца",
                schedule_type="monthly_weekday",
                start_at=make_datetime(2099, 1, 5),
                timezone_name=TIMEZONE_NAME,
                day_of_week="MON",
                month_week_number=1,
            ),
        ),
    ),
    ParseCase(
        name="monthly_weekday_from",
        parser=parse_monthly_weekday_from_command,
        command_text=(
            "/monthly_weekday_from 1 mon 2099-07-01 12:12 "
            "Первый понедельник месяца с июля"
        ),
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Первый понедельник месяца с июля",
                schedule_type="monthly_weekday",
                start_at=make_datetime(2099, 7, 6),
                timezone_name=TIMEZONE_NAME,
                day_of_week="MON",
                month_week_number=1,
            ),
            reject_past_heading=(
                "Дата и время первого срабатывания должны быть в будущем."
            ),
            reject_past_show_candidate=True,
        ),
    ),
    ParseCase(
        name="monthly_day",
        parser=parse_monthly_day_command,
        command_text="/monthly_day 11 12:12 Оплатить интернет",
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Оплатить интернет",
                schedule_type="monthly_day",
                start_at=make_datetime(2099, 1, 11),
                timezone_name=TIMEZONE_NAME,
                month_day=11,
            ),
        ),
    ),
    ParseCase(
        name="monthly_day_from",
        parser=parse_monthly_day_from_command,
        command_text="/monthly_day_from 11 2099-07-01 12:12 Оплатить интернет с июля",
        expected_result=ReminderParseResult(
            data=ReminderCreateData(
                reminder_text="Оплатить интернет с июля",
                schedule_type="monthly_day",
                start_at=make_datetime(2099, 7, 11),
                timezone_name=TIMEZONE_NAME,
                month_day=11,
            ),
            reject_past_heading=(
                "Дата и время первого срабатывания должны быть в будущем."
            ),
            reject_past_show_candidate=True,
        ),
    ),
]


@pytest.mark.parametrize("case", PARSE_CASES, ids=[case.name for case in PARSE_CASES])
def test_parse_create_commands(case: ParseCase) -> None:
    assert (
        case.parser(
            case.command_text,
            TIMEZONE_NAME,
            now=NOW,
        )
        == case.expected_result
    )


def test_split_empty_command_text() -> None:
    with pytest.raises(ReminderParseError, match="Не вижу текст команды."):
        parse_remind_command(None, TIMEZONE_NAME)


def test_split_command_text_with_missing_parts() -> None:
    with pytest.raises(ReminderParseError, match="Не хватает данных."):
        parse_remind_command("/remind 2099-06-10", TIMEZONE_NAME)


def test_parse_min_int_rejects_non_integer_value() -> None:
    with pytest.raises(ReminderParseError, match="N должно быть целым числом."):
        parse_every_days_command(
            "/every_days abc 12:12 Текст напоминания",
            TIMEZONE_NAME,
            now=NOW,
        )


def test_parse_min_int_rejects_value_out_of_range() -> None:
    with pytest.raises(ReminderParseError, match="N должно быть больше или равно 1."):
        parse_every_days_command(
            "/every_days 0 12:12 Текст напоминания",
            TIMEZONE_NAME,
            now=NOW,
        )


def test_normalize_weekday_rejects_unknown_value() -> None:
    with pytest.raises(ReminderParseError, match="Не понял день недели."):
        parse_every_week_command(
            "/every_week 1 XXX 12:12 Текст напоминания",
            TIMEZONE_NAME,
            now=NOW,
        )
