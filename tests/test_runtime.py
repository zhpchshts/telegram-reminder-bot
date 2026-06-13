import asyncio

from fastapi import FastAPI

from app import runtime as runtime_module
from app.runtime import (
    BotRuntime,
    bind_api_runtime,
    create_bot_runtime,
    prepare_bot_runtime,
)


def test_bind_api_runtime_stores_shared_bot_and_scheduler() -> None:
    fastapi_app = FastAPI()
    bot = object()

    bind_api_runtime(fastapi_app, bot=bot)

    assert fastapi_app.state.bot is bot
    assert fastapi_app.state.scheduler is runtime_module.scheduler


def test_create_bot_runtime_builds_polling_and_api_context(
    monkeypatch,
) -> None:
    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

    class FakeDispatcher:
        def __init__(self) -> None:
            self.routers = []

        def include_router(self, router) -> None:
            self.routers.append(router)

    monkeypatch.setattr(runtime_module, "Bot", FakeBot)
    monkeypatch.setattr(runtime_module, "Dispatcher", FakeDispatcher)

    fastapi_app = FastAPI()

    runtime = create_bot_runtime(
        bot_token="test-token",
        fastapi_app=fastapi_app,
    )

    assert runtime.bot.token == "test-token"
    assert runtime.dispatcher.routers == [runtime_module.router]
    assert runtime.api_app is fastapi_app
    assert fastapi_app.state.bot is runtime.bot
    assert fastapi_app.state.scheduler is runtime_module.scheduler


def test_prepare_bot_runtime_starts_shared_scheduler_and_restores_jobs(
    monkeypatch,
) -> None:
    calls = []
    bot = object()

    class FakeScheduler:
        running = False

        def start(self) -> None:
            self.running = True
            calls.append("scheduler.start")

    async def fake_set_bot_commands(received_bot) -> None:
        calls.append(("set_bot_commands", received_bot))

    async def fake_restore_active_reminders(received_bot) -> None:
        calls.append(("restore_active_reminders", received_bot))

    def fake_schedule_healthcheck(
        *,
        bot,
        chat_id: int,
        interval_minutes: int,
    ) -> None:
        calls.append(("schedule_healthcheck", bot, chat_id, interval_minutes))

    monkeypatch.setattr(runtime_module, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(runtime_module, "set_bot_commands", fake_set_bot_commands)
    monkeypatch.setattr(
        runtime_module,
        "restore_active_reminders",
        fake_restore_active_reminders,
    )
    monkeypatch.setattr(
        runtime_module,
        "schedule_healthcheck",
        fake_schedule_healthcheck,
    )
    monkeypatch.setattr(runtime_module, "scheduler", FakeScheduler())
    monkeypatch.setattr(runtime_module, "HEALTHCHECK_CHAT_ID", 100)
    monkeypatch.setattr(runtime_module, "HEALTHCHECK_INTERVAL_MINUTES", 360)

    runtime = BotRuntime(
        bot=bot,
        dispatcher=object(),
        api_app=FastAPI(),
    )

    asyncio.run(prepare_bot_runtime(runtime))

    assert calls == [
        "init_db",
        ("set_bot_commands", bot),
        "scheduler.start",
        ("restore_active_reminders", bot),
        ("schedule_healthcheck", bot, 100, 360),
    ]
