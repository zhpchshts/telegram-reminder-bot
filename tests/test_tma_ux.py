from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_tma_asset(name: str) -> str:
    return (PROJECT_ROOT / "tma" / name).read_text(encoding="utf-8")


def test_tma_uses_safe_area_and_stacks_datetime_on_narrow_screens() -> None:
    html = read_tma_asset("index.html")
    styles = read_tma_asset("styles.css")

    assert "viewport-fit=cover" in html
    assert "--app-safe-area-top" in styles
    assert "--tg-content-safe-area-inset-bottom" in styles
    assert "@media (max-width: 420px)" in styles
    assert "#start-at-fields.start-at-grid" in styles
    assert '#start-at-fields .compact-field input[type="time"]' in styles


def test_tma_requests_have_timeout_no_store_and_friendly_error_mapping() -> None:
    javascript = read_tma_asset("app.js")

    assert "new AbortController()" in javascript
    assert 'cache: "no-store"' in javascript
    assert "API_REQUEST_TIMEOUT_MS" in javascript
    assert "window.clearTimeout(timeoutId)" in javascript
    assert "Array.isArray(detail)" in javascript
    assert "Сессия Mini App устарела." in javascript
    assert "Напоминание уже удалено или недоступно." in javascript
    assert "Напоминание изменилось в другом окне." in javascript
    assert "Сервис временно недоступен." in javascript
    assert "Не удалось связаться с сервером." in javascript
    assert "isPotentiallyStateChangingRequest" in javascript
    assert "Изменение могло сохраниться." in javascript
    assert "isTelegramLaunchContextError" in javascript
    assert "Этот запуск Mini App предназначен для другого чата." in javascript
    assert (
        "shouldShowTechnicalDetails = !isTelegramLaunchContextError(error)"
        in javascript
    )


def test_tma_locks_reminder_form_while_preview_or_save_is_pending() -> None:
    html = read_tma_asset("index.html")
    javascript = read_tma_asset("app.js")

    assert 'id="reminder-form-fields"' in html
    assert 'aria-busy="false"' in html
    assert "withReminderFormPending" in javascript
    assert "elements.formFieldset.disabled = true" in javascript
    assert "elements.formFieldset.disabled = false" in javascript
    assert '"Рассчитываем…"' in javascript
    assert '"Сохраняем…"' in javascript
    assert '"Создаём…"' in javascript
    assert "finally" in javascript


def test_tma_preview_and_long_text_ui_are_accessible() -> None:
    html = read_tma_asset("index.html")
    styles = read_tma_asset("styles.css")
    javascript = read_tma_asset("app.js")

    assert 'id="preview"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "buildTextExcerpt" in javascript
    assert "DELETE_CONFIRMATION_EXCERPT_MAX_LENGTH" in javascript
    assert "ACCESSIBLE_REMINDER_EXCERPT_MAX_LENGTH" in javascript
    assert "100dvh" in styles
    assert "overflow-y: auto" in styles
    assert "position: sticky" in styles
    assert "-webkit-line-clamp: 6" in styles


def test_tma_uses_contrast_safe_primary_colors() -> None:
    styles = read_tma_asset("styles.css")

    assert "--primary-bg: #1d64c8" in styles
    assert "--primary-text: #ffffff" in styles
    assert "--primary-bg: #60a5fa" in styles
    assert "--primary-text: #0b1220" in styles
    assert "background: var(--primary-bg)" in styles
    assert "color: var(--primary-text)" in styles


def test_tma_validates_frontend_limits_and_does_not_fake_next_run() -> None:
    html = read_tma_asset("index.html")
    javascript = read_tma_asset("app.js")
    styles = read_tma_asset("styles.css")

    assert "DEFAULT_REMINDER_TEXT_MAX_LENGTH = 3900" in javascript
    assert "DEFAULT_WEATHER_REMINDER_TEXT_MAX_LENGTH = 600" in javascript
    assert "DEFAULT_WEATHER_LOCATION_MAX_LENGTH = 100" in javascript
    assert "DEFAULT_WEATHER_LOCATION_MAX_COUNT = 5" in javascript
    assert '"reminder_text_max_length"' in javascript
    assert '"weather_reminder_text_max_length"' in javascript
    assert '"weather_location_max_length"' in javascript
    assert '"weather_location_max_count"' in javascript
    assert "parseUniqueWeatherLocations" in javascript
    assert "weatherLocations.length > weatherLocationMaxCount" in javascript
    assert "location.length > weatherLocationMaxLength" in javascript
    assert 'id="reminder-text-error"' in html
    assert 'aria-describedby="reminder-text-hint reminder-text-error"' in html
    assert "showReminderTextError(reminderTextErrors[0])" in javascript
    assert ".field-error" in styles
    assert "color: var(--danger-strong)" in styles
    assert 'nextRun.textContent = "Не запланировано"' in javascript
    assert "reminder.next_run_at || reminder.start_at" not in javascript


def test_tma_uses_revision_cas_and_idempotent_create_contract() -> None:
    javascript = read_tma_asset("app.js")

    assert "state.editingReminderRevision = Number(reminder.revision)" in javascript
    assert "payload.expected_revision = state.editingReminderRevision" in javascript
    assert "expected_revision: String(reminder.revision)" in javascript
    assert '"Idempotency-Key": getCreateIdempotencyKey(payload)' in javascript
    assert "window.crypto?.randomUUID" in javascript
    assert "window.crypto?.getRandomValues" in javascript
    assert "Math.random" not in javascript
    assert "state.pendingCreateRequest?.fingerprint !== fingerprint" in javascript
    assert "currentFingerprint !== state.pendingCreateRequest.fingerprint" in javascript
    assert "повтор не создаст дубликат" in javascript
    assert "isReminderCreateRequest(error)" in javascript
    assert "error?.status === 425" in javascript


def test_tma_refreshes_revision_without_losing_edit_draft_on_conflict() -> None:
    javascript = read_tma_asset("app.js")
    handler_start = javascript.index(
        "async function refreshEditingReminderAfterConflict",
    )
    handler_end = javascript.index(
        "async function refreshReminderList",
        handler_start,
    )
    conflict_handler = javascript[handler_start:handler_end]

    assert "await refreshReminderList()" in conflict_handler
    assert 'apiRequest("/api/tma/reminders")' in javascript
    assert "state.reminders = sortReminders(reminders)" in javascript
    assert "state.editingReminderRevision = freshRevision" in conflict_handler
    assert "hidePreview()" in conflict_handler
    assert "markNextNotificationForPreview()" in conflict_handler
    assert "EDIT_CONFLICT_RECOVERED_MESSAGE" in conflict_handler
    assert "resetForm" not in conflict_handler
    assert 'method: "PUT"' not in conflict_handler
    assert 'path === "/api/tma/reminder-preview"' not in conflict_handler
    assert javascript.count("requestWithEditConflictRefresh(") == 3
    assert "Список обновлён — проверь данные и повтори удаление." in javascript
    assert (
        "Черновик сохранён, версия обновлена. Проверь предпросмотр и повтори "
        "сохранение." in javascript
    )
