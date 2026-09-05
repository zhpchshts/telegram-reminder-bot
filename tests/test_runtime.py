import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
import pytest

from app import handlers
from app import runtime as runtime_module
from app.api_auth import get_tma_launch_context
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

    bind_api_runtime(
        fastapi_app,
        bot=bot,
        bot_token="test-token",
    )

    assert fastapi_app.state.bot is bot
    assert fastapi_app.state.bot_token == "test-token"
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
    assert fastapi_app.state.bot_token == "test-token"
    assert fastapi_app.state.scheduler is runtime_module.scheduler


def test_runtime_token_signs_handler_launch_context_for_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

    class FakeDispatcher:
        def include_router(self, router) -> None:
            pass

    runtime_token = "123456789:runtime-bound-token"
    direct_url = "https://t.me/ZhpchshtsReminderBot?startapp="
    monkeypatch.setattr(runtime_module, "Bot", FakeBot)
    monkeypatch.setattr(runtime_module, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(handlers, "TMA_DIRECT_URL", direct_url)

    fastapi_app = FastAPI()
    runtime = create_bot_runtime(
        bot_token=runtime_token,
        fastapi_app=fastapi_app,
    )
    message = SimpleNamespace(
        bot=runtime.bot,
        chat=SimpleNamespace(id=-100, type="supergroup", title="Home"),
    )

    keyboard = handlers.build_tma_keyboard_for_message(message)

    assert keyboard is not None
    launch_url = keyboard.inline_keyboard[0][0].url
    assert launch_url is not None
    launch_context = get_tma_launch_context(
        SimpleNamespace(
            start_param=launch_url.removeprefix(direct_url),
            chat=None,
        ),
        bot_token=fastapi_app.state.bot_token,
    )
    assert launch_context.chat_id == -100
    assert launch_context.chat_type == "supergroup"
    assert launch_context.chat_title == "Home"


def test_create_bot_runtime_requires_configured_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "BOT_TOKEN", None)

    with pytest.raises(RuntimeError, match="BOT_TOKEN is not set"):
        create_bot_runtime(fastapi_app=FastAPI())


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

        def get_job(self, job_id: str):
            return object()

    async def fake_set_bot_commands(received_bot) -> None:
        calls.append(("set_bot_commands", received_bot))

    async def fake_restore_active_reminders(received_bot) -> None:
        calls.append(("restore_active_reminders", received_bot))

    def fake_schedule_healthcheck(
        *,
        bot,
        chat_id: int,
    ) -> None:
        calls.append(("schedule_healthcheck", bot, chat_id))

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
        ("schedule_healthcheck", bot, 100),
    ]
    assert runtime.api_app.state.reminders_restored is True


def test_prepare_bot_runtime_fails_closed_when_required_worker_is_missing(
    monkeypatch,
) -> None:
    bot = object()

    class FakeScheduler:
        running = True

        def get_job(self, job_id: str):
            if job_id == "completion-occurrence-repeat-worker":
                return None
            return object()

    async def fake_set_bot_commands(received_bot) -> None:
        assert received_bot is bot

    async def fake_restore_active_reminders(received_bot) -> None:
        assert received_bot is bot

    monkeypatch.setattr(runtime_module, "init_db", lambda: None)
    monkeypatch.setattr(runtime_module, "set_bot_commands", fake_set_bot_commands)
    monkeypatch.setattr(
        runtime_module,
        "restore_active_reminders",
        fake_restore_active_reminders,
    )
    monkeypatch.setattr(runtime_module, "scheduler", FakeScheduler())
    monkeypatch.setattr(runtime_module, "HEALTHCHECK_CHAT_ID", None)
    runtime = BotRuntime(
        bot=bot,
        dispatcher=object(),
        api_app=FastAPI(),
    )

    with pytest.raises(
        RuntimeError,
        match="completion-occurrence-repeat-worker",
    ):
        asyncio.run(prepare_bot_runtime(runtime))

    assert runtime.api_app.state.reminders_restored is False


def test_run_polling_and_api_runtime_starts_polling_and_api_server(
    monkeypatch,
) -> None:
    calls = []
    bot = object()

    class FakeDispatcher:
        async def start_polling(
            self,
            received_bot,
            *,
            handle_signals: bool,
        ) -> None:
            calls.append(("start_polling", received_bot, handle_signals))

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
        ("start_polling", bot, False),
        "api_server.serve",
    ]


def test_combined_runtime_stops_polling_when_api_fails(
    monkeypatch,
) -> None:
    calls: list[object] = []
    stop_event = asyncio.Event()

    class FakeDispatcher:
        async def start_polling(
            self,
            received_bot,
            *,
            handle_signals: bool,
        ) -> None:
            calls.append(("polling_started", handle_signals))
            await stop_event.wait()

        async def stop_polling(self) -> None:
            calls.append("polling_stopped")
            stop_event.set()

    class FakeApiServer:
        should_exit = False

        async def serve(self) -> None:
            await asyncio.sleep(0)
            raise RuntimeError("api failed")

    runtime = BotRuntime(
        bot=object(),
        dispatcher=FakeDispatcher(),
        api_app=FastAPI(),
    )
    monkeypatch.setattr(runtime_module, "create_bot_runtime", lambda: runtime)
    monkeypatch.setattr(
        runtime_module,
        "prepare_bot_runtime",
        lambda received_runtime: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_api_server",
        lambda *args, **kwargs: FakeApiServer(),
    )

    async def fake_shutdown_runtime(received_runtime: BotRuntime) -> None:
        calls.append(("runtime_stopped", received_runtime))

    monkeypatch.setattr(runtime_module, "shutdown_runtime", fake_shutdown_runtime)

    with pytest.raises(RuntimeError, match="api failed"):
        asyncio.run(run_polling_and_api_runtime())

    assert ("polling_started", False) in calls
    assert "polling_stopped" in calls
    assert ("runtime_stopped", runtime) in calls


def test_combined_runtime_bounds_stuck_polling_shutdown(monkeypatch) -> None:
    calls: list[object] = []
    never_stops = asyncio.Event()

    class FakeDispatcher:
        async def start_polling(
            self,
            received_bot,
            *,
            handle_signals: bool,
        ) -> None:
            calls.append(("polling_started", handle_signals))
            await never_stops.wait()

        async def stop_polling(self) -> None:
            calls.append("polling_stop_requested")
            await never_stops.wait()

    class FakeApiServer:
        should_exit = False

        async def serve(self) -> None:
            await asyncio.sleep(0)
            raise RuntimeError("api failed")

    runtime = BotRuntime(
        bot=object(),
        dispatcher=FakeDispatcher(),
        api_app=FastAPI(),
    )
    monkeypatch.setattr(runtime_module, "RUNTIME_SHUTDOWN_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(runtime_module, "create_bot_runtime", lambda: runtime)
    monkeypatch.setattr(
        runtime_module,
        "prepare_bot_runtime",
        lambda received_runtime: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_api_server",
        lambda *args, **kwargs: FakeApiServer(),
    )

    async def fake_shutdown_runtime(received_runtime: BotRuntime) -> None:
        calls.append(("runtime_stopped", received_runtime))

    monkeypatch.setattr(runtime_module, "shutdown_runtime", fake_shutdown_runtime)

    with pytest.raises(RuntimeError, match="api failed"):
        asyncio.run(run_polling_and_api_runtime())

    assert "polling_stop_requested" in calls
    assert ("runtime_stopped", runtime) in calls
