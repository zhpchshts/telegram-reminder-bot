import runpy

import app.main_with_api
from app import runtime as runtime_module


def test_main_with_api_uses_combined_runtime() -> None:
    assert (
        app.main_with_api.run_polling_and_api_runtime
        is runtime_module.run_polling_and_api_runtime
    )


def test_main_with_api_runs_combined_runtime_when_executed(monkeypatch) -> None:
    calls = []

    async def fake_run_polling_and_api_runtime() -> None:
        calls.append("combined runtime")

    monkeypatch.setattr(
        runtime_module,
        "run_polling_and_api_runtime",
        fake_run_polling_and_api_runtime,
    )

    runpy.run_path(app.main_with_api.__file__, run_name="__main__")

    assert calls == ["combined runtime"]
