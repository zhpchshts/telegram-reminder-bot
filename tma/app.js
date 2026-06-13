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
const state = {
  context: null,
  reminderOptions: null,
  reminders: [],
  isBusy: false,
};

const elements = {
  chatTitle: document.querySelector("#chat-title"),
  status: document.querySelector("#status"),
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

function setBusy(isBusy) {
  state.isBusy = isBusy;

  for (const button of document.querySelectorAll("button")) {
    button.disabled = isBusy;
  }
}

function showPreview(preview) {
  const period = preview.period || "одноразовое";
  elements.preview.innerHTML = `
    <strong>Предпросмотр</strong>
    <div>${escapeHtml(preview.reminder_text)}</div>
    <div class="muted">${escapeHtml(period)}</div>
    <div class="muted">${formatDateTime(preview.start_at)}</div>
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

  const bootstrap = await apiRequest("/api/tma/bootstrap");

  state.context = bootstrap.context;
  state.reminderOptions = bootstrap.reminder_options;
  state.reminders = bootstrap.active_reminders;

  renderContext();
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

  const meta = document.createElement("div");
  meta.className = "reminder-meta";
  meta.innerHTML = `
    <span>${escapeHtml(reminder.period || "одноразовое")}</span>
    <span>${formatDateTime(reminder.start_at)}</span>
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

function setDefaultStartAtIfEmpty() {
  updateStartAtMin();

  if (!elements.startAt.value) {
    setDefaultStartAt();
  }
}

function setDefaultStartAt() {
  const date = new Date();

  date.setMinutes(date.getMinutes() + DEFAULT_START_OFFSET_MINUTES);
  date.setSeconds(0, 0);

  elements.startAt.value = toDateTimeLocalValue(date);
}

function updateStartAtMin() {
  const date = new Date();

  date.setSeconds(0, 0);

  elements.startAt.min = toDateTimeLocalValue(date);
}

function startEdit(reminder) {
  elements.reminderId.value = reminder.id;
  elements.formTitle.textContent = "Редактировать напоминание";
  elements.reminderText.value = reminder.reminder_text;
  elements.scheduleType.value = reminder.schedule_type;
  elements.startAt.value = toDateTimeLocalValue(reminder.start_at);
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
  updateConditionalFields();
  showStatus(
    "Редактируешь напоминание. Внеси изменения и нажми «Сохранить изменения».",
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
  updateConditionalFields();
}

async function previewReminder() {
  hideStatus();

  const preview = await apiRequest("/api/tma/reminder-preview", {
    method: "POST",
    body: JSON.stringify(buildRequestPayload()),
  });

  showPreview(preview);
}

async function saveTimezone() {
  hideStatus();

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
  resetForm();
  showStatus("Таймзона чата обновлена.");
}

async function saveReminder() {
  hideStatus();

  const reminderId = elements.reminderId.value;
  const isEdit = Boolean(reminderId);
  const path = isEdit ? `/api/tma/reminders/${reminderId}` : "/api/tma/reminders";
  const method = isEdit ? "PUT" : "POST";

  await apiRequest(path, {
    method,
    body: JSON.stringify(buildRequestPayload()),
  });

  resetForm();
  await loadBootstrap();
  showStatus(isEdit ? "Напоминание обновлено." : "Напоминание создано.");
}

function confirmAction(message) {
  if (typeof telegram?.showConfirm === "function") {
    return new Promise((resolve) => {
      telegram.showConfirm(message, resolve);
    });
  }

  return window.confirm(message);
}

function buildDeleteConfirmationMessage(reminder) {
  return `Удалить напоминание?\n\n${reminder.reminder_text}`;
}

async function deleteReminder(reminder) {
  hideStatus();

  const confirmed = await confirmAction(buildDeleteConfirmationMessage(reminder));
  if (!confirmed) {
    return;
  }

  await apiRequest(`/api/tma/reminders/${reminder.id}`, {
    method: "DELETE",
  });

  await loadBootstrap();
  showStatus("Напоминание удалено.");
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function toDateTimeLocalValue(value) {
  const date = new Date(value);
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

async function handleAsync(action) {
  if (state.isBusy) {
    return;
  }

  setBusy(true);

  try {
    await action();
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

elements.reloadButton.addEventListener("click", () => handleAsync(loadBootstrap));
elements.startAt.addEventListener("focus", updateStartAtMin);
elements.scheduleType.addEventListener("change", updateConditionalFields);
elements.previewButton.addEventListener("click", () => handleAsync(previewReminder));
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