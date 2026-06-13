const telegram = window.Telegram?.WebApp;

const initData = getTelegramInitData();
const DEFAULT_START_OFFSET_MINUTES = 5;

function getTelegramInitData() {
  const sdkInitData = telegram?.initData || "";

  if (sdkInitData) {
    return sdkInitData;
  }

  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  const hashParams = new URLSearchParams(hash);
  const searchParams = new URLSearchParams(window.location.search);

  return (
    hashParams.get("tgWebAppData") ||
    searchParams.get("tgWebAppData") ||
    ""
  );
}

function buildMissingInitDataMessage() {
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  const hashParams = new URLSearchParams(hash);
  const searchParams = new URLSearchParams(window.location.search);

  return [
    "Telegram initData не найден.",
    "",
    "Открой Mini App именно через кнопку /app в Telegram, а не прямой ссылкой в браузере.",
    "",
    `Debug: WebApp=${telegram ? "yes" : "no"}, platform=${telegram?.platform || "unknown"}, version=${telegram?.version || "unknown"}, hash_has_tgWebAppData=${hashParams.has("tgWebAppData") ? "yes" : "no"}, search_has_tgWebAppData=${searchParams.has("tgWebAppData") ? "yes" : "no"}`,
  ].join("\n");
}

function getDeviceTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

const state = {
  context: null,
  reminderOptions: null,
  reminders: [],
  isBusy: false,
};

const elements = {
  chatTitle: document.querySelector("#chat-title"),
  status: document.querySelector("#status"),

  deviceTimezoneBlock: document.querySelector("#device-timezone-block"),
  deviceTimezoneName: document.querySelector("#device-timezone-name"),
  useDeviceTimezoneButton: document.querySelector("#use-device-timezone-button"),

  timezoneForm: document.querySelector("#timezone-form"),
  chatTimezoneName: document.querySelector("#chat-timezone-name"),
  timezoneSaveButton: document.querySelector("#timezone-save-button"),

  reloadButton: document.querySelector("#reload-button"),

  form: document.querySelector("#reminder-form"),
  formTitle: document.querySelector("#form-title"),
  reminderId: document.querySelector("#reminder-id"),
  reminderText: document.querySelector("#reminder-text"),
  scheduleType: document.querySelector("#schedule-type"),
  startAt: document.querySelector("#start-at"),
  startAtHint: document.querySelector("#start-at-hint"),
  startAtError: document.querySelector("#start-at-error"),
  timezoneName: document.querySelector("#timezone-name"),
  intervalDays: document.querySelector("#interval-days"),
  intervalWeeks: document.querySelector("#interval-weeks"),
  dayOfWeek: document.querySelector("#day-of-week"),
  monthDayOfWeek: document.querySelector("#month-day-of-week"),
  monthWeekNumber: document.querySelector("#month-week-number"),
  monthDay: document.querySelector("#month-day"),

  intervalDaysField: document.querySelector("#interval-days-field"),
  weeklyFields: document.querySelector("#weekly-fields"),
  monthlyWeekdayFields: document.querySelector("#monthly-weekday-fields"),
  monthDayField: document.querySelector("#month-day-field"),

  preview: document.querySelector("#preview"),
  previewButton: document.querySelector("#preview-button"),
  saveButton: document.querySelector("#save-button"),
  cancelEditButton: document.querySelector("#cancel-edit-button"),
  remindersList: document.querySelector("#reminders-list"),
};

