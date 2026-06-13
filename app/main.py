import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.config import BOT_TOKEN, HEALTHCHECK_CHAT_ID, HEALTHCHECK_INTERVAL_MINUTES
from app.database import init_db
from app.handlers import router
from app.scheduler import restore_active_reminders, schedule_healthcheck, scheduler


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


async def main() -> None:
    init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await set_bot_commands(bot)

    scheduler.start()
    restore_active_reminders(bot)

    if HEALTHCHECK_CHAT_ID is not None:
        schedule_healthcheck(
            bot=bot,
            chat_id=HEALTHCHECK_CHAT_ID,
            interval_minutes=HEALTHCHECK_INTERVAL_MINUTES,
        )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
