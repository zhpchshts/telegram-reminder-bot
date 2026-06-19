let telegram = window.Telegram?.WebApp || null;

function refreshTelegramWebApp() {
  telegram = window.Telegram?.WebApp || telegram || null;
  return telegram;
}

const DEFAULT_START_OFFSET_MINUTES = 5;
const THEME_STORAGE_KEY = "telegram-reminder-theme";
const DARK_THEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";
const TELEGRAM_INIT_DATA_QUERY_PARAM = "tgWebAppData";
const SUPPORTED_THEMES = new Set(["dark", "light"]);
const REMINDER_KIND_TEXT = "text";
const REMINDER_KIND_WEATHER = "weather";

function getTelegramLocationParams() {
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;

  return {
    hashParams: new URLSearchParams(hash),
    searchParams: new URLSearchParams(window.location.search),
  };
}

function getTelegramInitData() {
  const sdkInitData = refreshTelegramWebApp()?.initData || "";
  if (sdkInitData) {
    return sdkInitData;
  }

  const { hashParams, searchParams } = getTelegramLocationParams();

  return (
    hashParams.get(TELEGRAM_INIT_DATA_QUERY_PARAM) ||
    searchParams.get(TELEGRAM_INIT_DATA_QUERY_PARAM) ||
    ""
  );
}

function buildMissingInitDataMessage() {
  const currentTelegram = refreshTelegramWebApp();
  const { hashParams, searchParams } = getTelegramLocationParams();

  return [
    "Telegram initData не найден.",
    "",
    "Открой Mini App именно через кнопку /app в Telegram, а не прямой ссылкой в браузере.",
    "",
    `Debug: WebApp=${currentTelegram ? "yes" : "no"}, platform=${currentTelegram?.platform || "unknown"}, version=${currentTelegram?.version || "unknown"}, hash_has_tgWebAppData=${hashParams.has(TELEGRAM_INIT_DATA_QUERY_PARAM) ? "yes" : "no"}, search_has_tgWebAppData=${searchParams.has(TELEGRAM_INIT_DATA_QUERY_PARAM) ? "yes" : "no"}`,
  ].join("\n");
}

function getDeviceTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

function isSupportedTheme(theme) {
  return SUPPORTED_THEMES.has(theme);
}

function getStoredTheme() {
  try {
    const theme = localStorage.getItem(THEME_STORAGE_KEY);

    if (isSupportedTheme(theme)) {
      return theme;
    }
  } catch {
    return null;
  }

  return null;
}

function storeTheme(theme) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Ignore storage errors inside Telegram WebView.
  }
}

function getSystemTheme() {
  if (window.matchMedia && window.matchMedia(DARK_THEME_MEDIA_QUERY).matches) {
    return "dark";
  }

  return "light";
}

function getCurrentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  if (!elements.themeToggleButton) {
    return;
  }

  const isDark = theme === "dark";
  const nextThemeLabel = isDark
    ? "Включить светлую тему"
    : "Включить тёмную тему";
  const themeIcon = elements.themeToggleButton.querySelector(
    "[aria-hidden='true']",
  );

  elements.themeToggleButton.setAttribute("aria-pressed", String(isDark));
  elements.themeToggleButton.setAttribute("aria-label", nextThemeLabel);
  elements.themeToggleButton.setAttribute("title", nextThemeLabel);

  if (themeIcon) {
    themeIcon.textContent = isDark ? "☀" : "☾";
    return;
  }

  elements.themeToggleButton.textContent = isDark ? "☀" : "☾";
}

function initTheme() {
  applyTheme(getStoredTheme() || getSystemTheme());
}

function toggleTheme() {
  const nextTheme = getCurrentTheme() === "dark" ? "light" : "dark";
  storeTheme(nextTheme);
  applyTheme(nextTheme);
}

const state = {
  context: null,
  reminderOptions: null,
  reminders: [],
  isBusy: false,
};

function byId(id) {
  return document.querySelector(`#${id}`);
}

