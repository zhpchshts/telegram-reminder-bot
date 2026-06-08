import asyncio
import calendar
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = Path("reminders.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Check your .env file.")


dp = Dispatcher()
scheduler = AsyncIOScheduler()


MONTH_NAMES_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

VALID_WEEKDAYS = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}

APSCHEDULER_WEEKDAYS = {
    "MON": "mon",
    "TUE": "tue",
    "WED": "wed",
    "THU": "thu",
    "FRI": "fri",
    "SAT": "sat",
    "SUN": "sun",
}

WEEKDAY_NAMES_RU_PLURAL = {
    "MON": "понедельникам",
    "TUE": "вторникам",
    "WED": "средам",
    "THU": "четвергам",
    "FRI": "пятницам",
    "SAT": "субботам",
    "SUN": "воскресеньям",
}

WEEKDAY_NAMES_RU_SINGLE = {
    "MON": "понедельник",
    "TUE": "вторник",
    "WED": "среду",
    "THU": "четверг",
    "FRI": "пятницу",
    "SAT": "субботу",
    "SUN": "воскресенье",
}

ORDINAL_NAMES_RU = {
    1: "1-й",
    2: "2-й",
    3: "3-й",
    4: "4-й",
    5: "5-й",
}

REMINDER_COLUMNS = """
    id,
    chat_id,
    text,
    schedule_type,
    status,
    start_at,
    interval_days,
    interval_weeks,
    day_of_week,
    month_week_number
"""

SCHEMA_MIGRATIONS = {
    "interval_weeks": "interval_weeks INTEGER",
    "day_of_week": "day_of_week TEXT",
    "month_week_number": "month_week_number INTEGER",
}

WEEKDAY_HELP = "MON, TUE, WED, THU, FRI, SAT, SUN"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                start_at TEXT NOT NULL,
                interval_days INTEGER,
                interval_weeks INTEGER,
                day_of_week TEXT,
                month_week_number INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )

        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reminders)").fetchall()
        }

        for column_name, column_definition in SCHEMA_MIGRATIONS.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE reminders ADD COLUMN {column_definition}"
                )


def create_reminder_in_db(
    *,
    chat_id: int,
    reminder_text: str,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO reminders (
                chat_id,
                text,
                schedule_type,
                status,
                start_at,
                interval_days,
                interval_weeks,
                day_of_week,
                month_week_number,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                reminder_text,
                schedule_type,
                "active",
                start_at.isoformat(timespec="seconds"),
                interval_days,
                interval_weeks,
                day_of_week,
                month_week_number,
                now,
            ),
        )

        return int(cursor.lastrowid)


def fetch_active_reminders(
    where_sql: str = "",
    params: tuple[Any, ...] = (),
) -> list[sqlite3.Row]:
    query = f"""
        SELECT {REMINDER_COLUMNS}
        FROM reminders
        WHERE status = 'active'
        {where_sql}
        ORDER BY id ASC
    """

    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def get_active_reminder_from_db(reminder_id: int) -> sqlite3.Row | None:
    reminders = fetch_active_reminders("AND id = ?", (reminder_id,))
    return reminders[0] if reminders else None


def get_active_reminders_for_chat(chat_id: int) -> list[sqlite3.Row]:
    return fetch_active_reminders("AND chat_id = ?", (chat_id,))


def get_all_active_reminders() -> list[sqlite3.Row]:
    return fetch_active_reminders()


