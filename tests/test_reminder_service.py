import pytest

from app import reminder_service as reminder_service_module
from app.reminder_service import (
    build_active_reminders_list_text_for_chat,
    delete_active_reminder_for_chat,
)


class FakeScheduler:
    def __init__(self, job: object | None) -> None:
        self.job = job
        self.get_job_ids: list[str] = []
        self.removed_job_ids: list[str] = []

    def get_job(self, job_id: str) -> object | None:
        self.get_job_ids.append(job_id)
        return self.job

    def remove_job(self, job_id: str) -> None:
        self.removed_job_ids.append(job_id)


def patch_reminder_lookup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reminder: object | None,
    deleted_ids: list[int],
) -> None:
    def fake_get_active_reminder_for_chat(
        *,
        reminder_id: int,
        chat_id: int,
    ) -> object | None:
        return reminder

    def fake_mark_reminder_as_deleted(reminder_id: int) -> None:
        deleted_ids.append(reminder_id)

    monkeypatch.setattr(
        reminder_service_module,
        "get_active_reminder_for_chat",
        fake_get_active_reminder_for_chat,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "mark_reminder_as_deleted",
        fake_mark_reminder_as_deleted,
    )


def test_delete_active_reminder_for_chat_returns_false_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler(job=object())
    deleted_ids: list[int] = []

    monkeypatch.setattr(reminder_service_module, "scheduler", fake_scheduler)
    patch_reminder_lookup(monkeypatch, reminder=None, deleted_ids=deleted_ids)

    result = delete_active_reminder_for_chat(reminder_id=42, chat_id=100)

    assert result is False
    assert fake_scheduler.get_job_ids == []
    assert fake_scheduler.removed_job_ids == []
    assert deleted_ids == []


def test_delete_active_reminder_for_chat_removes_job_and_marks_deleted_when_job_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler(job=object())
    deleted_ids: list[int] = []

    monkeypatch.setattr(reminder_service_module, "scheduler", fake_scheduler)
    patch_reminder_lookup(monkeypatch, reminder=object(), deleted_ids=deleted_ids)

    result = delete_active_reminder_for_chat(reminder_id=42, chat_id=100)

    assert result is True
    assert fake_scheduler.get_job_ids == ["42"]
    assert fake_scheduler.removed_job_ids == ["42"]
    assert deleted_ids == [42]


def test_delete_active_reminder_for_chat_marks_deleted_when_job_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler(job=None)
    deleted_ids: list[int] = []

    monkeypatch.setattr(reminder_service_module, "scheduler", fake_scheduler)
    patch_reminder_lookup(monkeypatch, reminder=object(), deleted_ids=deleted_ids)

    result = delete_active_reminder_for_chat(reminder_id=42, chat_id=100)

    assert result is True
    assert fake_scheduler.get_job_ids == ["42"]
    assert fake_scheduler.removed_job_ids == []
    assert deleted_ids == [42]


def test_build_active_reminders_list_text_for_chat_returns_none_when_no_reminders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_active_reminders_for_chat(chat_id: int) -> list[object]:
        return []

    def fake_format_next_run_line(reminder_id: int) -> str:
        raise AssertionError("format_next_run_line should not be called")

    def fake_format_reminder_for_list(
        reminder: object,
        next_run_line: str,
    ) -> str:
        raise AssertionError("format_reminder_for_list should not be called")

    monkeypatch.setattr(
        reminder_service_module,
        "get_active_reminders_for_chat",
        fake_get_active_reminders_for_chat,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_next_run_line",
        fake_format_next_run_line,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_reminder_for_list",
        fake_format_reminder_for_list,
    )

    result = build_active_reminders_list_text_for_chat(chat_id=100)

    assert result is None


def test_build_active_reminders_list_text_for_chat_returns_formatted_reminders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reminders = [
        {"id": 1},
        {"id": 2},
    ]
    requested_chat_ids: list[int] = []
    next_run_ids: list[int] = []
    formatted_reminders: list[tuple[int, str]] = []

    def fake_get_active_reminders_for_chat(chat_id: int) -> list[dict[str, int]]:
        requested_chat_ids.append(chat_id)
        return reminders

    def fake_format_next_run_line(reminder_id: int) -> str:
        next_run_ids.append(reminder_id)
        return f"next {reminder_id}"

    def fake_format_reminder_for_list(
        reminder: dict[str, int],
        next_run_line: str,
    ) -> str:
        formatted_reminders.append((reminder["id"], next_run_line))
        return f"reminder {reminder['id']} / {next_run_line}"

    monkeypatch.setattr(
        reminder_service_module,
        "get_active_reminders_for_chat",
        fake_get_active_reminders_for_chat,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_next_run_line",
        fake_format_next_run_line,
    )
    monkeypatch.setattr(
        reminder_service_module,
        "format_reminder_for_list",
        fake_format_reminder_for_list,
    )

    result = build_active_reminders_list_text_for_chat(chat_id=100)

    assert result == (
        "Активные напоминания в этом чате\n"
        "\n\n"
        "reminder 1 / next 1"
        "\n\n"
        "reminder 2 / next 2"
    )
    assert requested_chat_ids == [100]
    assert next_run_ids == [1, 2]
    assert formatted_reminders == [
        (1, "next 1"),
        (2, "next 2"),
    ]
