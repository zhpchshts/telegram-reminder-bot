import asyncio

from aiogram import Bot, Dispatcher

from app.config import BOT_TOKEN
from app.database import init_db
from app.handlers import router
from app.scheduler import restore_active_reminders, scheduler


async def main() -> None:
    init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    scheduler.start()
    await restore_active_reminders(bot)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
