import app.main
import app.main_with_api
from app import runtime as runtime_module


def test_main_uses_polling_only_runtime() -> None:
    assert app.main.run_polling_runtime is runtime_module.run_polling_runtime


def test_main_with_api_uses_combined_runtime() -> None:
    assert (
        app.main_with_api.run_polling_and_api_runtime
        is runtime_module.run_polling_and_api_runtime
    )