const elements = {
  chatTitle: byId("chat-title"),
  timezoneSummaryText: byId("timezone-summary-text"),
  remindersCount: byId("reminders-count"),
  status: byId("status"),
  deviceTimezoneBlock: byId("device-timezone-block"),
  deviceTimezoneName: byId("device-timezone-name"),
  useDeviceTimezoneButton: byId("use-device-timezone-button"),
  timezoneForm: byId("timezone-form"),
  chatTimezoneName: byId("chat-timezone-name"),
  timezoneSaveButton: byId("timezone-save-button"),
  reloadButton: byId("reload-button"),
  themeToggleButton: byId("theme-toggle-button"),
  form: byId("reminder-form"),
  formTitle: byId("form-title"),
  reminderId: byId("reminder-id"),
  reminderKind: byId("reminder-kind"),
  reminderTextLabel: byId("reminder-text-label"),
  reminderTextHint: byId("reminder-text-hint"),
  reminderText: byId("reminder-text"),
  scheduleType: byId("schedule-type"),
  startAt: byId("start-at"),
  startDate: byId("start-date"),
  startTime: byId("start-time"),
  startAtHint: byId("start-at-hint"),
  startAtError: byId("start-at-error"),
  timezoneName: byId("timezone-name"),
  intervalDays: byId("interval-days"),
  intervalWeeks: byId("interval-weeks"),
  dayOfWeek: byId("day-of-week"),
  monthDayOfWeek: byId("month-day-of-week"),
  monthWeekNumber: byId("month-week-number"),
  monthDay: byId("month-day"),
  intervalDaysField: byId("interval-days-field"),
  weeklyFields: byId("weekly-fields"),
  monthlyWeekdayFields: byId("monthly-weekday-fields"),
  monthDayField: byId("month-day-field"),
  preview: byId("preview"),
  previewButton: byId("preview-button"),
  saveButton: byId("save-button"),
  cancelEditButton: byId("cancel-edit-button"),
  remindersList: byId("reminders-list"),
};

function getStartAtFieldElements() {
  return [elements.startAt, elements.startDate, elements.startTime];
}

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

  for (const element of getStartAtFieldElements()) {
    element?.setAttribute("aria-invalid", "true");
  }
}

function clearStartAtError() {
  elements.startAtError.textContent = "";
  elements.startAtError.hidden = true;

  for (const element of getStartAtFieldElements()) {
    element?.removeAttribute("aria-invalid");
  }
}

function clearFieldErrors() {
  clearStartAtError();
}

function setStartAtValue(value) {
  const normalizedValue = value || "";

  elements.startAt.value = normalizedValue;

  const [datePart, timePart = ""] = normalizedValue.split("T");

  if (elements.startDate) {
    elements.startDate.value = datePart || "";
  }

  if (elements.startTime) {
    elements.startTime.value = timePart.slice(0, 5) || "";
  }
}

function syncStartAtFromParts() {
  if (!elements.startDate || !elements.startTime) {
    return;
  }

  const datePart = elements.startDate.value;
  const timePart = elements.startTime.value;

  elements.startAt.value = datePart && timePart ? `${datePart}T${timePart}` : "";
}

function getStartAtFocusTarget() {
  return elements.startDate || elements.startAt;
}

function focusStartAtField() {
  const target = getStartAtFocusTarget();

  target.scrollIntoView({
    behavior: "smooth",
    block: "center",
  });

  target.focus();
}

function isMissingChatContextError(error) {
  return error.message === "Telegram init data start_param is required.";
}

function isExpiredLaunchTokenError(error) {
  return error.message === "TMA launch token is expired.";
}

function buildExpiredLaunchTokenMessage() {
  return [
    "Ссылка на Mini App устарела.",
    "",
    "Открой Незабудку заново из Telegram: отправь /app в нужном чате и нажми свежую кнопку.",
    "",
    "Старые кнопки из истории чата могут перестать работать.",
  ].join("\n");
}

function buildMissingChatContextMessage() {
  return [
    "Не удалось определить чат.",
    "",
    "Незабудка хранит напоминания отдельно для каждого Telegram-чата.",
    "Открой приложение из нужного чата: отправь /app или нажми кнопку «Управлять напоминаниями» в сообщении бота.",
  ].join("\n");
}

function buildStartAtPastMessage() {
  const timezoneName = elements.timezoneName.value || state.context?.timezone_name;
  const timezoneLabel = getActiveTimezoneLabel(timezoneName);

  return `Время срабатывания уже прошло в ${timezoneLabel} ${timezoneName}.\nВыбери более позднее время.`;
}

function isStartAtPastError(error) {
  return error.message === "start_at must be in the future.";
}

function isInvalidTimezoneError(error) {
  return error.message === "Invalid timezone name.";
}

function buildInvalidTimezoneMessage() {
  return [
    "Не удалось сохранить таймзону.",
    "",
    "Такой таймзоны нет. Используй таймзону устройства или скопируй значение из TimeZoneDB.",
  ].join("\n");
}

