from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_tma_asset(name: str) -> str:
    return (PROJECT_ROOT / "tma" / name).read_text(encoding="utf-8")


def test_completion_controls_are_available_in_reminder_form() -> None:
    html = read_tma_asset("index.html")

    assert 'id="requires-completion"' in html
    assert 'name="requires_completion"' in html
    assert 'id="completion-repeat-interval"' in html
    assert "Повторять до выполнения" in html
    assert "Бот будет поднимать напоминание, заменяя предыдущую копию." in html
    assert 'src="./app.js"' in html


def test_tma_completion_request_edit_reset_and_card_use_backend_contract() -> None:
    javascript = read_tma_asset("app.js")

    assert "state.reminderOptions.completion_repeat_intervals || []" in javascript
    assert "state.reminderOptions?.completion_reminder_text_max_length" in javascript
    assert (
        "requires_completion: Boolean(elements.requiresCompletion?.checked)"
        in javascript
    )
    assert "repeat_interval_minutes: elements.requiresCompletion?.checked" in javascript
    assert "Boolean(reminder.requires_completion)" in javascript
    assert "reminder.repeat_interval_minutes" in javascript
    assert "elements.requiresCompletion.checked = false;" in javascript
    assert "reminder.awaiting_completion" in javascript
    assert "Ожидает выполнения" in javascript


def test_tma_completion_and_auto_delete_are_compatible() -> None:
    javascript = read_tma_asset("app.js")

    assert (
        "elements.requiresCompletion.checked && elements.deleteAfterTwoDays"
        not in javascript
    )
    assert (
        "elements.deleteAfterTwoDays.checked && elements.requiresCompletion"
        not in javascript
    )
    assert "Автоудаление после выполнения" in javascript
    assert (
        "После выполнения сообщение будет удалено примерно через два дня." in javascript
    )
