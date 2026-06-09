from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import LinkPreviewOptions, Message

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import APP_TIMEZONE_NAME

from app.constants import TIMEZONE_LOOKUP_URL, VALID_WEEKDAYS, WEEKDAY_HELP
from app.database import (
    create_reminder_in_db,
    get_active_reminder_for_chat,
    get_active_reminders_for_chat,
    mark_reminder_as_deleted,
    get_chat_timezone,
    set_chat_timezone,
)
from app.formatting import (
    format_datetime_ru,
    format_period_line,
    format_reminder_for_list,
    get_int,
)
from app.scheduler import (
    format_next_run_line,
    schedule_reminder,
    scheduler,
)
from app.schedule_calculations import (
    get_first_weekday_datetime_on_or_after_date,
    get_monthly_weekday_datetime_on_or_after,
    get_nearest_future_datetime_for_time,
    get_nearest_future_weekday_datetime,
    get_nearest_monthly_weekday_datetime,
    parse_datetime,
)


router = Router()

NO_LINK_PREVIEW = LinkPreviewOptions(is_disabled=True)


def get_chat_timezone_name(chat_id: int) -> str:
    return get_chat_timezone(chat_id) or APP_TIMEZONE_NAME


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
        answer_text = f"{missing_text}\n\n{usage_text}" if missing_text else usage_text
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
        f"Не понял день недели.\n\nПоддерживаемые значения:\n{WEEKDAY_HELP}"
    )
    return False


async def reject_past_datetime(
    message: Message,
    *,
    start_at: datetime,
    heading: str,
    timezone_name: str,
    show_candidate: bool = False,
) -> bool:
    timezone = ZoneInfo(timezone_name)
    now = datetime.now(timezone)

    if start_at > now:
        return False

    lines = [heading, ""]

    if show_candidate:
        lines.append(
            f"Первое подходящее срабатывание получилось: "
            f"{format_datetime_ru(start_at, timezone_name)}"
        )

    lines.append(
        f"Сейчас в таймзоне {timezone_name}: {format_datetime_ru(now, timezone_name)}"
    )
    await message.answer("\n".join(lines))

    return True


async def create_schedule_and_confirm(
    message: Message,
    bot: Bot,
    *,
    reminder_text: str,
    schedule_type: str,
    start_at: datetime,
    timezone_name: str,
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
        timezone=timezone_name,
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
        timezone_name=timezone_name,
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
            f"Таймзона: {timezone_name}",
            f"Первое срабатывание: {format_datetime_ru(start_at, timezone_name)}",
            format_next_run_line(reminder_id, timezone_name),
            f"Текст: {reminder_text}",
        ]
    )

    await message.answer("\n".join(answer_lines))


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Привет. Я бот для напоминаний.\n\n"
        "Доступные команды:\n"
        "/start — запустить бота\n"
        "/help — показать справку\n"
        "/examples — показать примеры команд\n"
        "/remind — создать одноразовое напоминание\n"
        "/every_days — повтор каждые N дней\n"
        "/every_days_from — повтор каждые N дней с указанной даты\n"
        "/every_week — повтор каждые N недель в день недели\n"
        "/every_week_from — повтор каждые N недель в день недели с указанной даты\n"
        "/monthly_weekday — повтор в N-й день недели месяца\n"
        "/monthly_weekday_from — повтор в N-й день недели месяца с указанной даты\n"
        "/list — показать активные напоминания\n"
        "/timezone — показать или задать таймзону чата\n"
        "/delete — удалить напоминание"
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Краткая справка по боту.\n\n"
        "Основные команды:\n"
        "/timezone — показать или задать таймзону текущего чата\n"
        "/examples — показать примеры создания напоминаний\n"
        "/list — показать активные напоминания текущего чата\n"
        "/delete ID — удалить напоминание из текущего чата\n\n"
        "Напоминания создаются и отображаются только в рамках текущего чата.\n"
        "Таймзона тоже настраивается отдельно для каждого чата.\n\n"
        "Дни недели в командах:\n"
        f"{WEEKDAY_HELP}\n\n"
        "Таймзона указывается в IANA-формате, например:\n"
        "/timezone Asia/Yekaterinburg\n"
        "/timezone Europe/Moscow\n"
        "/timezone Asia/Almaty\n\n"
        "Узнать и скопировать свою таймзону можно здесь:\n"
        f"{TIMEZONE_LOOKUP_URL}\n\n"
        "Чтобы посмотреть готовые примеры команд, отправь:\n"
        "/examples",
        link_preview_options=NO_LINK_PREVIEW,
    )


