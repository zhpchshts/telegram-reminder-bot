from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from app.constants import TIMEZONE_LOOKUP_URL, WEEKDAY_HELP
from app.config import BOT_TOKEN, TMA_DIRECT_URL
from app.formatting import format_datetime_ru
from app.reminder_models import ReminderCreateData
from app.reminder_parsing import (
    ReminderParseError,
    ReminderParseResult,
    parse_delete_command,
    parse_every_days_command,
    parse_every_days_from_command,
    parse_every_week_command,
    parse_every_week_from_command,
    parse_monthly_day_command,
    parse_monthly_day_from_command,
    parse_monthly_weekday_command,
    parse_monthly_weekday_from_command,
    parse_remind_command,
    parse_timezone_command,
)
from app.reminder_service import (
    build_active_reminders_list_text_for_chat,
    build_created_reminder_text,
    create_scheduled_reminder,
    delete_active_reminder_for_chat,
    get_chat_timezone_name,
    set_chat_timezone_for_chat,
)
from app.tma_launch import create_tma_launch_token

router = Router()
NO_LINK_PREVIEW = LinkPreviewOptions(is_disabled=True)
ParseCommand = Callable[[str | None, str], ReminderParseResult]


def is_plain_reply_to_current_bot(message: Message) -> bool:
    if not message.text or message.text.startswith("/"):
        return False

    reply_to_message = message.reply_to_message
    if reply_to_message is None:
        return False

    reply_author = reply_to_message.from_user
    if reply_author is None or not reply_author.is_bot:
        return False

    bot_id_text, separator, _ = BOT_TOKEN.partition(":")
    if not separator or not bot_id_text.isdecimal():
        return False

    return reply_author.id == int(bot_id_text)


def build_tma_keyboard(launch_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть Незабудку",
                    url=launch_url,
                )
            ]
        ]
    )


def build_tma_launch_url(
    *,
    chat_id: int,
    chat_type: str,
    chat_title: str | None,
) -> str:
    token = create_tma_launch_token(
        chat_id=chat_id,
        chat_type=chat_type,
        chat_title=chat_title,
        secret=BOT_TOKEN,
    )
    return f"{TMA_DIRECT_URL}{token}"


def build_tma_keyboard_for_message(message: Message) -> InlineKeyboardMarkup | None:
    if not TMA_DIRECT_URL:
        return None

    launch_url = build_tma_launch_url(
        chat_id=message.chat.id,
        chat_type=message.chat.type,
        chat_title=message.chat.title,
    )
    return build_tma_keyboard(launch_url)


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
    data: ReminderCreateData,
) -> None:
    reminder_id = create_scheduled_reminder(
        bot=bot,
        chat_id=message.chat.id,
        data=data,
    )
    answer_text = build_created_reminder_text(
        reminder_id=reminder_id,
        data=data,
    )

    await message.answer(answer_text)


async def answer_parse_error(
    message: Message,
    *,
    error: ReminderParseError,
    usage_text: str,
    invalid_datetime_text: str | None = None,
) -> None:
    error_text = str(error)

    if error_text == "Не хватает данных.":
        await message.answer(f"{error_text}\n\n{usage_text}")
        return

    if error_text == "Не понял день недели.":
        await message.answer(
            f"Не понял день недели.\n\nПоддерживаемые значения:\n{WEEKDAY_HELP}"
        )
        return

    if invalid_datetime_text and error_text.startswith(
        ("Не смог разобрать дату", "Не смог разобрать время")
    ):
        await message.answer(invalid_datetime_text)
        return

    await message.answer(error_text)


async def parse_create_command_or_answer(
    message: Message,
    *,
    parser: ParseCommand,
    usage_text: str,
    invalid_datetime_text: str | None = None,
) -> ReminderParseResult | None:
    timezone_name = get_chat_timezone_name(message.chat.id)

    try:
        return parser(message.text, timezone_name)
    except ReminderParseError as error:
        await answer_parse_error(
            message,
            error=error,
            usage_text=usage_text,
            invalid_datetime_text=invalid_datetime_text,
        )
        return None


