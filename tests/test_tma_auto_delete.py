from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_tma_asset(name: str) -> str:
    return (PROJECT_ROOT / "tma" / name).read_text(encoding="utf-8")


def test_auto_delete_checkbox_is_available_for_every_reminder() -> None:
    html = read_tma_asset("index.html")

    assert 'id="delete-after-two-days"' in html
    assert 'name="delete_after_two_days"' in html
    assert 'type="checkbox"' in html
    assert "Удалять через 2 суток" in html
    assert (
        "Бот автоматически удалит отправленное сообщение примерно через два дня."
        in html
    )

    checkbox_position = html.index('id="delete-after-two-days"')
    form_end_position = html.index("</form>", checkbox_position)
    assert checkbox_position < form_end_position


def test_tma_request_edit_reset_and_card_support_auto_delete() -> None:
    javascript = read_tma_asset("app.js")

    assert (
        "delete_after_two_days: Boolean(elements.deleteAfterTwoDays?.checked)"
        in javascript
    )
    assert (
        "elements.deleteAfterTwoDays.checked = Boolean(\n"
        "      reminder.delete_after_two_days,\n"
        "    );" in javascript
    )
    assert "elements.deleteAfterTwoDays.checked = false;" in javascript
    assert "if (reminder.delete_after_two_days)" in javascript
    assert javascript.count("Автоудаление: через 2 суток") >= 2
