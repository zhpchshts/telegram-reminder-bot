"""Keep collection and test execution independent of local runtime settings."""

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory, gettempdir

import pytest


# Configure the process before test modules import app.config or load dotenv.
_bootstrap_directory = TemporaryDirectory(prefix="nezabudka-pytest-")
_bootstrap_path = Path(_bootstrap_directory.name).resolve()
os.environ.update(
    PYTHON_DOTENV_DISABLED="1",
    BOT_TOKEN="123456789:synthetic-test-token",
    DB_PATH=str(_bootstrap_path / "collection.sqlite"),
    APP_TIMEZONE="Asia/Yekaterinburg",
    HEALTHCHECK_CHAT_ID="",
    API_HOST="127.0.0.1",
    API_PORT="8000",
    API_ALLOWED_ORIGINS="",
    TMA_BOT_USERNAME="SyntheticReminderTestBot",
    TMA_DIRECT_URL="https://t.me/SyntheticReminderTestBot?startapp=",
)

_allowed_database_directory = _bootstrap_path
_database_guard_enabled = True


def _guard_sqlite_connection(event: str, args: tuple[object, ...]) -> None:
    if event != "sqlite3.connect" or not _database_guard_enabled:
        return
    database = os.fsdecode(args[0])
    if database in ("", ":memory:"):
        return
    # SQLite URI filenames are unnecessary in this suite; reject them rather
    # than let a URI bypass the path check. The audit event precedes file access.
    if database.startswith("file:") or not Path(database).resolve().is_relative_to(
        _allowed_database_directory
    ):
        pytest.fail("SQLite connection outside this test's temporary directory")


sys.addaudithook(_guard_sqlite_connection)


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app import config, database

    global _allowed_database_directory
    previous_directory = _allowed_database_directory
    _allowed_database_directory = tmp_path.resolve()
    database_path = tmp_path / "application.sqlite"
    monkeypatch.setenv("DB_PATH", str(database_path))
    monkeypatch.setattr(config, "DB_PATH", database_path)
    monkeypatch.setattr(database, "DB_PATH", database_path)
    try:
        yield database_path
    finally:
        _allowed_database_directory = previous_directory


def pytest_unconfigure() -> None:
    global _database_guard_enabled
    _database_guard_enabled = False
    assert _bootstrap_path.parent == Path(gettempdir()).resolve()
    assert _bootstrap_path.name.startswith("nezabudka-pytest-")
    _bootstrap_directory.cleanup()