async def handle_create_command(
    message: Message,
    bot: Bot,
    *,
    parser: ParseCommand,
    usage_text: str,
    invalid_datetime_text: str | None = None,
) -> None:
    parse_result = await parse_create_command_or_answer(
        message,
        parser=parser,
        usage_text=usage_text,
        invalid_datetime_text=invalid_datetime_text,
    )

    if parse_result is None:
        return

    if parse_result.reject_past_heading and await reject_past_datetime(
        message,
        start_at=parse_result.data.start_at,
        heading=parse_result.reject_past_heading,
        timezone_name=parse_result.data.timezone_name,
        show_candidate=parse_result.reject_past_show_candidate,
    ):
        return

    await create_schedule_and_confirm(
        message,
        bot,
        data=parse_result.data,
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Привет.\n"
        "Я Незабудка — бот для напоминаний в Telegram-чатах.\n\n"
        "Основной сценарий теперь в Mini App: там можно создать, посмотреть "
        "и удалить напоминания.\n\n"
        "Текстовые команды остаются как запасной способ управления:\n"
        "/help — справка\n"
        "/examples — примеры команд\n"
        "/timezone — таймзона чата",
        reply_markup=build_tma_keyboard_for_message(message),
    )


@router.message(Command("app"))
async def app_command(message: Message) -> None:
    reply_markup = build_tma_keyboard_for_message(message)

    if reply_markup is None:
        await message.answer(
            "Mini App пока не настроен.\n\n"
            "Администратору нужно задать переменную окружения TMA_DIRECT_URL."
        )
        return

    await message.answer(
        "Открой Незабудку для управления напоминаниями:",
        reply_markup=reply_markup,
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Незабудка — бот для напоминаний в Telegram-чатах.\n\n"
        "Основной сценарий — Mini App: создать, посмотреть и удалить "
        "напоминания можно через интерфейс.\n\n"
        "Текстовые команды на случай, если удобнее управлять из чата:\n"
        "/app — открыть Mini App\n"
        "/examples — показать примеры создания напоминаний\n"
        "/timezone — показать или задать таймзону текущего чата\n"
        "/list — показать активные напоминания текущего чата\n"
        "/delete ID — удалить напоминание из текущего чата\n\n"
        "Команды создания через текст:\n"
        "/remind — одноразовое напоминание\n"
        "/every_days — повтор каждые N дней\n"
        "/every_week — повтор каждые N недель\n"
        "/monthly_weekday — повтор в N-й день недели месяца\n"
        "/monthly_day — повтор в конкретный день месяца\n\n"
        "Напоминания создаются и отображаются только в рамках текущего чата.\n"
        "Таймзона тоже настраивается отдельно для каждого чата.\n"
        "Смена таймзоны влияет только на новые напоминания.\n\n"
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
        reply_markup=build_tma_keyboard_for_message(message),
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
        "Каждое 11 число месяца:\n"
        "/monthly_day 11 12:12 Оплатить интернет\n\n"
        "Каждое 11 число месяца с кастомной датой старта:\n"
        "/monthly_day_from 11 2026-07-01 12:12 Оплатить интернет\n\n"
        "Таймзона:\n"
        "/timezone Asia/Yekaterinburg"
    )


@router.message(Command("timezone"))
async def timezone_command(message: Message) -> None:
    try:
        timezone_name = parse_timezone_command(message.text)
    except ReminderParseError as error:
        await message.answer(str(error))
        return

    if timezone_name is None:
        current_timezone = get_chat_timezone_name(message.chat.id)

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

    is_timezone_updated = set_chat_timezone_for_chat(
        chat_id=message.chat.id,
        timezone_name=timezone_name,
    )

    if not is_timezone_updated:
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

    await message.answer(
        "Таймзона этого чата обновлена.\n\n"
        f"Теперь новые напоминания будут создаваться в таймзоне: {timezone_name}\n\n"
        "Уже созданные напоминания останутся в той таймзоне, "
        "которая была установлена на момент их создания."
    )


@router.message(Command("remind"))
async def remind(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_remind_command,
        usage_text="Формат:\n/remind ГГГГ-ММ-ДД ЧЧ:ММ Текст",
        invalid_datetime_text=(
            "Не смог разобрать дату и время.\n\nНужный формат:\nГГГГ-ММ-ДД ЧЧ:ММ"
        ),
    )


@router.message(Command("every_days"))
async def every_days(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_every_days_command,
        usage_text=(
            "Формат:\n"
            "/every_days N ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/every_days 3 12:12 Каждые три дня"
        ),
        invalid_datetime_text="Не смог разобрать время.\nНужный формат: ЧЧ:ММ",
    )


@router.message(Command("every_days_from"))
async def every_days_from(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_every_days_from_command,
        usage_text="Формат:\n/every_days_from N ГГГГ-ММ-ДД ЧЧ:ММ Текст",
        invalid_datetime_text=(
            "Не смог разобрать дату и время.\nНужный формат: ГГГГ-ММ-ДД ЧЧ:ММ"
        ),
    )