function showStatus(message, type = "success") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`;
  elements.status.hidden = false;
}

function hideStatus() {
  elements.status.hidden = true;
  elements.status.textContent = "";
  elements.status.className = "status";
}

function showStartAtError(message) {
  elements.startAtError.textContent = message;
  elements.startAtError.hidden = false;
  elements.startAt.setAttribute("aria-invalid", "true");
}

function clearStartAtError() {
  elements.startAtError.textContent = "";
  elements.startAtError.hidden = true;
  elements.startAt.removeAttribute("aria-invalid");
}

function clearFieldErrors() {
  clearStartAtError();
}

function focusStartAtField() {
  elements.startAt.scrollIntoView({
    behavior: "smooth",
    block: "center",
  });
  elements.startAt.focus();
}

function buildStartAtPastMessage() {
  const timezoneName = elements.timezoneName.value || state.context?.timezone_name;

  return `Время срабатывания уже прошло в таймзоне чата ${timezoneName}. Выбери более позднее время.`;
}

function isStartAtPastError(error) {
  return error.message === "start_at must be in the future.";
}

function handleError(error) {
  if (isStartAtPastError(error)) {
    hideStatus();
    showStartAtError(buildStartAtPastMessage());
    focusStartAtField();
    return;
  }

  showStatus(error.message, "error");
}

function setBusy(isBusy) {
  state.isBusy = isBusy;

  for (const button of document.querySelectorAll("button")) {
    if (button.hasAttribute("data-modal-button")) {
      continue;
    }

    button.disabled = isBusy;
  }
}

function showPreview(preview) {
  const period = preview.period || "одноразовое";
  const timezoneName = preview.timezone_name || state.context?.timezone_name;
  const formattedStartAt = formatDateTime(preview.start_at, timezoneName);

  elements.preview.innerHTML = `
    <strong>Предпросмотр</strong>
    <div>${escapeHtml(preview.reminder_text)}</div>
    <div class="muted">${escapeHtml(period)}</div>
    <div class="muted">Первое срабатывание: ${escapeHtml(formattedStartAt)} · ${escapeHtml(timezoneName)}</div>
  `;
  elements.preview.hidden = false;
}

function hidePreview() {
  elements.preview.hidden = true;
  elements.preview.textContent = "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function apiRequest(path, options = {}) {
  if (!initData) {
    throw new Error(buildMissingInitDataMessage());
  }

  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData,
      ...(options.headers || {}),
    },
  });

  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = typeof body === "object" ? body.detail : body;
    throw new Error(detail || `HTTP ${response.status}`);
  }

  return body;
}

async function loadBootstrap() {
  hideStatus();
  hidePreview();
  clearFieldErrors();

  const bootstrap = await apiRequest("/api/tma/bootstrap");

  state.context = bootstrap.context;
  state.reminderOptions = bootstrap.reminder_options;
  state.reminders = sortReminders(bootstrap.active_reminders);

  renderContext();
  renderDeviceTimezoneSuggestion();
  renderOptions();
  renderReminders();
  setDefaultStartAtIfEmpty();
}

function renderContext() {
  const chat = state.context?.chat;
  const title = chat?.title || chat?.type || "Telegram chat";

  elements.chatTitle.textContent = `${title} · ${state.context.timezone_name}`;
  elements.chatTimezoneName.value = state.context.timezone_name;
  elements.timezoneName.value = state.context.timezone_name;
  renderStartAtHint();
}

function renderStartAtHint() {
  const timezoneName = elements.timezoneName.value || state.context?.timezone_name;

  elements.startAtHint.textContent = `Время указывается в таймзоне чата: ${timezoneName}.`;
}

function renderDeviceTimezoneSuggestion() {
  const deviceTimezone = getDeviceTimezone();

  if (!deviceTimezone) {
    elements.deviceTimezoneBlock.hidden = true;
    elements.deviceTimezoneName.textContent = "";
    return;
  }

  elements.deviceTimezoneName.textContent = deviceTimezone;
  elements.deviceTimezoneBlock.hidden = false;

  const isCurrentTimezone = deviceTimezone === state.context?.timezone_name;
  elements.useDeviceTimezoneButton.textContent = isCurrentTimezone
    ? "Таймзона устройства уже используется"
    : "Использовать таймзону устройства";
}

function renderOptions() {
  fillSelect(
    elements.dayOfWeek,
    state.reminderOptions.weekdays,
    "Не выбрано",
  );

  fillSelect(
    elements.monthDayOfWeek,
    state.reminderOptions.weekdays,
    "Не выбрано",
  );

  fillSelect(
    elements.monthWeekNumber,
    state.reminderOptions.month_week_numbers.map((value) => ({
      value,
      label: `${value}`,
    })),
    "Не выбрано",
  );

  fillSelect(
    elements.monthDay,
    state.reminderOptions.month_days.map((value) => ({
      value,
      label: `${value}`,
    })),
    "Не выбрано",
  );

  updateConditionalFields();
}

function fillSelect(select, options, emptyLabel) {
  select.replaceChildren();

  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = emptyLabel;
  select.append(emptyOption);

  for (const option of options) {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label;
    select.append(element);
  }
}

function renderReminders() {
  elements.remindersList.replaceChildren();

  if (!state.reminders.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Активных напоминаний пока нет.";
    elements.remindersList.append(empty);
    return;
  }

  for (const reminder of state.reminders) {
    elements.remindersList.append(createReminderCard(reminder));
  }
}

function createReminderCard(reminder) {
  const card = document.createElement("article");
  card.className = "reminder-card";

  const title = document.createElement("h3");
  title.textContent = reminder.reminder_text;

  const timezoneName = reminder.timezone_name || state.context?.timezone_name;
  const formattedNextRunAt = formatDateTime(
    reminder.next_run_at || reminder.start_at,
    timezoneName,
  );

  const meta = document.createElement("div");
  meta.className = "reminder-meta";
  meta.innerHTML = `
    <span>${escapeHtml(reminder.period || "одноразовое")}</span>
    <span>Следующее: ${escapeHtml(formattedNextRunAt)} · ${escapeHtml(timezoneName)}</span>
  `;

  const actions = document.createElement("div");
  actions.className = "reminder-actions";

  const editButton = document.createElement("button");
  editButton.className = "secondary-button";
  editButton.type = "button";
  editButton.textContent = "Изменить";
  editButton.addEventListener("click", () => startEdit(reminder));

  const deleteButton = document.createElement("button");
  deleteButton.className = "danger-button";
  deleteButton.type = "button";
  deleteButton.textContent = "Удалить";
  deleteButton.addEventListener("click", () =>
    handleAsync(() => deleteReminder(reminder)),
  );

  actions.append(editButton, deleteButton);
  card.append(title, meta, actions);

  return card;
}

function sortReminders(reminders) {
  return [...reminders].sort((left, right) => {
    const leftTime = getReminderSortTime(left);
    const rightTime = getReminderSortTime(right);

    if (leftTime !== rightTime) {
      return leftTime - rightTime;
    }

    return Number(left.id) - Number(right.id);
  });
}

function getReminderSortTime(reminder) {
  const value = reminder.next_run_at || reminder.start_at;

  if (!value) {
    return Number.POSITIVE_INFINITY;
  }

  const time = new Date(value).getTime();

  if (Number.isNaN(time)) {
    return Number.POSITIVE_INFINITY;
  }

  return time;
}

function updateConditionalFields() {
  const type = elements.scheduleType.value;

  elements.intervalDaysField.hidden = type !== "every_days";
  elements.weeklyFields.hidden = type !== "every_week";
  elements.monthlyWeekdayFields.hidden = type !== "monthly_weekday";
  elements.monthDayField.hidden = type !== "monthly_day";
}

function buildRequestPayload() {
  const scheduleType = elements.scheduleType.value;

  const payload = {
    reminder_text: elements.reminderText.value.trim(),
    schedule_type: scheduleType,
    start_at: elements.startAt.value,
    timezone_name: elements.timezoneName.value.trim(),
    interval_days: null,
    interval_weeks: null,
    day_of_week: null,
    month_week_number: null,
    month_day: null,
  };

  if (scheduleType === "every_days") {
    payload.interval_days = numberOrNull(elements.intervalDays.value);
  }

  if (scheduleType === "every_week") {
    payload.interval_weeks = numberOrNull(elements.intervalWeeks.value);
    payload.day_of_week = elements.dayOfWeek.value || null;
  }

  if (scheduleType === "monthly_weekday") {
    payload.month_week_number = numberOrNull(elements.monthWeekNumber.value);
    payload.day_of_week = elements.monthDayOfWeek.value || null;
  }

  if (scheduleType === "monthly_day") {
    payload.month_day = numberOrNull(elements.monthDay.value);
  }

  return payload;
}

function numberOrNull(value) {
  if (value === "") {
    return null;
  }

  return Number(value);
}

function isPositiveIntegerValue(value) {
  if (value === "") {
    return false;
  }

  const number = Number(value);

  return Number.isInteger(number) && number >= 1;
}

function hasStartAtValue() {
  return Boolean(elements.startAt.value);
}

function validateTimezoneForm() {
  if (!elements.chatTimezoneName.value.trim()) {
    showStatus("Укажи таймзону чата.", "error");
    return false;
  }

  return true;
}

function validateReminderForm() {
  const errors = [];
  const scheduleType = elements.scheduleType.value;

  clearFieldErrors();

  if (!elements.reminderText.value.trim()) {
    errors.push("Укажи текст напоминания.");
  }

  if (!hasStartAtValue()) {
    showStartAtError("Укажи первое срабатывание.");
  }

  if (!elements.timezoneName.value.trim()) {
    errors.push("Укажи таймзону чата.");
  }

  if (
    scheduleType === "every_days" &&
    !isPositiveIntegerValue(elements.intervalDays.value)
  ) {
    errors.push("Для расписания «Каждые N дней» укажи интервал в днях.");
  }

  if (scheduleType === "every_week") {
    if (!isPositiveIntegerValue(elements.intervalWeeks.value)) {
      errors.push("Для расписания «Каждые N недель» укажи интервал в неделях.");
    }

    if (!elements.dayOfWeek.value) {
      errors.push("Для расписания «Каждые N недель» выбери день недели.");
    }
  }

  if (scheduleType === "monthly_weekday") {
    if (!elements.monthWeekNumber.value) {
      errors.push("Для расписания по дню недели месяца выбери неделю месяца.");
    }

    if (!elements.monthDayOfWeek.value) {
      errors.push("Для расписания по дню недели месяца выбери день недели.");
    }
  }

  if (scheduleType === "monthly_day" && !elements.monthDay.value) {
    errors.push("Для расписания по дню месяца выбери день месяца.");
  }

  if (!hasStartAtValue()) {
    hideStatus();
    focusStartAtField();
    return false;
  }

  if (errors.length) {
    showStatus(errors.join("\n"), "error");
    return false;
  }

  return true;
}

function setDefaultStartAtIfEmpty() {
  if (!elements.startAt.value) {
    setDefaultStartAt();
  }
}

function setDefaultStartAt() {
  const date = new Date();
  date.setMinutes(date.getMinutes() + DEFAULT_START_OFFSET_MINUTES);
  date.setSeconds(0, 0);

  elements.startAt.value = toDateTimeLocalValue(
    date,
    state.context?.timezone_name,
  );
}

function startEdit(reminder) {
  const timezoneName = reminder.timezone_name || state.context?.timezone_name;

  elements.reminderId.value = reminder.id;
  elements.formTitle.textContent = "Редактировать напоминание";
  elements.reminderText.value = reminder.reminder_text;
  elements.scheduleType.value = reminder.schedule_type;
  elements.startAt.value = toDateTimeLocalValue(reminder.start_at, timezoneName);
  elements.timezoneName.value = reminder.timezone_name;
  elements.intervalDays.value = reminder.interval_days || "";
  elements.intervalWeeks.value = reminder.interval_weeks || "";
  elements.dayOfWeek.value = reminder.day_of_week || "";
  elements.monthDayOfWeek.value = reminder.day_of_week || "";
  elements.monthWeekNumber.value = reminder.month_week_number || "";
  elements.monthDay.value = reminder.month_day || "";
  elements.saveButton.textContent = "Сохранить изменения";
  elements.cancelEditButton.hidden = false;

  hidePreview();
  clearFieldErrors();
  updateConditionalFields();
  renderStartAtHint();
  showStatus(
    "Редактируешь напоминание.\nВнеси изменения и нажми «Сохранить изменения».",
  );

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetForm() {
  elements.form.reset();
  elements.reminderId.value = "";
  elements.formTitle.textContent = "Создать напоминание";
  elements.timezoneName.value = state.context?.timezone_name || "";
  setDefaultStartAt();
  elements.saveButton.textContent = "Сохранить";
  elements.cancelEditButton.hidden = true;

  hideStatus();
  hidePreview();
  clearFieldErrors();
  updateConditionalFields();
  renderStartAtHint();
}

async function previewReminder() {
  hideStatus();
  hidePreview();

  if (!validateReminderForm()) {
    return;
  }

  const preview = await apiRequest("/api/tma/reminder-preview", {
    method: "POST",
    body: JSON.stringify(buildRequestPayload()),
  });

  showPreview(preview);
}

async function saveTimezone(statusMessage = "Таймзона чата обновлена.") {
  hideStatus();

  if (!validateTimezoneForm()) {
    return;
  }

  const timezoneName = elements.chatTimezoneName.value.trim();

  const timezone = await apiRequest("/api/tma/timezone", {
    method: "PUT",
    body: JSON.stringify({
      timezone_name: timezoneName,
    }),
  });

  state.context.timezone_name = timezone.timezone_name;
  elements.timezoneName.value = timezone.timezone_name;
  elements.chatTimezoneName.value = timezone.timezone_name;

  renderContext();
  renderDeviceTimezoneSuggestion();
  resetForm();
  showStatus(statusMessage);
}

async function useDeviceTimezone() {
  const deviceTimezone = getDeviceTimezone();

  if (!deviceTimezone) {
    showStatus("Не удалось определить таймзону устройства.", "error");
    return;
  }

  elements.chatTimezoneName.value = deviceTimezone;
  await saveTimezone("Таймзона устройства применена для этого чата.");
}

async function saveReminder() {
  hideStatus();
  hidePreview();

  if (!validateReminderForm()) {
    return;
  }

  const reminderId = elements.reminderId.value;
  const isEdit = Boolean(reminderId);
  const path = isEdit
    ? `/api/tma/reminders/${reminderId}`
    : "/api/tma/reminders";
  const method = isEdit ? "PUT" : "POST";

  await apiRequest(path, {
    method,
    body: JSON.stringify(buildRequestPayload()),
  });

  resetForm();
  await loadBootstrap();
  showStatus(isEdit ? "Напоминание обновлено." : "Напоминание создано.");
}

function showDeleteConfirmation(reminder) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-backdrop";

    const dialog = document.createElement("section");
    dialog.className = "modal-card";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "delete-confirmation-title");

    const title = document.createElement("h2");
    title.id = "delete-confirmation-title";
    title.textContent = "Удалить напоминание?";

    const text = document.createElement("p");
    text.className = "modal-text";
    text.textContent = reminder.reminder_text;

    const actions = document.createElement("div");
    actions.className = "modal-actions";

    const cancelButton = document.createElement("button");
    cancelButton.className = "secondary-button";
    cancelButton.type = "button";
    cancelButton.textContent = "Отменить";
    cancelButton.setAttribute("data-modal-button", "");

    const confirmButton = document.createElement("button");
    confirmButton.className = "danger-button";
    confirmButton.type = "button";
    confirmButton.textContent = "Удалить";
    confirmButton.setAttribute("data-modal-button", "");

    function close(result) {
      document.removeEventListener("keydown", handleKeyDown);
      overlay.remove();
      resolve(result);
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        close(false);
      }
    }

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) {
        close(false);
      }
    });

    cancelButton.addEventListener("click", () => close(false));
    confirmButton.addEventListener("click", () => close(true));
    document.addEventListener("keydown", handleKeyDown);

    actions.append(cancelButton, confirmButton);
    dialog.append(title, text, actions);
    overlay.append(dialog);
    document.body.append(overlay);

    cancelButton.focus();
  });
}

async function deleteReminder(reminder) {
  hideStatus();

  const confirmed = await showDeleteConfirmation(reminder);

  if (!confirmed) {
    return;
  }

  await apiRequest(`/api/tma/reminders/${reminder.id}`, {
    method: "DELETE",
  });

  await loadBootstrap();
  showStatus("Напоминание удалено.");
}

function formatDateTime(value, timezoneName) {
  if (!value) {
    return "не запланировано";
  }

  const localValue = toDateTimeLocalValue(value, timezoneName);

  if (!localValue) {
    return "некорректная дата";
  }

  const [datePart, timePart] = localValue.split("T");
  const [year, month, day] = datePart.split("-");

  return `${day}.${month}.${year}, ${timePart}`;
}

function toDateTimeLocalValue(value, timezoneName) {
  if (typeof value === "string" && isDatetimeLocalValue(value)) {
    return value.slice(0, 16);
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  if (!timezoneName) {
    return toBrowserDateTimeLocalValue(date);
  }

  try {
    return toTimezoneDateTimeLocalValue(date, timezoneName);
  } catch {
    return toBrowserDateTimeLocalValue(date);
  }
}

function isDatetimeLocalValue(value) {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value) &&
    !/(Z|[+-]\d{2}:?\d{2})$/i.test(value);
}

function toBrowserDateTimeLocalValue(date) {
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;

  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function toTimezoneDateTimeLocalValue(date, timezoneName) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezoneName,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    hourCycle: "h23",
  }).formatToParts(date);

  const values = Object.fromEntries(
    parts
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );

  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`;
}

async function handleAsync(action) {
  if (state.isBusy) {
    return;
  }

  setBusy(true);

  try {
    await action();
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

elements.reloadButton.addEventListener("click", () => handleAsync(loadBootstrap));
elements.startAt.addEventListener("input", clearStartAtError);
elements.scheduleType.addEventListener("change", updateConditionalFields);
elements.previewButton.addEventListener("click", () => handleAsync(previewReminder));
elements.useDeviceTimezoneButton.addEventListener("click", () =>
  handleAsync(useDeviceTimezone),
);

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  handleAsync(saveReminder);
});

elements.cancelEditButton.addEventListener("click", resetForm);

elements.timezoneForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleAsync(saveTimezone);
});

telegram?.ready();
telegram?.expand();

handleAsync(loadBootstrap);