@router.message(Command("examples"))
async def examples_command(message: Message) -> None:
    await message.answer(
        "Примеры команд:\n\n"
        "Одноразовое напоминание:\n"
        "/remind 2026-06-10 12:12 Проверить статус релиза\n\n"
        "Каждый день:\n"
        "/every_days 1 12:12 Выпить воду\n\n"
        "Каждые 3 дня:\n"
        "/every_days 3 12:12 Проверить задачу\n\n"
        "Каждую субботу:\n"
        "/every_week 1 SAT 12:12 Запланировать покупки\n\n"
        "Каждое второе воскресенье:\n"
        "/every_week 2 SUN 12:12 Проверить регулярный отчёт\n\n"
        "Каждый первый понедельник месяца:\n"
        "/monthly_weekday 1 MON 12:12 Оплатить сервисы\n\n"
        "С кастомной датой старта:\n"
        "/every_days_from 3 2026-06-10 12:12 Каждые три дня с 10 июня\n\n"
        "Таймзона:\n"
        "/timezone Asia/Yekaterinburg"
    )


@router.message(Command("timezone"))
async def timezone_command(message: Message) -> None:
    if not message.text:
        await message.answer("Не вижу текст команды.")
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) == 1:
        current_timezone = get_chat_timezone(message.chat.id) or APP_TIMEZONE_NAME

        await message.answer(
            "Текущая таймзона этого чата:\n\n"
            f"{current_timezone}\n\n"
            "Чтобы изменить таймзону, отправь команду в формате:\n"
            "/timezone Asia/Yekaterinburg\n\n"
            "Узнать и скопировать свою таймзону можно здесь:\n"
            f"{TIMEZONE_LOOKUP_URL}",
            link_preview_options=NO_LINK_PREVIEW,
        )
        return

    timezone_name = parts[1].strip()

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        await message.answer(
            "Не смог распознать таймзону.\n\n"
            "Используй IANA-формат, например:\n"
            "/timezone Asia/Yekaterinburg\n"
            "/timezone Europe/Moscow\n"
            "/timezone Asia/Almaty\n\n"
            "Узнать и скопировать свою таймзону можно здесь:\n"
            f"{TIMEZONE_LOOKUP_URL}",
            link_preview_options=NO_LINK_PREVIEW,
        )
        return

    set_chat_timezone(
        chat_id=message.chat.id,
        timezone=timezone_name,
    )

    await message.answer(
        "Таймзона этого чата обновлена.\n\n"
        f"Теперь время будет считаться как: {timezone_name}"
    )


@router.message(Command("remind"))
async def remind(message: Message, bot: Bot) -> None:
    parts = await split_command(
        message,
        maxsplit=3,
        min_parts=4,
        usage_text="Формат:\n/remind ГГГГ-ММ-ДД ЧЧ:ММ Текст",
    )
    if not parts:
        return

    timezone_name = get_chat_timezone_name(message.chat.id)
    chat_timezone = ZoneInfo(timezone_name)

    try:
        start_at = parse_datetime(parts[1], parts[2], chat_timezone)
    except ValueError:
        await message.answer(
            "Не смог разобрать дату и время.\n\nНужный формат:\nГГГГ-ММ-ДД ЧЧ:ММ"
        )
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время должны быть в будущем.",
        timezone_name=timezone_name,
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[3],
        schedule_type="once",
        start_at=start_at,
        timezone_name=timezone_name,
    )


@router.message(Command("every_days"))
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

    timezone_name = get_chat_timezone_name(message.chat.id)
    chat_timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_nearest_future_datetime_for_time(
            parts[2],
            timezone=chat_timezone,
        )
    except ValueError:
        await message.answer("Не смог разобрать время. Нужный формат: ЧЧ:ММ")
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[3],
        schedule_type="every_days",
        start_at=start_at,
        timezone_name=timezone_name,
        interval_days=interval_days,
    )