@router.message(Command("every_week"))
async def every_week(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_every_week_command,
        usage_text=(
            "Формат:\n"
            "/every_week N ДЕНЬ ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/every_week 2 SUN 12:12 Каждое второе воскресенье"
        ),
        invalid_datetime_text="Не смог разобрать время.\nНужный формат: ЧЧ:ММ",
    )


@router.message(Command("every_week_from"))
async def every_week_from(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_every_week_from_command,
        usage_text=(
            "Формат:\n"
            "/every_week_from N ДЕНЬ ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/every_week_from 2 SUN 2026-06-14 12:12 Каждое второе воскресенье"
        ),
        invalid_datetime_text=(
            "Не смог разобрать дату или время.\nНужный формат: ГГГГ-ММ-ДД ЧЧ:ММ"
        ),
    )


@router.message(Command("monthly_weekday"))
async def monthly_weekday(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_monthly_weekday_command,
        usage_text=(
            "Формат:\n"
            "/monthly_weekday N ДЕНЬ ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/monthly_weekday 1 MON 12:12 Каждый первый понедельник месяца"
        ),
        invalid_datetime_text="Не смог разобрать время.\nНужный формат: ЧЧ:ММ",
    )


@router.message(Command("monthly_weekday_from"))
async def monthly_weekday_from(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_monthly_weekday_from_command,
        usage_text=(
            "Формат:\n"
            "/monthly_weekday_from N ДЕНЬ ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/monthly_weekday_from 1 MON 2026-07-01 12:12 Первый понедельник "
            "месяца с июля"
        ),
        invalid_datetime_text=(
            "Не смог разобрать дату или время.\nНужный формат: ГГГГ-ММ-ДД ЧЧ:ММ"
        ),
    )


@router.message(Command("monthly_day"))
async def monthly_day(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_monthly_day_command,
        usage_text=(
            "Формат:\n"
            "/monthly_day ДЕНЬ ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/monthly_day 11 12:12 Оплатить интернет"
        ),
        invalid_datetime_text="Не смог разобрать время.\nНужный формат: ЧЧ:ММ",
    )


@router.message(Command("monthly_day_from"))
async def monthly_day_from(message: Message, bot: Bot) -> None:
    await handle_create_command(
        message,
        bot,
        parser=parse_monthly_day_from_command,
        usage_text=(
            "Формат:\n"
            "/monthly_day_from ДЕНЬ ГГГГ-ММ-ДД ЧЧ:ММ Текст\n\n"
            "Пример:\n"
            "/monthly_day_from 11 2026-07-01 12:12 Оплатить интернет"
        ),
        invalid_datetime_text=(
            "Не смог разобрать дату или время.\nНужный формат: ГГГГ-ММ-ДД ЧЧ:ММ"
        ),
    )


@router.message(Command("list"))
async def list_reminders(message: Message) -> None:
    answer_text = build_active_reminders_list_text_for_chat(message.chat.id)

    if answer_text is None:
        await message.answer("В этом чате нет активных напоминаний.")
        return

    await message.answer(answer_text, parse_mode="HTML")


@router.message(Command("delete"))
async def delete_reminder(message: Message) -> None:
    usage_text = "Укажи ID напоминания.\n\nФормат:\n/delete ID\n\nПример:\n/delete 1"

    try:
        reminder_id = parse_delete_command(message.text)
    except ReminderParseError as error:
        if str(error) == "Не хватает данных.":
            await message.answer(usage_text)
            return

        if str(error) == "ID должен быть числом.":
            await message.answer("ID должен быть числом.\nНапример: /delete 1")
            return

        await message.answer(str(error))
        return

    was_deleted = delete_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=message.chat.id,
    )

    if not was_deleted:
        await message.answer(
            f"Не нашёл активное напоминание с ID {reminder_id} в этом чате."
        )
        return

    await message.answer(f"Напоминание #{reminder_id} удалено.")


@router.message()
async def unknown_message(message: Message) -> None:
    if not message.text:
        return

    if is_plain_reply_to_current_bot(message):
        return

    reply_markup = build_tma_keyboard_for_message(message)

    if message.text.startswith("/"):
        await message.answer(
            "Не знаю такую команду.\n\n"
            "Открыть интерфейс управления напоминаниями можно через кнопку ниже.\n\n"
            "Доступные команды можно посмотреть через /help.\n"
            "Примеры создания напоминаний — через /examples.",
            reply_markup=reply_markup,
        )
        return

    await message.answer(
        "Я пока понимаю только команды.\n\n"
        "Открыть интерфейс управления напоминаниями можно через кнопку ниже.\n\n"
        "Доступные команды можно посмотреть через /help.\n"
        "Примеры создания напоминаний — через /examples.",
        reply_markup=reply_markup,
    )
