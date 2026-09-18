from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_tma_asset(name: str) -> str:
    return (PROJECT_ROOT / "tma" / name).read_text(encoding="utf-8")


def test_auto_delete_switch_has_isolated_checkbox_styles() -> None:
    html = read_tma_asset("index.html")
    styles = read_tma_asset("styles.css")

    assert 'href="./styles.css"' in html
    assert '.auto-delete-switch input[type="checkbox"]' in styles
    assert "appearance: none;" in styles
    assert ".auto-delete-switch input:checked + .auto-delete-switch-track" in styles
    assert (
        ".auto-delete-switch input:focus-visible + .auto-delete-switch-track" in styles
    )
    assert ".auto-delete-help:hover .auto-delete-tooltip" in styles
    assert ".auto-delete-help:focus-within .auto-delete-tooltip" in styles


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
    assert "Автоудаление через 2 суток" in javascript
    assert "Автоудаление после выполнения" in javascript