def set_reminder_status(reminder_id: int, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE reminders
            SET status = ?
            WHERE id = ?
            """,
            (status, reminder_id),
        )


def mark_reminder_as_sent(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "sent")


def mark_reminder_as_deleted(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "deleted")


def mark_reminder_as_missed(reminder_id: int) -> None:
    set_reminder_status(reminder_id, "missed")


def parse_time(time_text: str):
    return datetime.strptime(time_text, "%H:%M").time()


def parse_datetime(date_text: str, time_text: str) -> datetime:
    return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")


def get_nearest_future_datetime_for_time(time_text: str) -> datetime:
    now = datetime.now()
    candidate = datetime.combine(now.date(), parse_time(time_text))

    return candidate if candidate > now else candidate + timedelta(days=1)


def get_nearest_future_weekday_datetime(
    day_of_week: str,
    time_text: str,
) -> datetime:
    now = datetime.now()
    target_weekday = VALID_WEEKDAYS[day_of_week]
    days_ahead = (target_weekday - now.weekday()) % 7
    candidate = datetime.combine(
        now.date() + timedelta(days=days_ahead),
        parse_time(time_text),
    )

    return candidate if candidate > now else candidate + timedelta(days=7)


def get_first_weekday_datetime_on_or_after_date(
    day_of_week: str,
    date_text: str,
    time_text: str,
) -> datetime:
    start_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    target_weekday = VALID_WEEKDAYS[day_of_week]
    days_ahead = (target_weekday - start_date.weekday()) % 7

    return datetime.combine(
        start_date + timedelta(days=days_ahead),
        parse_time(time_text),
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
            return datetime.combine(candidate_date.date(), parse_time(time_text))

    return None


def get_nearest_monthly_weekday_datetime(
    month_week_number: int,
    day_of_week: str,
    time_text: str,
) -> datetime:
    return get_monthly_weekday_datetime_on_or_after(
        month_week_number=month_week_number,
        day_of_week=day_of_week,
        time_text=time_text,
        lower_bound=datetime.now(),
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
        )

        if candidate and candidate >= lower_bound:
            return candidate

    raise RuntimeError("Could not find monthly weekday occurrence.")


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value

    return value.astimezone().replace(tzinfo=None)


def format_datetime_ru(value: datetime) -> str:
    normalized_value = normalize_datetime(value)
    month_name = MONTH_NAMES_RU[normalized_value.month]

    return (
        f"{normalized_value.day:02d} "
        f"{month_name} в {normalized_value.strftime('%H:%M')}"
    )


def get_next_run_at(reminder_id: int) -> datetime | None:
    job = scheduler.get_job(str(reminder_id))

    if not job or not job.next_run_time:
        return None

    return normalize_datetime(job.next_run_time)


def format_next_run_line(reminder_id: int) -> str:
    next_run_at = get_next_run_at(reminder_id)

    if not next_run_at:
        return "Следующее срабатывание: не запланировано"

    return f"Следующее срабатывание: {format_datetime_ru(next_run_at)}"


def get_int(row: sqlite3.Row, key: str) -> int:
    return int(row[key])


def get_str(row: sqlite3.Row, key: str) -> str:
    return str(row[key])


async def send_once_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_id: int,
) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=f"Напоминание #{reminder_id}:\n\n{reminder_text}",
    )

    mark_reminder_as_sent(reminder_id)


async def send_repeating_reminder(
    bot: Bot,
    chat_id: int,
    reminder_text: str,
    reminder_id: int,
) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=f"Повторяющееся напоминание #{reminder_id}:\n\n{reminder_text}",
    )


def schedule_reminder(
    *,
    bot: Bot,
    reminder_id: int,
    chat_id: int,
    reminder_text: str,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
) -> None:
    job_kwargs: dict[str, Any] = {
        "args": [bot, chat_id, reminder_text, reminder_id],
        "id": str(reminder_id),
        "replace_existing": True,
    }

    if schedule_type == "once":
        scheduler.add_job(
            send_once_reminder,
            trigger="date",
            run_date=start_at,
            **job_kwargs,
        )
        return

    if schedule_type == "every_days":
        scheduler.add_job(
            send_repeating_reminder,
            trigger="interval",
            days=interval_days,
            start_date=start_at,
            **job_kwargs,
        )
        return

    if schedule_type == "every_week":
        scheduler.add_job(
            send_repeating_reminder,
            trigger="interval",
            weeks=interval_weeks,
            start_date=start_at,
            **job_kwargs,
        )
        return

    if schedule_type == "monthly_weekday":
        if month_week_number is None or day_of_week is None:
            raise ValueError("month_week_number and day_of_week are required.")

        scheduler.add_job(
            send_repeating_reminder,
            trigger="cron",
            day=get_month_day_range_for_week_number(month_week_number),
            day_of_week=APSCHEDULER_WEEKDAYS[day_of_week],
            hour=start_at.hour,
            minute=start_at.minute,
            start_date=start_at,
            **job_kwargs,
        )
        return

    raise ValueError(f"Unknown schedule_type: {schedule_type}")


def schedule_reminder_from_row(bot: Bot, reminder: sqlite3.Row) -> None:
    schedule_reminder(
        bot=bot,
        reminder_id=get_int(reminder, "id"),
        chat_id=get_int(reminder, "chat_id"),
        reminder_text=get_str(reminder, "text"),
        schedule_type=get_str(reminder, "schedule_type"),
        start_at=datetime.fromisoformat(get_str(reminder, "start_at")),
        interval_days=reminder["interval_days"],
        interval_weeks=reminder["interval_weeks"],
        day_of_week=reminder["day_of_week"],
        month_week_number=reminder["month_week_number"],
    )


def format_period_line(
    *,
    schedule_type: str,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
) -> str:
    if schedule_type == "once":
        return "один раз"

    if schedule_type == "every_days":
        return f"каждые {interval_days} дн."

    if schedule_type == "every_week":
        weekday_name = WEEKDAY_NAMES_RU_PLURAL.get(str(day_of_week), str(day_of_week))
        return f"каждые {interval_weeks} нед. по {weekday_name}"

    if schedule_type == "monthly_weekday":
        ordinal_name = ORDINAL_NAMES_RU.get(int(month_week_number), str(month_week_number))
        weekday_name = WEEKDAY_NAMES_RU_SINGLE.get(str(day_of_week), str(day_of_week))
        return f"каждый {ordinal_name} {weekday_name} месяца"

    return schedule_type


def format_period_line_from_row(reminder: sqlite3.Row) -> str:
    return format_period_line(
        schedule_type=get_str(reminder, "schedule_type"),
        interval_days=reminder["interval_days"],
        interval_weeks=reminder["interval_weeks"],
        day_of_week=reminder["day_of_week"],
        month_week_number=reminder["month_week_number"],
    )


def format_reminder_for_list(reminder: sqlite3.Row) -> str:
    reminder_id = get_int(reminder, "id")
    start_at = datetime.fromisoformat(get_str(reminder, "start_at"))

    return (
        f"#{reminder_id} — {format_period_line_from_row(reminder)}\n"
        f"Первое срабатывание: {format_datetime_ru(start_at)}\n"
        f"{format_next_run_line(reminder_id)}\n"
        f"{get_str(reminder, 'text')}"
    )


async def restore_active_reminders(bot: Bot) -> None:
    now = datetime.now()
    restored_count = 0
    missed_count = 0

    for reminder in get_all_active_reminders():
        reminder_id = get_int(reminder, "id")
        schedule_type = get_str(reminder, "schedule_type")
        start_at = datetime.fromisoformat(get_str(reminder, "start_at"))

        if schedule_type == "once" and start_at <= now:
            mark_reminder_as_missed(reminder_id)
            missed_count += 1
            continue

        schedule_reminder_from_row(bot, reminder)
        restored_count += 1

    print(
        f"Restored reminders: {restored_count}. "
        f"Missed reminders: {missed_count}."
    )


async def split_command(
    message: Message,
    *,
    maxsplit: int,
    min_parts: int,
    usage_text: str,
    missing_text: str | None = "Не хватает данных.",
) -> list[str] | None:
    if not message.text:
        await message.answer("Не вижу текст команды.")
        return None

    parts = message.text.split(maxsplit=maxsplit)

    if len(parts) < min_parts:
        answer_text = (
            f"{missing_text}\n\n{usage_text}"
            if missing_text
            else usage_text
        )
        await message.answer(answer_text)
        return None

    return parts


async def parse_min_int(
    message: Message,
    value: str,
    *,
    min_value: int = 1,
    max_value: int | None = None,
    parse_error: str = "N должно быть целым числом.",
    range_error: str = "N должно быть больше или равно 1.",
) -> int | None:
    try:
        result = int(value)
    except ValueError:
        await message.answer(parse_error)
        return None

    if result < min_value or (max_value is not None and result > max_value):
        await message.answer(range_error)
        return None

    return result


async def validate_weekday(message: Message, day_of_week: str) -> bool:
    if day_of_week in VALID_WEEKDAYS:
        return True

    await message.answer(
        "Не понял день недели.\n\n"
        "Поддерживаемые значения:\n"
        f"{WEEKDAY_HELP}"
    )
    return False


async def reject_past_datetime(
    message: Message,
    *,
    start_at: datetime,
    heading: str,
    show_candidate: bool = False,
) -> bool:
    now = datetime.now()

    if start_at > now:
        return False

    lines = [heading, ""]

    if show_candidate:
        lines.append(f"Первое подходящее срабатывание получилось: {format_datetime_ru(start_at)}")

    lines.append(f"Сейчас по времени компьютера: {now.strftime('%Y-%m-%d %H:%M')}")
    await message.answer("\n".join(lines))

    return True


async def create_schedule_and_confirm(
    message: Message,
    bot: Bot,
    *,
    reminder_text: str,
    schedule_type: str,
    start_at: datetime,
    interval_days: int | None = None,
    interval_weeks: int | None = None,
    day_of_week: str | None = None,
    month_week_number: int | None = None,
) -> None:
    reminder_id = create_reminder_in_db(
        chat_id=message.chat.id,
        reminder_text=reminder_text,
        schedule_type=schedule_type,
        start_at=start_at,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
    )

    schedule_reminder(
        bot=bot,
        reminder_id=reminder_id,
        chat_id=message.chat.id,
        reminder_text=reminder_text,
        schedule_type=schedule_type,
        start_at=start_at,
        interval_days=interval_days,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
        month_week_number=month_week_number,
    )

    header = (
        "Одноразовое напоминание создано."
        if schedule_type == "once"
        else "Повторяющееся напоминание создано."
    )
    answer_lines = [
        header,
        "",
        f"ID: {reminder_id}",
    ]

    if schedule_type != "once":
        answer_lines.append(
            "Период: "
            + format_period_line(
                schedule_type=schedule_type,
                interval_days=interval_days,
                interval_weeks=interval_weeks,
                day_of_week=day_of_week,
                month_week_number=month_week_number,
            )
        )

    answer_lines.extend(
        [
            f"Первое срабатывание: {format_datetime_ru(start_at)}",
            format_next_run_line(reminder_id),
            f"Текст: {reminder_text}",
        ]
    )

    await message.answer("\n".join(answer_lines))


@dp.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Привет. Я бот для напоминаний.\n\n"
        "Доступные команды:\n"
        "/start — запустить бота\n"
        "/help — показать справку\n"
        "/remind — создать одноразовое напоминание\n"
        "/every_days — повтор каждые N дней\n"
        "/every_days_from — повтор каждые N дней с указанной даты\n"
        "/every_week — повтор каждые N недель в день недели\n"
        "/every_week_from — повтор каждые N недель в день недели с указанной даты\n"
        "/monthly_weekday — повтор в N-й день недели месяца\n"
        "/monthly_weekday_from — повтор в N-й день недели месяца с указанной даты\n"
        "/list — показать активные напоминания\n"
        "/delete — удалить напоминание"
    )


@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Одноразовое напоминание:\n"
        "/remind ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
        "Повтор каждые N дней с ближайшего времени:\n"
        "/every_days N ЧЧ:ММ Текст\n\n"
        "Примеры:\n"
        "/every_days 1 12:12 Каждый день\n"
        "/every_days 3 12:12 Каждые три дня\n\n"
        "Повтор каждые N дней с кастомной даты:\n"
        "/every_days_from N ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
        "Повтор каждые N недель в конкретный день недели:\n"
        "/every_week N ДЕНЬ ЧЧ:ММ Текст\n\n"
        "Примеры:\n"
        "/every_week 1 SAT 12:12 Каждую субботу\n"
        "/every_week 2 SUN 12:12 Каждое второе воскресенье\n\n"
        "Повтор каждые N недель с кастомной даты:\n"
        "/every_week_from N ДЕНЬ ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
        "Повтор в N-й день недели месяца:\n"
        "/monthly_weekday N ДЕНЬ ЧЧ:ММ Текст\n\n"
        "Пример:\n"
        "/monthly_weekday 1 MON 12:12 Каждый первый понедельник месяца\n\n"
        "Повтор в N-й день недели месяца с кастомной даты:\n"
        "/monthly_weekday_from N ДЕНЬ ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
        "Пример:\n"
        "/monthly_weekday_from 1 MON 2026-07-01 12:12 Первый понедельник месяца с июля\n\n"
        "Дни недели:\n"
        f"{WEEKDAY_HELP}\n\n"
        "Список:\n"
        "/list\n\n"
        "Удаление:\n"
        "/delete ID"
    )


@dp.message(Command("remind"))
async def remind(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=3,
        min_parts=4,
        usage_text="Формат:\n/remind ГГГГ-ММ-ДД ЧЧ:ММ Текст",
    )
    if not parts:
        return

    try:
        start_at = parse_datetime(parts[1], parts[2])
    except ValueError:
        await message.answer(
            "Не смог разобрать дату и время.\n\n"
            "Нужный формат:\n"
            "ГГГГ-ММ-ДД ЧЧ:ММ"
        )
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время должны быть в будущем.",
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[3],
        schedule_type="once",
        start_at=start_at,
    )


@dp.message(Command("every_days"))
async def every_days(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=3,
        min_parts=4,
        usage_text=(
            "Формат:\n"
            "/every_days N ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/every_days 3 12:12 Каждые три дня"
        ),
    )
    if not parts:
        return

    interval_days = await parse_min_int(message, parts[1])
    if interval_days is None:
        return

    try:
        start_at = get_nearest_future_datetime_for_time(parts[2])
    except ValueError:
        await message.answer("Не смог разобрать время. Нужный формат: ЧЧ:ММ")
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[3],
        schedule_type="every_days",
        start_at=start_at,
        interval_days=interval_days,
    )


@dp.message(Command("every_days_from"))
async def every_days_from(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=4,
        min_parts=5,
        usage_text="Формат:\n/every_days_from N ГГГГ-ММ-ДД ЧЧ:ММ Текст",
    )
    if not parts:
        return

    interval_days = await parse_min_int(message, parts[1])
    if interval_days is None:
        return

    try:
        start_at = parse_datetime(parts[2], parts[3])
    except ValueError:
        await message.answer("Не смог разобрать дату и время. Нужный формат: ГГГГ-ММ-ДД ЧЧ:ММ")
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время старта должны быть в будущем.",
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[4],
        schedule_type="every_days",
        start_at=start_at,
        interval_days=interval_days,
    )


@dp.message(Command("every_week"))
async def every_week(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=4,
        min_parts=5,
        usage_text=(
            "Формат:\n"
            "/every_week N ДЕНЬ ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/every_week 2 SUN 12:12 Каждое второе воскресенье"
        ),
    )
    if not parts:
        return

    interval_weeks = await parse_min_int(message, parts[1])
    day_of_week = parts[2].upper()

    if interval_weeks is None or not await validate_weekday(message, day_of_week):
        return

    try:
        start_at = get_nearest_future_weekday_datetime(day_of_week, parts[3])
    except ValueError:
        await message.answer("Не смог разобрать время. Нужный формат: ЧЧ:ММ")
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[4],
        schedule_type="every_week",
        start_at=start_at,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
    )


@dp.message(Command("every_week_from"))
async def every_week_from(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=5,
        min_parts=6,
        usage_text=(
            "Формат:\n"
            "/every_week_from N ДЕНЬ ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/every_week_from 2 SUN 2026-06-14 12:12 Каждое второе воскресенье"
        ),
    )
    if not parts:
        return

    interval_weeks = await parse_min_int(message, parts[1])
    day_of_week = parts[2].upper()

    if interval_weeks is None or not await validate_weekday(message, day_of_week):
        return

    try:
        start_at = get_first_weekday_datetime_on_or_after_date(
            day_of_week=day_of_week,
            date_text=parts[3],
            time_text=parts[4],
        )
    except ValueError:
        await message.answer("Не смог разобрать дату или время. Нужный формат: ГГГГ-ММ-ДД ЧЧ:ММ")
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время первого срабатывания должны быть в будущем.",
        show_candidate=True,
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[5],
        schedule_type="every_week",
        start_at=start_at,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
    )


@dp.message(Command("monthly_weekday"))
async def monthly_weekday(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=4,
        min_parts=5,
        usage_text=(
            "Формат:\n"
            "/monthly_weekday N ДЕНЬ ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/monthly_weekday 1 MON 12:12 Каждый первый понедельник месяца"
        ),
    )
    if not parts:
        return

    month_week_number = await parse_min_int(
        message,
        parts[1],
        max_value=5,
        parse_error="N должно быть целым числом от 1 до 5.",
        range_error="N должно быть от 1 до 5.",
    )
    day_of_week = parts[2].upper()

    if month_week_number is None or not await validate_weekday(message, day_of_week):
        return

    try:
        start_at = get_nearest_monthly_weekday_datetime(
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=parts[3],
        )
    except ValueError:
        await message.answer("Не смог разобрать время. Нужный формат: ЧЧ:ММ")
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[4],
        schedule_type="monthly_weekday",
        start_at=start_at,
        month_week_number=month_week_number,
        day_of_week=day_of_week,
    )


@dp.message(Command("monthly_weekday_from"))
async def monthly_weekday_from(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=5,
        min_parts=6,
        usage_text=(
            "Формат:\n"
            "/monthly_weekday_from N ДЕНЬ ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/monthly_weekday_from 1 MON 2026-07-01 12:12 Первый понедельник месяца с июля"
        ),
    )
    if not parts:
        return

    month_week_number = await parse_min_int(
        message,
        parts[1],
        max_value=5,
        parse_error="N должно быть целым числом от 1 до 5.",
        range_error="N должно быть от 1 до 5.",
    )
    day_of_week = parts[2].upper()

    if month_week_number is None or not await validate_weekday(message, day_of_week):
        return

    try:
        lower_bound = parse_datetime(parts[3], parts[4])
        start_at = get_monthly_weekday_datetime_on_or_after(
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=parts[4],
            lower_bound=lower_bound,
        )
    except ValueError:
        await message.answer("Не смог разобрать дату или время. Нужный формат: ГГГГ-ММ-ДД ЧЧ:ММ")
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время первого срабатывания должны быть в будущем.",
        show_candidate=True,
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[5],
        schedule_type="monthly_weekday",
        start_at=start_at,
        month_week_number=month_week_number,
        day_of_week=day_of_week,
    )


@dp.message(Command("list"))
async def list_reminders(message: Message) -> None:
    chat_reminders = get_active_reminders_for_chat(message.chat.id)

    if not chat_reminders:
        await message.answer("В этом чате нет активных напоминаний.")
        return

    lines = ["Активные напоминания:\n"]
    lines.extend(format_reminder_for_list(reminder) for reminder in chat_reminders)

    await message.answer("\n\n".join(lines))


@dp.message(Command("delete"))
async def delete_reminder(message: Message) -> None:
    parts = await split_command(
        message,
        maxsplit=1,
        min_parts=2,
        usage_text=(
            "Укажи ID напоминания.\n\n"
            "Формат:\n"
            "/delete ID\n\n"
            "Пример:\n"
            "/delete 1"
        ),
        missing_text=None,
    )
    if not parts:
        return

    try:
        reminder_id = int(parts[1].strip())
    except ValueError:
        await message.answer("ID должен быть числом. Например: /delete 1")
        return

    reminder = get_active_reminder_from_db(reminder_id)

    if not reminder:
        await message.answer(f"Не нашёл активное напоминание с ID {reminder_id}.")
        return

    if get_int(reminder, "chat_id") != message.chat.id:
        await message.answer(
            "Это напоминание создано в другом чате. "
            "Из этого чата его удалить нельзя."
        )
        return

    job = scheduler.get_job(str(reminder_id))

    if job:
        scheduler.remove_job(str(reminder_id))

    mark_reminder_as_deleted(reminder_id)

    await message.answer(f"Напоминание #{reminder_id} удалено.")


async def main() -> None:
    init_db()

    bot = Bot(token=BOT_TOKEN)

    scheduler.start()
    await restore_active_reminders(bot)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
