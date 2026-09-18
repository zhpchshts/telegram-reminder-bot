import os
from pathlib import Path
import sqlite3

import dotenv
import pytest

from app import config, database


def test_database_configuration_uses_current_test_directory(tmp_path: Path) -> None:
    assert database.DB_PATH == tmp_path / "application.sqlite"
    assert config.DB_PATH == database.DB_PATH
    assert Path(os.environ["DB_PATH"]) == database.DB_PATH
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"


def test_dotenv_loading_is_disabled_before_searching_for_files(monkeypatch) -> None:
    def unexpected_lookup(*args, **kwargs):
        pytest.fail("Tests must not search for local dotenv files")

    monkeypatch.setattr(dotenv.main, "find_dotenv", unexpected_lookup)

    assert dotenv.load_dotenv() is False


def test_sqlite_rejects_paths_outside_current_test_directory(tmp_path: Path) -> None:
    unrelated_path = tmp_path.parent / "unexpected-connection.sqlite"

    with pytest.raises(pytest.fail.Exception, match="outside this test"):
        sqlite3.connect(unrelated_path)

    assert not unrelated_path.exists()


def test_sqlite_rejects_uri_paths_before_opening_them(tmp_path: Path) -> None:
    unrelated_path = tmp_path.parent / "unexpected-uri-connection.sqlite"

    with pytest.raises(pytest.fail.Exception, match="outside this test"):
        sqlite3.connect(unrelated_path.as_uri(), uri=True)

    assert not unrelated_path.exists()


def test_sqlite_accepts_temporary_and_in_memory_databases(tmp_path: Path) -> None:
    for target in (tmp_path / "allowed.sqlite", ":memory:"):
        connection = sqlite3.connect(target)
        try:
            assert connection.execute("SELECT 42").fetchone() == (42,)
        finally:
            connection.close()