function handleError(error) {
  if (isMissingChatContextError(error)) {
    showStatus(buildMissingChatContextMessage(), "info");
    return;
  }
  if (isExpiredLaunchTokenError(error)) {
    showStatus(buildExpiredLaunchTokenMessage(), "info");
    return;
  }
  if (isStartAtPastError(error)) {
    hideStatus();
    showStartAtError(buildStartAtPastMessage());
    focusStartAtField();
    return;
  }
  if (isInvalidTimezoneError(error)) {
    showStatus(buildInvalidTimezoneMessage(), "error");
    elements.chatTimezoneName.focus();
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
  const timezoneName =
    preview.timezone_name || elements.timezoneName.value || state.context?.timezone_name;
  const reminderKind = preview.reminder_kind || getReminderKind();

  elements.preview.innerHTML = `
    <div class="preview-label">Предпросмотр</div>
    <div class="preview-title">${escapeHtml(preview.reminder_text)}</div>
    <div class="preview-grid">
      <span class="preview-chip">${escapeHtml(getReminderKindLabel(reminderKind))}</span>
      <span class="preview-chip">${escapeHtml(period)}</span>
      <span class="preview-next">Первое срабатывание: ${escapeHtml(
        formatDateTimeWithConditionalTimezone(preview.start_at, timezoneName),
      )}</span>
    </div>
  `;

  elements.preview.hidden = false;
}

function hidePreview() {
  elements.preview.hidden = true;
  elements.preview.textContent = "";
}

function getReminderKind() {
  return elements.reminderKind?.value || REMINDER_KIND_TEXT;
}

function getReminderKindLabel(reminderKind) {
  return reminderKind === REMINDER_KIND_WEATHER ? "Погода" : "Обычное";
}

function getReminderTextLabel(reminderKind = getReminderKind()) {
  return reminderKind === REMINDER_KIND_WEATHER
    ? "Населённые пункты"
    : "Текст напоминания";
}

function getReminderTextPlaceholder(reminderKind = getReminderKind()) {
  return reminderKind === REMINDER_KIND_WEATHER
    ? "Например: Екатеринбург; Москва"
    : "Например: заказать воду";
}

function getReminderTextRequiredMessage() {
  return getReminderKind() === REMINDER_KIND_WEATHER
    ? "Укажи хотя бы один населённый пункт."
    : "Укажи текст напоминания.";
}

function updateReminderKindFields() {
  const reminderKind = getReminderKind();
  const label = getReminderTextLabel(reminderKind);

  if (elements.reminderTextLabel) {
    elements.reminderTextLabel.textContent = label;
  }

  if (elements.reminderText) {
    elements.reminderText.placeholder = getReminderTextPlaceholder(reminderKind);
    elements.reminderText.setAttribute("aria-label", label);
  }

  if (elements.reminderTextHint) {
    const isWeather = reminderKind === REMINDER_KIND_WEATHER;
    elements.reminderTextHint.hidden = !isWeather;
    elements.reminderTextHint.textContent = isWeather
      ? "Можно указать до 5 населённых пунктов через точку с запятой или с новой строки."
      : "";
  }
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
  const initData = getTelegramInitData();

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
  elements.chatTitle.textContent = "Загрузка чата...";

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
  const timezoneName = state.context.timezone_name;

  elements.chatTitle.textContent = title;

  if (elements.timezoneSummaryText) {
    elements.timezoneSummaryText.textContent = `Таймзона чата: ${timezoneName}`;
  }

  elements.chatTimezoneName.value = timezoneName;
  elements.timezoneName.value = timezoneName;
  renderStartAtHint();
  updateRemindersCount();
}

function renderStartAtHint() {
  const timezoneName = elements.timezoneName.value || state.context?.timezone_name;
  elements.startAtHint.textContent = `Таймзона: ${timezoneName}`;
}

function getActiveTimezoneLabel(timezoneName) {
  if (
    timezoneName &&
    state.context?.timezone_name &&
    timezoneName !== state.context.timezone_name
  ) {
    return "таймзоне напоминания";
  }

  return "таймзоне чата";
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
	? "Используется"
	: "Использовать";
}

function renderOptions() {
  fillSelect(elements.dayOfWeek, state.reminderOptions.weekdays, "Не выбрано");
  fillSelect(
    elements.monthDayOfWeek,
    state.reminderOptions.weekdays,
    "Не выбрано",
  );
  fillNumberSelect(
    elements.monthWeekNumber,
    state.reminderOptions.month_week_numbers,
    "Не выбрано",
  );
  fillNumberSelect(
    elements.monthDay,
    state.reminderOptions.month_days,
    "Не выбрано",
  );

  updateConditionalFields();
}

function fillNumberSelect(select, values, emptyLabel) {
  fillSelect(
    select,
    values.map((value) => ({ value, label: `${value}` })),
    emptyLabel,
  );
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

function updateRemindersCount() {
  if (!elements.remindersCount) {
    return;
  }

  const count = state.reminders.length;
  elements.remindersCount.textContent =
    count === 1 ? "1 активное" : `${count} активных`;
}

function createTextElement(tagName, className, textContent) {
  const element = document.createElement(tagName);

  if (className) {
    element.className = className;
  }

  element.textContent = textContent;
  return element;
}

function createButton(className, textContent, onClick) {
  const button = document.createElement("button");
  button.className = className;
  button.type = "button";
  button.textContent = textContent;
  button.addEventListener("click", onClick);
  return button;
}

function renderReminders() {
  elements.remindersList.replaceChildren();
  updateRemindersCount();

  if (!state.reminders.length) {
    const empty = document.createElement("article");
    empty.className = "empty-state";
    empty.append(
      createTextElement("div", "empty-state-icon", "🌸"),
      createTextElement("h3", "", "Пока нет активных напоминаний"),
      createTextElement(
        "p",
        "",
        "Создай первое — например, про воду, уборку, фильтры или день рождения.",
      ),
    );

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

  const content = document.createElement("div");
  content.className = "reminder-content";

  const titleText =
    reminder.reminder_kind === REMINDER_KIND_WEATHER
      ? `Погода: ${reminder.reminder_text}`
      : reminder.reminder_text;
  const title = createTextElement("h3", "", titleText);

  const meta = document.createElement("div");
  meta.className = "reminder-meta";

  const period = createTextElement(
    "span",
    "reminder-chip",
    reminder.period || "одноразовое",
  );

  const nextRun = document.createElement("span");
  nextRun.className = "reminder-next-run";
  const nextRunAt = reminder.next_run_at || reminder.start_at;
  const timezoneName = reminder.timezone_name || state.context?.timezone_name;
  nextRun.textContent = `Следующее: ${formatDateTimeWithConditionalTimezone(
    nextRunAt,
    timezoneName,
  )}`;

  if (reminder.reminder_kind === REMINDER_KIND_WEATHER) {
    meta.append(createTextElement("span", "reminder-chip", "Погода"));
  }

  meta.append(period, nextRun);
  content.append(title, meta);

  const actions = document.createElement("div");
  actions.className = "reminder-actions";

  const editButton = createButton(
    "secondary-button compact-button",
    "Изменить",
    () => startEdit(reminder),
  );
  const deleteButton = createButton(
    "danger-button compact-button",
    "Удалить",
    () => handleAsync(() => deleteReminder(reminder)),
  );

  actions.append(editButton, deleteButton);
  card.append(content, actions);

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
  const scheduleType = elements.scheduleType.value;
  const fieldScheduleTypes = [
    [elements.intervalDaysField, "every_days"],
    [elements.weeklyFields, "every_week"],
    [elements.monthlyWeekdayFields, "monthly_weekday"],
    [elements.monthDayField, "monthly_day"],
  ];

  for (const [field, fieldScheduleType] of fieldScheduleTypes) {
    field.hidden = scheduleType !== fieldScheduleType;
  }
}

function buildRequestPayload() {
  syncStartAtFromParts();

  const scheduleType = elements.scheduleType.value;

  const payload = {
    reminder_kind: getReminderKind(),
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

  applySchedulePayload(payload, scheduleType);

  return payload;
}

function applySchedulePayload(payload, scheduleType) {
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

function hasValidStartAtValue() {
  syncStartAtFromParts();

  if (!elements.startAt.value) {
    return false;
  }

  const date = new Date(elements.startAt.value);

  return !Number.isNaN(date.getTime());
}

function validateTimezoneForm() {
  if (!elements.chatTimezoneName.value.trim()) {
    showStatus("Укажи таймзону чата.", "error");
    return false;
  }

  return true;
}

function validateReminderForm() {
  clearFieldErrors();

  const errors = getReminderFormErrors();

  if (errors.length) {
    showStatus(errors.join("\n"), "error");
    return false;
  }

  return true;
}

function getReminderFormErrors() {
  const errors = [];
  const scheduleType = elements.scheduleType.value;

  if (!elements.reminderText.value.trim()) {
    errors.push(getReminderTextRequiredMessage());
  }

  if (!hasValidStartAtValue()) {
    errors.push("Укажи первое срабатывание.");
  }

  if (!elements.timezoneName.value.trim()) {
    errors.push("Укажи таймзону чата.");
  }

  addScheduleValidationErrors(errors, scheduleType);

  return errors;
}

function addScheduleValidationErrors(errors, scheduleType) {
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

  const timezoneName = elements.timezoneName.value || state.context?.timezone_name;
  setStartAtValue(toDateTimeLocalValue(date, timezoneName));
}

function startEdit(reminder) {
  elements.reminderId.value = reminder.id;
  elements.formTitle.textContent = "Редактировать напоминание";
  if (elements.reminderKind) {
    elements.reminderKind.value = reminder.reminder_kind || REMINDER_KIND_TEXT;
  }

  elements.reminderText.value = reminder.reminder_text;

  updateReminderKindFields();

  elements.scheduleType.value = reminder.schedule_type;
  setStartAtValue(
    toDateTimeLocalValue(
      reminder.start_at,
      reminder.timezone_name || state.context?.timezone_name,
    ),
  );
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
  updateReminderKindFields();
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
  clearFieldErrors();

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
  clearFieldErrors();

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
  renderReminders();
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
  clearFieldErrors();

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

    const title = createTextElement("h2", "", "Удалить напоминание?");
    title.id = "delete-confirmation-title";

    const text = createTextElement("p", "modal-text", reminder.reminder_text);

    const actions = document.createElement("div");
    actions.className = "modal-actions";

    const cancelButton = createButton("secondary-button", "Отменить", () =>
      close(false),
    );
    const confirmButton = createButton("danger-button", "Удалить", () =>
      close(true),
    );
    cancelButton.setAttribute("data-modal-button", "");
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

function formatDateTimeWithConditionalTimezone(value, timezoneName) {
  const formatted = formatDateTime(value, timezoneName);

  if (shouldShowTimezoneSuffix(timezoneName)) {
    return `${formatted} · ${timezoneName}`;
  }

  return formatted;
}

function shouldShowTimezoneSuffix(timezoneName) {
  const currentTimezoneName = state.context?.timezone_name;

  return Boolean(
    timezoneName && currentTimezoneName && timezoneName !== currentTimezoneName,
  );
}

function formatDateTime(value, timezoneName) {
  if (!value) {
    return "не запланировано";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "некорректная дата";
  }

  const options = {
    dateStyle: "medium",
    timeStyle: "short",
  };

  if (timezoneName) {
    options.timeZone = timezoneName;
  }

  return new Intl.DateTimeFormat("ru-RU", options).format(date);
}

function toDateTimeLocalValue(value, timezoneName) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  if (!timezoneName) {
    const offsetMs = date.getTimezoneOffset() * 60 * 1000;
    return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
  }

  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezoneName,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(date);

    const values = Object.fromEntries(
      parts
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, part.value]),
    );

    return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`;
  } catch {
    const offsetMs = date.getTimezoneOffset() * 60 * 1000;
    return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
  }
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

function on(element, eventName, handler) {
  element?.addEventListener(eventName, handler);
}

function onSubmit(form, action) {
  on(form, "submit", (event) => {
    event.preventDefault();
    handleAsync(action);
  });
}

function clearStartAtErrorAndSync() {
  clearStartAtError();
  syncStartAtFromParts();
}

on(elements.reloadButton, "click", () => handleAsync(loadBootstrap));
on(elements.themeToggleButton, "click", toggleTheme);
on(elements.startAt, "input", clearStartAtError);
on(elements.startDate, "input", clearStartAtErrorAndSync);
on(elements.startTime, "input", clearStartAtErrorAndSync);
on(elements.scheduleType, "change", () => {
  updateConditionalFields();
  hidePreview();
});
on(elements.reminderKind, "change", () => {
  updateReminderKindFields();
  hidePreview();
});
on(elements.form, "input", hidePreview);
on(elements.form, "change", hidePreview);
on(elements.previewButton, "click", () => handleAsync(previewReminder));
on(elements.useDeviceTimezoneButton, "click", () =>
  handleAsync(useDeviceTimezone),
);
on(elements.cancelEditButton, "click", resetForm);
onSubmit(elements.form, saveReminder);
onSubmit(elements.timezoneForm, saveTimezone);

initTheme();
updateReminderKindFields();
window.setTimeout(() => handleAsync(loadBootstrap), 0);
