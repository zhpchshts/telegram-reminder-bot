import asyncio

from fastapi import FastAPI

from app import runtime as runtime_module
from app.runtime import (
    BotRuntime,
    bind_api_runtime,
    create_api_server,
    create_bot_runtime,
    prepare_bot_runtime,
    run_polling_and_api_runtime,
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
    assert runtime.dispatcher.routers == [
        runtime_module.completion_router,
        runtime_module.router,
    ]
    assert runtime.api_app is fastapi_app
    assert fastapi_app.state.bot is runtime.bot
    assert fastapi_app.state.scheduler is runtime_module.scheduler


def test_create_api_server_uses_runtime_api_app_and_network_settings() -> None:
    runtime = BotRuntime(
        bot=object(),
        dispatcher=object(),
        api_app=FastAPI(),
    )

    server = create_api_server(
        runtime,
        host="127.0.0.1",
        port=9000,
    )

    assert server.config.app is runtime.api_app
    assert server.config.host == "127.0.0.1"
    assert server.config.port == 9000


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


def test_run_polling_and_api_runtime_starts_polling_and_api_server(
    monkeypatch,
) -> None:
    calls = []
    bot = object()

    class FakeDispatcher:
        async def start_polling(self, received_bot) -> None:
            calls.append(("start_polling", received_bot))

    class FakeApiServer:
        async def serve(self) -> None:
            calls.append("api_server.serve")

    runtime = BotRuntime(
        bot=bot,
        dispatcher=FakeDispatcher(),
        api_app=FastAPI(),
    )

    def fake_create_bot_runtime() -> BotRuntime:
        calls.append("create_bot_runtime")
        return runtime

    async def fake_prepare_bot_runtime(received_runtime: BotRuntime) -> None:
        calls.append(("prepare_bot_runtime", received_runtime))

    def fake_create_api_server(
        received_runtime: BotRuntime,
        *,
        host: str,
        port: int,
    ) -> FakeApiServer:
        calls.append(("create_api_server", received_runtime, host, port))
        return FakeApiServer()

    monkeypatch.setattr(
        runtime_module,
        "create_bot_runtime",
        fake_create_bot_runtime,
    )
    monkeypatch.setattr(
        runtime_module,
        "prepare_bot_runtime",
        fake_prepare_bot_runtime,
    )
    monkeypatch.setattr(
        runtime_module,
        "create_api_server",
        fake_create_api_server,
    )

    asyncio.run(
        run_polling_and_api_runtime(
            api_host="127.0.0.1",
            api_port=9000,
        )
    )

    assert calls == [
        "create_bot_runtime",
        ("prepare_bot_runtime", runtime),
        ("create_api_server", runtime, "127.0.0.1", 9000),
        ("start_polling", bot),
        "api_server.serve",
    ]