@router.message(Command("every_days_from"))
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

    timezone_name = get_chat_timezone_name(message.chat.id)
    chat_timezone = ZoneInfo(timezone_name)

    try:
        start_at = parse_datetime(parts[2], parts[3], chat_timezone)
    except ValueError:
        await message.answer(
            "Не смог разобрать дату и время. Нужный формат: ГГГГ-ММ-ДД ЧЧ:ММ"
        )
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время старта должны быть в будущем.",
        timezone_name=timezone_name,
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[4],
        schedule_type="every_days",
        start_at=start_at,
        timezone_name=timezone_name,
        interval_days=interval_days,
    )


@router.message(Command("every_week"))
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

    timezone_name = get_chat_timezone_name(message.chat.id)
    chat_timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_nearest_future_weekday_datetime(
            day_of_week,
            parts[3],
            timezone=chat_timezone,
        )
    except ValueError:
        await message.answer("Не смог разобрать время. Нужный формат: ЧЧ:ММ")
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[4],
        schedule_type="every_week",
        start_at=start_at,
        timezone_name=timezone_name,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
    )


@router.message(Command("every_week_from"))
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

    timezone_name = get_chat_timezone_name(message.chat.id)
    chat_timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_first_weekday_datetime_on_or_after_date(
            day_of_week=day_of_week,
            date_text=parts[3],
            time_text=parts[4],
            timezone=chat_timezone,
        )
    except ValueError:
        await message.answer(
            "Не смог разобрать дату или время. Нужный формат: ГГГГ-ММ-ДД ЧЧ:ММ"
        )
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время первого срабатывания должны быть в будущем.",
        timezone_name=timezone_name,
        show_candidate=True,
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[5],
        schedule_type="every_week",
        start_at=start_at,
        timezone_name=timezone_name,
        interval_weeks=interval_weeks,
        day_of_week=day_of_week,
    )


@router.message(Command("monthly_weekday"))
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

    timezone_name = get_chat_timezone_name(message.chat.id)
    chat_timezone = ZoneInfo(timezone_name)

    try:
        start_at = get_nearest_monthly_weekday_datetime(
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=parts[3],
            timezone=chat_timezone,
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
        timezone_name=timezone_name,
        month_week_number=month_week_number,
        day_of_week=day_of_week,
    )


@router.message(Command("monthly_weekday_from"))
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

    timezone_name = get_chat_timezone_name(message.chat.id)
    chat_timezone = ZoneInfo(timezone_name)

    try:
        lower_bound = parse_datetime(parts[3], parts[4], chat_timezone)
        start_at = get_monthly_weekday_datetime_on_or_after(
            month_week_number=month_week_number,
            day_of_week=day_of_week,
            time_text=parts[4],
            lower_bound=lower_bound,
        )
    except ValueError:
        await message.answer(
            "Не смог разобрать дату или время. Нужный формат: ГГГГ-ММ-ДД ЧЧ:ММ"
        )
        return

    if await reject_past_datetime(
        message,
        start_at=start_at,
        heading="Дата и время первого срабатывания должны быть в будущем.",
        timezone_name=timezone_name,
        show_candidate=True,
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        reminder_text=parts[5],
        schedule_type="monthly_weekday",
        start_at=start_at,
        timezone_name=timezone_name,
        month_week_number=month_week_number,
        day_of_week=day_of_week,
    )


@router.message(Command("list"))
async def list_reminders(message: Message) -> None:
    chat_reminders = get_active_reminders_for_chat(message.chat.id)

    if not chat_reminders:
        await message.answer("В этом чате нет активных напоминаний.")
        return

    lines = ["Активные напоминания:\n"]
    lines.extend(
        format_reminder_for_list(
            reminder,
            format_next_run_line(get_int(reminder, "id")),
        )
        for reminder in chat_reminders
    )

    await message.answer("\n\n".join(lines))


@router.message(Command("delete"))
async def delete_reminder(message: Message) -> None:
    parts = await split_command(
        message,
        maxsplit=1,
        min_parts=2,
        usage_text=(
            "Укажи ID напоминания.\n\nФормат:\n/delete ID\n\nПример:\n/delete 1"
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

    reminder = get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=message.chat.id,
    )

    if not reminder:
        await message.answer(
            f"Не нашёл активное напоминание с ID {reminder_id} в этом чате."
        )
        return

    job = scheduler.get_job(str(reminder_id))

    if job:
        scheduler.remove_job(str(reminder_id))

    mark_reminder_as_deleted(reminder_id)

    await message.answer(f"Напоминание #{reminder_id} удалено.")
