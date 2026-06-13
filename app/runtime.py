from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from fastapi import FastAPI

from app.api import app as api_app
from app.config import BOT_TOKEN, HEALTHCHECK_CHAT_ID, HEALTHCHECK_INTERVAL_MINUTES
from app.database import init_db
from app.handlers import router
from app.scheduler import restore_active_reminders, schedule_healthcheck, scheduler


@dataclass(frozen=True)
class BotRuntime:
    bot: Bot
    dispatcher: Dispatcher
    api_app: FastAPI


def bind_api_runtime(fastapi_app: FastAPI, *, bot: Bot) -> None:
    fastapi_app.state.bot = bot
    fastapi_app.state.scheduler = scheduler


def create_bot_runtime(
    *,
    bot_token: str = BOT_TOKEN,
    fastapi_app: FastAPI = api_app,
) -> BotRuntime:
    bot = Bot(token=bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    bind_api_runtime(fastapi_app, bot=bot)

    return BotRuntime(
        bot=bot,
        dispatcher=dispatcher,
        api_app=fastapi_app,
    )


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="help", description="Показать справку"),
            BotCommand(command="examples", description="Показать примеры команд"),
            BotCommand(command="remind", description="Одноразовое напоминание"),
            BotCommand(command="every_days", description="Повтор каждые N дней"),
            BotCommand(
                command="every_days_from",
                description="Повтор каждые N дней с даты",
            ),
            BotCommand(
                command="every_week",
                description="Повтор каждые N недель",
            ),
            BotCommand(
                command="every_week_from",
                description="Повтор каждые N недель с даты",
            ),
            BotCommand(
                command="monthly_weekday",
                description="Повтор в N-й день недели месяца",
            ),
            BotCommand(
                command="monthly_weekday_from",
                description="Месячный повтор с даты",
            ),
            BotCommand(command="monthly_day", description="Повтор в день месяца"),
            BotCommand(
                command="monthly_day_from",
                description="Повтор в день месяца с даты",
            ),
            BotCommand(command="timezone", description="Показать или задать таймзону"),
            BotCommand(command="list", description="Показать активные напоминания"),
            BotCommand(command="delete", description="Удалить напоминание"),
        ]
    )


async def prepare_bot_runtime(runtime: BotRuntime) -> None:
    init_db()
    await set_bot_commands(runtime.bot)

    if not scheduler.running:
        scheduler.start()

    await restore_active_reminders(runtime.bot)

    if HEALTHCHECK_CHAT_ID is not None:
        schedule_healthcheck(
            bot=runtime.bot,
            chat_id=HEALTHCHECK_CHAT_ID,
            interval_minutes=HEALTHCHECK_INTERVAL_MINUTES,
        )


async def run_polling_runtime() -> None:
    runtime = create_bot_runtime()
    await prepare_bot_runtime(runtime)
    await runtime.dispatcher.start_polling(runtime.bot)
