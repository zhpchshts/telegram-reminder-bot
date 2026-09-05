import asyncio
from dataclasses import dataclass
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from fastapi import FastAPI
import uvicorn

from app.api import app as api_app
from app.config import (
    API_HOST,
    API_PORT,
    BOT_TOKEN,
    HEALTHCHECK_CHAT_ID,
    require_bot_token,
)
from app.completion_handlers import router as completion_router
from app.database import init_db
from app.handlers import router
from app.scheduler import (
    get_missing_required_scheduler_job_ids,
    restore_active_reminders,
    schedule_healthcheck,
    scheduler,
)

LOGGER = logging.getLogger(__name__)
RUNTIME_SHUTDOWN_TIMEOUT_SECONDS = 10
APPLICATION_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_application_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=APPLICATION_LOG_FORMAT,
    )


@dataclass(frozen=True)
class BotRuntime:
    bot: Bot
    dispatcher: Dispatcher
    api_app: FastAPI


def bind_api_runtime(
    fastapi_app: FastAPI,
    *,
    bot: Bot,
    bot_token: str,
) -> None:
    fastapi_app.state.bot = bot
    fastapi_app.state.bot_token = bot_token
    fastapi_app.state.scheduler = scheduler
    fastapi_app.state.reminders_restored = False


def create_bot_runtime(
    *,
    bot_token: str | None = None,
    fastapi_app: FastAPI = api_app,
) -> BotRuntime:
    configured_bot_token = require_bot_token(
        BOT_TOKEN if bot_token is None else bot_token
    )
    bot = Bot(token=configured_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(completion_router)
    dispatcher.include_router(router)

    bind_api_runtime(
        fastapi_app,
        bot=bot,
        bot_token=configured_bot_token,
    )

    return BotRuntime(
        bot=bot,
        dispatcher=dispatcher,
        api_app=fastapi_app,
    )


def create_api_server(
    runtime: BotRuntime,
    *,
    host: str = API_HOST,
    port: int = API_PORT,
) -> uvicorn.Server:
    config = uvicorn.Config(
        runtime.api_app,
        host=host,
        port=port,
        log_level="info",
    )
    return uvicorn.Server(config)


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="help", description="Показать справку"),
            BotCommand(command="examples", description="Показать примеры команд"),
            BotCommand(command="app", description="Управлять напоминаниями"),
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
    runtime.api_app.state.reminders_restored = False
    init_db()
    await set_bot_commands(runtime.bot)

    if not scheduler.running:
        scheduler.start()

    await restore_active_reminders(runtime.bot)

    if HEALTHCHECK_CHAT_ID is not None:
        schedule_healthcheck(
            bot=runtime.bot,
            chat_id=HEALTHCHECK_CHAT_ID,
        )

    missing_job_ids = get_missing_required_scheduler_job_ids(scheduler)
    if missing_job_ids:
        raise RuntimeError(
            "Required scheduler jobs are missing: " + ", ".join(missing_job_ids)
        )

    runtime.api_app.state.reminders_restored = True


async def stop_polling_best_effort(
    dispatcher: Dispatcher,
    *,
    timeout_seconds: float = RUNTIME_SHUTDOWN_TIMEOUT_SECONDS,
) -> None:
    stop_polling = getattr(dispatcher, "stop_polling", None)
    if stop_polling is None:
        return
    try:
        await asyncio.wait_for(stop_polling(), timeout=max(0.0, timeout_seconds))
    except TimeoutError:
        LOGGER.error(
            "Telegram polling did not stop within %.1f seconds.",
            timeout_seconds,
        )
    except RuntimeError:
        # aiogram raises when polling has already stopped or never started.
        return
    except Exception:
        LOGGER.exception("Could not stop Telegram polling cleanly.")


async def close_bot_session_best_effort(bot: Bot) -> None:
    session = getattr(bot, "session", None)
    close = getattr(session, "close", None)
    if close is None:
        return
    try:
        await close()
    except Exception:
        LOGGER.exception("Could not close Telegram bot session cleanly.")


async def shutdown_runtime(runtime: BotRuntime) -> None:
    runtime.api_app.state.reminders_restored = False
    if scheduler.running:
        try:
            scheduler.shutdown(wait=True)
        except Exception:
            LOGGER.exception("Could not shut down reminder scheduler cleanly.")

    await close_bot_session_best_effort(runtime.bot)


async def run_polling_and_api_runtime(
    *,
    api_host: str = API_HOST,
    api_port: int = API_PORT,
) -> None:
    configure_application_logging()
    runtime = create_bot_runtime()
    api_server: uvicorn.Server | None = None
    polling_task: asyncio.Task[object] | None = None
    api_task: asyncio.Task[object] | None = None
    tasks: set[asyncio.Task[object]] = set()

    try:
        await prepare_bot_runtime(runtime)
        api_server = create_api_server(
            runtime,
            host=api_host,
            port=api_port,
        )
        polling_task = asyncio.create_task(
            runtime.dispatcher.start_polling(
                runtime.bot,
                handle_signals=False,
            ),
            name="telegram-polling",
        )
        api_task = asyncio.create_task(
            api_server.serve(),
            name="http-api",
        )
        tasks = {polling_task, api_task}

        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        first_error: BaseException | None = None
        for task in done:
            if task.cancelled():
                continue
            error = task.exception()
            if error is not None and first_error is None:
                first_error = error

        shutdown_deadline = (
            asyncio.get_running_loop().time() + RUNTIME_SHUTDOWN_TIMEOUT_SECONDS
        )

        if polling_task in pending:
            await stop_polling_best_effort(
                runtime.dispatcher,
                timeout_seconds=max(
                    0.0,
                    shutdown_deadline - asyncio.get_running_loop().time(),
                ),
            )
        if api_task in pending:
            api_server.should_exit = True

        if pending:
            _finished, still_pending = await asyncio.wait(
                pending,
                timeout=max(
                    0.0,
                    shutdown_deadline - asyncio.get_running_loop().time(),
                ),
            )
            for task in still_pending:
                task.cancel()
            if still_pending:
                await asyncio.gather(*still_pending, return_exceptions=True)

        if first_error is not None:
            raise first_error
    finally:
        if api_server is not None:
            api_server.should_exit = True
        if polling_task is not None and not polling_task.done():
            await stop_polling_best_effort(
                runtime.dispatcher,
                timeout_seconds=RUNTIME_SHUTDOWN_TIMEOUT_SECONDS,
            )
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await shutdown_runtime(runtime)
