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
const YEARLY_DATE_REFERENCE_YEAR = 2000;

const YEARLY_MONTHS = [
  { value: 1, label: "Январь" },
  { value: 2, label: "Февраль" },
  { value: 3, label: "Март" },
  { value: 4, label: "Апрель" },
  { value: 5, label: "Май" },
  { value: 6, label: "Июнь" },
  { value: 7, label: "Июль" },
  { value: 8, label: "Август" },
  { value: 9, label: "Сентябрь" },
  { value: 10, label: "Октябрь" },
  { value: 11, label: "Ноябрь" },
  { value: 12, label: "Декабрь" },
];

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

  if (elements.themeToggleLabel) {
    elements.themeToggleLabel.textContent = nextThemeLabel;
  }

  if (themeIcon) {
    themeIcon.textContent = isDark ? "☀" : "☾";
  } else {
    elements.themeToggleButton.textContent = isDark ? "☀" : "☾";
  }
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
  isBootstrapping: false,
  hasBootstrapped: false,
  currentScreen: null,
  listScrollY: 0,
  returnReminderId: null,
  returnFocusTarget: "create",
  openActionBlock: null,
};

function byId(id) {
  return document.querySelector(`#${id}`);
}

const elements = {
  app: byId("app"),
  loadingState: byId("loading-state"),
  listScreen: byId("list-screen"),
  formScreen: byId("form-screen"),
  settingsScreen: byId("settings-screen"),
  fatalErrorScreen: byId("fatal-error-screen"),
  listScreenTitle: byId("list-screen-title"),
  settingsScreenTitle: byId("settings-screen-title"),
  fatalErrorTitle: byId("fatal-error-title"),
  fatalErrorMessage: byId("fatal-error-message"),
  fatalErrorDetailsBlock: byId("fatal-error-details-block"),
  fatalErrorDetails: byId("fatal-error-details"),
  retryBootstrapButton: byId("retry-bootstrap-button"),
  chatTitle: byId("chat-title"),
  formChatTitle: byId("form-chat-title"),
  settingsChatTitle: byId("settings-chat-title"),
  timezoneSummaryText: byId("timezone-summary-text"),
  remindersCount: byId("reminders-count"),
  listStatus: byId("list-status"),
  formStatus: byId("form-status"),
  settingsStatus: byId("settings-status"),
  deviceTimezoneBlock: byId("device-timezone-block"),
  deviceTimezoneName: byId("device-timezone-name"),
  useDeviceTimezoneButton: byId("use-device-timezone-button"),
  timezoneForm: byId("timezone-form"),
  chatTimezoneName: byId("chat-timezone-name"),
  reloadButton: byId("reload-button"),
  settingsButton: byId("settings-button"),
  createReminderButton: byId("create-reminder-button"),
  formBackButton: byId("form-back-button"),
  settingsBackButton: byId("settings-back-button"),
  themeToggleButton: byId("theme-toggle-button"),
  themeToggleLabel: byId("theme-toggle-label"),
  form: byId("reminder-form"),
  formTitle: byId("form-title"),
  reminderId: byId("reminder-id"),
  reminderKindControl: byId("reminder-kind-control"),
  reminderKindStatic: byId("reminder-kind-static"),
  reminderKindStaticValue: byId("reminder-kind-static-value"),
  reminderKind: byId("reminder-kind"),
  reminderTextLabel: byId("reminder-text-label"),
  reminderTextHint: byId("reminder-text-hint"),
  reminderText: byId("reminder-text"),
  scheduleType: byId("schedule-type"),
  scheduleTypeControl: byId("schedule-type-control"),
  scheduleTypeStatic: byId("schedule-type-static"),
  scheduleTypeStaticValue: byId("schedule-type-static-value"),
  startAt: byId("start-at"),
  startAtLabel: byId("start-at-label"),
  startDateField: byId("start-date-field"),
  startDate: byId("start-date"),
  startDateLabel: byId("start-date-label"),
  yearlyDateField: byId("yearly-date-field"),
  yearlyMonth: byId("yearly-month"),
  yearlyDay: byId("yearly-day"),
  startTimeField: byId("start-time-field"),
  startTime: byId("start-time"),
  startTimeLabel: byId("start-time-label"),
  startAtHint: byId("start-at-hint"),
  startAtError: byId("start-at-error"),
  nextNotificationField: byId("next-notification-field"),
  nextNotificationValue: byId("next-notification-value"),
  timezoneName: byId("timezone-name"),
  intervalDays: byId("interval-days"),
  intervalWeeks: byId("interval-weeks"),
  dayOfWeek: byId("day-of-week"),
  monthDayOfWeek: byId("month-day-of-week"),
  monthWeekNumber: byId("month-week-number"),
  monthDay: byId("month-day"),
  completionField: byId("completion-field"),
  requiresCompletion: byId("requires-completion"),
  completionRepeatField: byId("completion-repeat-field"),
  completionRepeatInterval: byId("completion-repeat-interval"),
  autoDeleteTooltip: byId("auto-delete-tooltip"),
  deleteAfterTwoDays: byId("delete-after-two-days"),
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

const SCREEN_NAMES = new Set(["list", "form", "settings", "fatal-error"]);

function getScreenElement(screenName) {
  return {
    list: elements.listScreen,
    form: elements.formScreen,
    settings: elements.settingsScreen,
    "fatal-error": elements.fatalErrorScreen,
  }[screenName];
}

function getScreenTitle(screenName) {
  return {
    list: elements.listScreenTitle,
    form: elements.formTitle,
    settings: elements.settingsScreenTitle,
    "fatal-error": elements.fatalErrorTitle,
  }[screenName];
}

function getStatusElement(screenName = state.currentScreen) {
  return {
    list: elements.listStatus,
    form: elements.formStatus,
    settings: elements.settingsStatus,
  }[screenName];
}

function showScreen(
  screenName,
  { focus = true, focusTarget = null, scrollToTop = true } = {},
) {
  if (!SCREEN_NAMES.has(screenName)) {
    throw new Error(`Unknown screen: ${screenName}`);
  }

  const previousScreen = state.currentScreen;
  closeActionBlock({ restoreFocus: false });

  if (previousScreen && previousScreen !== screenName) {
    hideStatus(previousScreen);
  }

  for (const name of SCREEN_NAMES) {
    const screen = getScreenElement(name);
    if (screen) {
      screen.hidden = name !== screenName;
    }
  }

  elements.loadingState.hidden = true;
  elements.app.setAttribute("aria-busy", "false");
  state.currentScreen = screenName;

  const resolvedFocusTarget = focusTarget || getScreenTitle(screenName);
  window.requestAnimationFrame(() => {
    if (scrollToTop !== false) {
      window.scrollTo({
        top: 0,
        behavior: "auto",
      });
    }

    if (focus !== false) {
      resolvedFocusTarget?.focus({ preventScroll: true });
    }
  });
}

function setBootstrapLoading(isLoading) {
  state.isBootstrapping = isLoading;
  elements.app.setAttribute("aria-busy", String(isLoading));
  const shouldShowInitialLoading = isLoading && !state.hasBootstrapped;
  elements.loadingState.hidden = !shouldShowInitialLoading;

  if (shouldShowInitialLoading) {
    for (const name of SCREEN_NAMES) {
      const screen = getScreenElement(name);
      if (screen) {
        screen.hidden = true;
      }
    }
    state.currentScreen = null;
  }
}

function showFatalError(error) {
  const technicalMessage = error?.message || "Неизвестная ошибка";
  let message = "Проверь подключение и попробуй ещё раз.";

  if (isMissingChatContextError(error)) {
    message = "Открой Незабудку из нужного Telegram-чата и попробуй ещё раз.";
  } else if (isExpiredLaunchTokenError(error)) {
    message = "Ссылка устарела. Открой Незабудку заново из Telegram-чата.";
  }

  elements.fatalErrorMessage.textContent = message;
  elements.fatalErrorDetails.textContent = technicalMessage;
  elements.fatalErrorDetailsBlock.hidden = !technicalMessage;
  showScreen("fatal-error");
}

function rememberListPosition({ reminderId = null, focusTarget = "create" } = {}) {
  state.listScrollY = window.scrollY;
  state.returnReminderId = reminderId;
  state.returnFocusTarget = focusTarget;
}

function getReminderContentButton(reminderId) {
  if (reminderId === null || reminderId === undefined) {
    return null;
  }

  return elements.remindersList.querySelector(
    `[data-reminder-content-id="${String(reminderId)}"]`,
  );
}

function getReminderMenuButton(reminderId) {
  if (reminderId === null || reminderId === undefined) {
    return null;
  }

  return elements.remindersList.querySelector(
    `[data-reminder-menu-id="${String(reminderId)}"]`,
  );
}

function getSavedReturnFocusTarget() {
  if (state.returnFocusTarget === "settings") {
    return elements.settingsButton;
  }
  if (state.returnFocusTarget === "menu") {
    return getReminderMenuButton(state.returnReminderId);
  }
  if (state.returnFocusTarget === "card") {
    return getReminderContentButton(state.returnReminderId);
  }

  return elements.createReminderButton;
}

function isElementInViewport(element) {
  if (!element) {
    return false;
  }

  const rect = element.getBoundingClientRect();
  return rect.top >= 0 && rect.bottom <= window.innerHeight;
}

function getMaximumScrollY() {
  return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
}

function restoreListPositionAndFocus({
  reminderId = null,
  mode = "restore",
  fallbackTarget = null,
} = {}) {
  window.requestAnimationFrame(() => {
    if (mode !== "create") {
      window.scrollTo({
        top: Math.min(state.listScrollY, getMaximumScrollY()),
        behavior: "auto",
      });
    }

    const target =
      getReminderContentButton(reminderId) ||
      fallbackTarget ||
      getSavedReturnFocusTarget() ||
      elements.createReminderButton;

    if (
      (mode === "create" || mode === "edit" || mode === "delete") &&
      !isElementInViewport(target)
    ) {
      target?.scrollIntoView({ block: "center", behavior: "auto" });
    }

    window.requestAnimationFrame(() => target?.focus({ preventScroll: true }));
  });
}

function showListAndRestoreFocus(options = {}) {
  showScreen("list", { focus: false, scrollToTop: false });
  restoreListPositionAndFocus(options);
}

function getStartAtFieldElements() {
  return [
    elements.startAt,
    elements.startDate,
    elements.startTime,
    elements.yearlyMonth,
    elements.yearlyDay,
  ];
}

function isEditMode() {
  return Boolean(elements.reminderId.value);
}

function isRepeatingReminder() {
  return elements.scheduleType.value !== "once";
}

function isRepeatingEdit() {
  return isEditMode() && isRepeatingReminder();
}

function isYearlyDateReminder() {
  return elements.scheduleType.value === "yearly_date";
}

function setFieldLabelVisibility(label, isVisible) {
  label?.classList.toggle("sr-only", !isVisible);
}

function updateStartAtFields() {
  const isRecurringEdit = isRepeatingEdit();
  const shouldShowYearlyDate =
    isRecurringEdit && isYearlyDateReminder();

  if (elements.startAtLabel) {
    elements.startAtLabel.hidden = isRecurringEdit;
  }

  if (elements.startDateField) {
    elements.startDateField.hidden = isRecurringEdit;
  }

  if (elements.startDate) {
    elements.startDate.disabled = isRecurringEdit;
  }

  if (elements.yearlyDateField) {
    elements.yearlyDateField.hidden = !shouldShowYearlyDate;
  }

  if (elements.yearlyMonth) {
    elements.yearlyMonth.disabled = !shouldShowYearlyDate;
  }

  if (elements.yearlyDay) {
    elements.yearlyDay.disabled = !shouldShowYearlyDate;
  }

  if (elements.startTimeField) {
    elements.startTimeField.hidden = false;
  }

  if (elements.startTime) {
    elements.startTime.disabled = false;
  }

  if (elements.startDateLabel) {
    elements.startDateLabel.textContent = "Дата первого срабатывания";
  }

  if (elements.startTimeLabel) {
    elements.startTimeLabel.textContent = isRecurringEdit
      ? "Время уведомления"
      : "Время первого срабатывания";
  }

  setFieldLabelVisibility(elements.startDateLabel, false);
  setFieldLabelVisibility(elements.startTimeLabel, isRecurringEdit);

  if (shouldShowYearlyDate) {
    syncYearlyDateControlsFromStartDate();
  }
}

function updateFormEditability() {
  const isEdit = isEditMode();

  if (elements.reminderKind) {
    elements.reminderKind.disabled = isEdit;
  }

  if (elements.reminderKindControl) {
    elements.reminderKindControl.hidden = isEdit;
  }
  if (elements.reminderKindStatic) {
    elements.reminderKindStatic.hidden = !isEdit;
  }
  if (elements.reminderKindStaticValue) {
    elements.reminderKindStaticValue.textContent =
      elements.reminderKind?.selectedOptions[0]?.textContent || "";
  }

  elements.scheduleType.disabled = isEdit;

  if (elements.scheduleTypeControl) {
    elements.scheduleTypeControl.hidden = isEdit;
  }
  if (elements.scheduleTypeStatic) {
    elements.scheduleTypeStatic.hidden = !isEdit;
  }
  if (elements.scheduleTypeStaticValue) {
    elements.scheduleTypeStaticValue.textContent =
      elements.scheduleType.selectedOptions[0]?.textContent || "";
  }

  updateStartAtFields();
}

function showStatus(message, type = "success", screenName = state.currentScreen) {
  const status = getStatusElement(screenName);
  if (!status) {
    return;
  }

  status.textContent = message;
  status.className = `status ${type}`;
  status.hidden = false;
}

function hideStatus(screenName = state.currentScreen) {
  const status = getStatusElement(screenName);
  if (!status) {
    return;
  }

  status.hidden = true;
  status.textContent = "";
  status.className = "status";
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

  syncYearlyDateControlsFromStartDate();
}

function getYearlyMonthDays(month) {
  return new Date(
    Date.UTC(YEARLY_DATE_REFERENCE_YEAR, month, 0),
  ).getUTCDate();
}

function fillYearlyDayOptions(selectedDay = "") {
  if (!elements.yearlyDay) {
    return;
  }

  const month = Number(elements.yearlyMonth?.value);
  const maximumDay = month ? getYearlyMonthDays(month) : 31;

  fillNumberSelect(
    elements.yearlyDay,
    Array.from({ length: maximumDay }, (_, index) => index + 1),
    "День",
  );

  if (selectedDay) {
    const day = Math.min(Number(selectedDay), maximumDay);
    elements.yearlyDay.value = String(day);
  }
}

function fillYearlyDateOptions() {
  if (!elements.yearlyMonth || !elements.yearlyDay) {
    return;
  }

  fillSelect(elements.yearlyMonth, YEARLY_MONTHS, "Месяц");
  fillYearlyDayOptions();
}

function syncYearlyDateControlsFromStartDate() {
  if (
    !elements.startDate?.value ||
    !elements.yearlyMonth ||
    !elements.yearlyDay
  ) {
    return;
  }

  const [, monthPart, dayPart] = elements.startDate.value.split("-");

  if (!monthPart || !dayPart) {
    return;
  }

  elements.yearlyMonth.value = String(Number(monthPart));
  fillYearlyDayOptions(String(Number(dayPart)));
}

function syncStartDateFromYearlyDateControls() {
  if (
    !elements.startDate ||
    !elements.yearlyMonth ||
    !elements.yearlyDay
  ) {
    return;
  }

  const month = Number(elements.yearlyMonth.value);
  const day = Number(elements.yearlyDay.value);

  if (!month || !day || day > getYearlyMonthDays(month)) {
    elements.startDate.value = "";
    return;
  }

  elements.startDate.value =
    `${YEARLY_DATE_REFERENCE_YEAR}-${String(month).padStart(2, "0")}` +
    `-${String(day).padStart(2, "0")}`;
}

function syncStartAtFromParts() {
  if (isRepeatingEdit() && isYearlyDateReminder()) {
    syncStartDateFromYearlyDateControls();
  }

  if (!elements.startDate || !elements.startTime) {
    return;
  }

  const datePart = elements.startDate.value;
  const timePart = elements.startTime.value;

  elements.startAt.value = datePart && timePart
    ? `${datePart}T${timePart}`
    : "";
}

function getStartAtFocusTarget() {
  if (isRepeatingEdit() && isYearlyDateReminder()) {
    return elements.yearlyMonth || elements.startTime || elements.startAt;
  }

  if (isRepeatingEdit()) {
    return elements.startTime || elements.startAt;
  }

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
    if (state.currentScreen === "settings") {
      elements.chatTimezoneName.focus();
    }
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
    preview.timezone_name ||
    elements.timezoneName.value ||
    state.context?.timezone_name;
  const reminderKind = preview.reminder_kind || getReminderKind();
  const isRecurringEdit = isRepeatingEdit();
  const notificationAt = isRecurringEdit
    ? preview.next_run_at
    : preview.start_at;
  const notificationLabel = isRecurringEdit
    ? "Следующее уведомление"
    : "Первое срабатывание";
  const autoDeleteChip = preview.delete_after_two_days
    ? `<span class="preview-chip">Автоудаление: ${
        preview.requires_completion ? "после выполнения" : "через 2 суток"
      }</span>`
    : "";
  const completionInterval = (
    state.reminderOptions?.completion_repeat_intervals || []
  ).find(
    (option) =>
      Number(option.value) === Number(preview.repeat_interval_minutes),
  );
  const completionChip = preview.requires_completion
    ? `<span class="preview-chip">До выполнения · ${escapeHtml(
        completionInterval?.label || `${preview.repeat_interval_minutes} мин.`,
      )}</span>`
    : "";

  elements.preview.innerHTML = `
    <div class="preview-label">Предпросмотр</div>
    <div class="preview-title">${escapeHtml(preview.reminder_text)}</div>
    <div class="preview-grid">
      <span class="preview-chip">${escapeHtml(
        getReminderKindLabel(reminderKind),
      )}</span>
      <span class="preview-chip">${escapeHtml(period)}</span>
      ${autoDeleteChip}
      ${completionChip}
      <span class="preview-next">${notificationLabel}: ${escapeHtml(
        formatDateTimeWithConditionalTimezone(
          notificationAt,
          timezoneName,
        ),
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

  updateCompletionFields();
}

function updateCompletionFields() {
  const isWeather = getReminderKind() === REMINDER_KIND_WEATHER;
  if (isWeather && elements.requiresCompletion) {
    elements.requiresCompletion.checked = false;
  }
  if (elements.completionField) {
    elements.completionField.hidden = isWeather;
  }
  if (elements.requiresCompletion) {
    elements.requiresCompletion.disabled = isWeather;
  }

  const isEnabled = Boolean(elements.requiresCompletion?.checked) && !isWeather;
  if (elements.autoDeleteTooltip) {
    elements.autoDeleteTooltip.textContent = isEnabled
      ? "После выполнения сообщение будет удалено примерно через два дня."
      : "Сообщение будет удалено примерно через два дня.";
  }
  if (elements.completionRepeatField) {
    elements.completionRepeatField.hidden = !isEnabled;
  }
  if (elements.completionRepeatInterval) {
    elements.completionRepeatInterval.disabled = !isEnabled;
    if (isEnabled && !elements.completionRepeatInterval.value) {
      elements.completionRepeatInterval.value = "60";
    }
  }
  if (elements.reminderText) {
    const maxLength = state.reminderOptions?.completion_reminder_text_max_length;
    if (isEnabled && Number.isInteger(maxLength)) {
      elements.reminderText.maxLength = maxLength;
    } else {
      elements.reminderText.removeAttribute("maxlength");
    }
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

function applyBootstrap(bootstrap) {
  state.context = bootstrap.context;
  state.reminderOptions = bootstrap.reminder_options;
  state.reminders = sortReminders(bootstrap.active_reminders);

  renderContext();
  renderDeviceTimezoneSuggestion();
  renderOptions();
  renderReminders();
  setDefaultStartAtIfEmpty();
}

async function bootstrapApp() {
  if (state.isBootstrapping) {
    return;
  }

  const isInitialBootstrap = !state.hasBootstrapped;
  if (isInitialBootstrap) {
    elements.chatTitle.textContent = "Загрузка чата...";
    hidePreview();
    clearFieldErrors();
  } else {
    state.listScrollY = window.scrollY;
    hideStatus("list");
  }

  setBootstrapLoading(true);
  setBusy(true);

  try {
    const bootstrap = await apiRequest("/api/tma/bootstrap");

    applyBootstrap(bootstrap);
    state.hasBootstrapped = true;
    setBootstrapLoading(false);

    if (isInitialBootstrap) {
      showScreen("list");
    } else {
      showScreen("list", { focus: false, scrollToTop: false });
      restoreListPositionAndFocus({ fallbackTarget: elements.reloadButton });
      showStatus("Список обновлён.", "success", "list");
    }
  } catch (error) {
    setBootstrapLoading(false);
    if (isInitialBootstrap) {
      showFatalError(error);
    } else {
      showScreen("list", { focus: false, scrollToTop: false });
      let message = error.message;
      if (isExpiredLaunchTokenError(error)) {
        message = buildExpiredLaunchTokenMessage();
      } else if (isMissingChatContextError(error)) {
        message = buildMissingChatContextMessage();
      }
      showStatus(message, "error", "list");
      window.requestAnimationFrame(() =>
        elements.reloadButton.focus({ preventScroll: true }),
      );
    }
  } finally {
    setBusy(false);
  }
}

function getChatDisplayTitle() {
  const chat = state.context?.chat;
  return chat?.title || chat?.type || "Telegram chat";
}

function renderContext() {
  const title = getChatDisplayTitle();
  const timezoneName = state.context.timezone_name;

  elements.chatTitle.textContent = title;
  elements.formChatTitle.textContent = title;
  elements.formChatTitle.title = title;
  elements.settingsChatTitle.textContent = title;
  elements.settingsChatTitle.title = title;

  if (elements.timezoneSummaryText) {
    elements.timezoneSummaryText.textContent = `Текущая таймзона: ${timezoneName}`;
  }

  elements.chatTimezoneName.value = timezoneName;
  elements.timezoneName.value = timezoneName;
  renderStartAtHint();
  updateRemindersCount();
}

function renderStartAtHint() {
  const timezoneName =
    elements.timezoneName.value || state.context?.timezone_name;

  elements.startAtHint.textContent = `Таймзона: ${timezoneName}`;
}

function hideNextNotification() {
  if (elements.nextNotificationField) {
    elements.nextNotificationField.hidden = true;
  }

  if (elements.nextNotificationValue) {
    elements.nextNotificationValue.textContent = "";
  }
}

function renderNextNotification(value, timezoneName) {
  if (
    !isRepeatingEdit() ||
    !value ||
    !elements.nextNotificationField ||
    !elements.nextNotificationValue
  ) {
    hideNextNotification();
    return;
  }

  elements.nextNotificationValue.textContent =
    formatDateTimeWithConditionalTimezone(value, timezoneName);
  elements.nextNotificationField.hidden = false;
}

function markNextNotificationForPreview() {
  if (
    !isRepeatingEdit() ||
    !elements.nextNotificationField ||
    !elements.nextNotificationValue
  ) {
    return;
  }

  elements.nextNotificationValue.textContent =
    "Изменились параметры расписания. Нажми «Предпросмотр», чтобы рассчитать следующее уведомление.";
  elements.nextNotificationField.hidden = false;
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
  fillYearlyDateOptions();
  fillSelect(
    elements.completionRepeatInterval,
    state.reminderOptions.completion_repeat_intervals || [],
    "Выбери интервал",
  );

  updateConditionalFields();
  updateCompletionFields();
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

function closeActionBlock({ restoreFocus = false } = {}) {
  const openBlock = state.openActionBlock;
  if (!openBlock) {
    return;
  }

  openBlock.block.hidden = true;
  openBlock.button.setAttribute("aria-expanded", "false");
  state.openActionBlock = null;

  if (restoreFocus && openBlock.button.isConnected) {
    openBlock.button.focus({ preventScroll: true });
  }
}

function toggleActionBlock({ button, block, wrapper, firstAction }) {
  if (state.openActionBlock?.button === button) {
    closeActionBlock({ restoreFocus: true });
    return;
  }

  closeActionBlock({ restoreFocus: false });
  block.hidden = false;
  button.setAttribute("aria-expanded", "true");
  state.openActionBlock = { button, block, wrapper };
  window.requestAnimationFrame(() => firstAction.focus());
}

function renderReminders() {
  closeActionBlock({ restoreFocus: false });
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
  card.dataset.reminderId = String(reminder.id);

  const contentButton = document.createElement("button");
  contentButton.className = "reminder-content-button";
  contentButton.type = "button";
  contentButton.dataset.reminderContentId = String(reminder.id);
  contentButton.setAttribute(
    "aria-label",
    `Изменить напоминание: ${reminder.reminder_text}`,
  );
  contentButton.addEventListener("click", () =>
    openReminderEditor(reminder, "card"),
  );

  const title = createTextElement(
    "span",
    "reminder-title",
    reminder.reminder_text,
  );

  const nextRun = document.createElement("span");
  nextRun.className = "reminder-next-run";
  if (reminder.schedule_type === "once" && reminder.awaiting_completion) {
    nextRun.textContent = "Ожидает выполнения";
  } else {
    const nextRunAt = reminder.next_run_at || reminder.start_at;
    const timezoneName = reminder.timezone_name || state.context?.timezone_name;
    nextRun.textContent = `Следующее: ${formatDateTimeWithConditionalTimezone(
      nextRunAt,
      timezoneName,
    )}`;
  }

  const period = createTextElement(
    "span",
    "reminder-period",
    reminder.period || "одноразовое",
  );

  const specialStates = document.createElement("span");
  specialStates.className = "reminder-special-states";

  if (reminder.reminder_kind === REMINDER_KIND_WEATHER) {
    specialStates.append(createTextElement("span", "reminder-chip", "Погода"));
  }

  if (reminder.requires_completion) {
    const intervalOption = (
      state.reminderOptions?.completion_repeat_intervals || []
    ).find(
      (option) =>
        Number(option.value) === Number(reminder.repeat_interval_minutes),
    );
    specialStates.append(
      createTextElement(
        "span",
        "reminder-chip",
        `До выполнения · ${intervalOption?.label || `${reminder.repeat_interval_minutes} мин.`}`,
      ),
    );
  }

  contentButton.append(title, nextRun, period);
  if (specialStates.childElementCount) {
    contentButton.append(specialStates);
  }
  if (reminder.delete_after_two_days) {
    contentButton.append(
      createTextElement(
        "span",
        "reminder-auto-delete",
        reminder.requires_completion
          ? "Автоудаление после выполнения"
          : "Автоудаление через 2 суток",
      ),
    );
  }

  const actions = document.createElement("div");
  actions.className = "reminder-actions-wrapper";

  const menuButton = createButton(
    "secondary-button reminder-menu-button",
    "⋯",
    () => toggleActionBlock({
      button: menuButton,
      block: actionBlock,
      wrapper: actions,
      firstAction: editButton,
    }),
  );
  const actionBlockId = `reminder-actions-${reminder.id}`;
  menuButton.dataset.reminderMenuId = String(reminder.id);
  menuButton.setAttribute(
    "aria-label",
    `Действия с напоминанием: ${reminder.reminder_text}`,
  );
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-controls", actionBlockId);

  const actionBlock = document.createElement("div");
  actionBlock.id = actionBlockId;
  actionBlock.className = "reminder-action-block";
  actionBlock.setAttribute("role", "group");
  actionBlock.setAttribute(
    "aria-label",
    `Действия с напоминанием: ${reminder.reminder_text}`,
  );
  actionBlock.hidden = true;

  const editButton = createButton(
    "reminder-action-button",
    "Изменить",
    () => {
      closeActionBlock({ restoreFocus: false });
      openReminderEditor(reminder, "menu");
    },
  );
  const deleteButton = createButton(
    "reminder-action-button danger-action",
    "Удалить",
    () => {
      closeActionBlock({ restoreFocus: false });
      deleteReminder(reminder, menuButton);
    },
  );

  actionBlock.append(editButton, deleteButton);
  actions.append(menuButton, actionBlock);
  card.append(contentButton, actions);

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
    delete_after_two_days: Boolean(elements.deleteAfterTwoDays?.checked),
    requires_completion: Boolean(elements.requiresCompletion?.checked),
    repeat_interval_minutes: elements.requiresCompletion?.checked
      ? numberOrNull(elements.completionRepeatInterval?.value)
      : null,
    interval_days: null,
    interval_weeks: null,
    day_of_week: null,
    month_week_number: null,
    month_day: null,
  };

  applySchedulePayload(payload, scheduleType);

  return payload;
}

function buildPreviewPayload() {
  const payload = buildRequestPayload();
  const reminderId = Number(elements.reminderId.value);

  if (Number.isInteger(reminderId) && reminderId > 0) {
    payload.reminder_id = reminderId;
  }

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

function getStartAtValidationMessage() {
  if (!isRepeatingEdit()) {
    return "Укажи первое срабатывание.";
  }

  if (isYearlyDateReminder()) {
    return "Укажи дату ежегодного уведомления и время уведомления.";
  }

  return "Укажи время уведомления.";
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

  if (
    elements.requiresCompletion?.checked &&
    !elements.completionRepeatInterval?.value
  ) {
    errors.push("Выбери интервал повтора до выполнения.");
  }

  if (!hasValidStartAtValue()) {
    errors.push(getStartAtValidationMessage());
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

function openCreateForm() {
  rememberListPosition({ focusTarget: "create" });
  resetForm();
  showScreen("form");
}

function openReminderEditor(reminder, focusTarget = "card") {
  rememberListPosition({
    reminderId: reminder.id,
    focusTarget,
  });
  startEdit(reminder);
  showScreen("form");
}

function cancelForm() {
  resetForm();
  showListAndRestoreFocus();
}

function openSettings() {
  rememberListPosition({ focusTarget: "settings" });
  elements.chatTimezoneName.value = state.context?.timezone_name || "";
  renderDeviceTimezoneSuggestion();
  showScreen("settings");
}

function closeSettings() {
  elements.chatTimezoneName.value = state.context?.timezone_name || "";
  hideStatus("settings");
  showListAndRestoreFocus();
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
  if (elements.deleteAfterTwoDays) {
    elements.deleteAfterTwoDays.checked = Boolean(
      reminder.delete_after_two_days,
    );
  }
  if (elements.requiresCompletion) {
    elements.requiresCompletion.checked = Boolean(reminder.requires_completion);
  }
  if (elements.completionRepeatInterval) {
    elements.completionRepeatInterval.value = reminder.repeat_interval_minutes
      ? String(reminder.repeat_interval_minutes)
      : "";
  }
  updateCompletionFields();
  elements.saveButton.textContent = "Сохранить изменения";
  elements.cancelEditButton.hidden = false;

  hidePreview();
  clearFieldErrors();
  updateConditionalFields();
  updateFormEditability();
  renderStartAtHint();
  renderNextNotification(
    reminder.next_run_at,
    reminder.timezone_name || state.context?.timezone_name,
  );
}

function resetForm() {
  elements.form.reset();
  elements.reminderId.value = "";
  elements.formTitle.textContent = "Создать напоминание";
  updateReminderKindFields();
  if (elements.deleteAfterTwoDays) {
    elements.deleteAfterTwoDays.checked = false;
  }
  if (elements.requiresCompletion) {
    elements.requiresCompletion.checked = false;
  }
  if (elements.completionRepeatInterval) {
    elements.completionRepeatInterval.value = "";
  }
  elements.timezoneName.value = state.context?.timezone_name || "";
  setDefaultStartAt();
  elements.saveButton.textContent = "Создать";
  elements.cancelEditButton.hidden = true;

  hideStatus("form");
  hidePreview();
  hideNextNotification();
  clearFieldErrors();
  updateConditionalFields();
  updateCompletionFields();
  updateFormEditability();
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
    body: JSON.stringify(buildPreviewPayload()),
  });

  showPreview(preview);
  renderNextNotification(
    preview.next_run_at,
    preview.timezone_name ||
      elements.timezoneName.value ||
      state.context?.timezone_name,
  );
}

async function saveTimezone(statusMessage = "Таймзона чата обновлена.") {
  hideStatus("settings");
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
  showStatus(statusMessage, "success", "settings");
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
  hideStatus("form");
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

  const savedReminder = await apiRequest(path, {
    method,
    body: JSON.stringify(buildRequestPayload()),
  });

  state.reminders = sortReminders([
    ...state.reminders.filter(
      (reminder) => Number(reminder.id) !== Number(savedReminder.id),
    ),
    savedReminder,
  ]);
  renderReminders();
  resetForm();
  showListAndRestoreFocus({
    reminderId: savedReminder.id,
    mode: isEdit ? "edit" : "create",
  });
  showStatus(
    isEdit ? "Напоминание обновлено." : "Напоминание создано.",
    "success",
    "list",
  );
}

function showDeleteConfirmation(reminder, invoker) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-backdrop";

    const dialog = document.createElement("section");
    dialog.className = "modal-card";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "delete-confirmation-title");
    dialog.setAttribute("aria-describedby", "delete-confirmation-description");

    const title = createTextElement("h2", "", "Удалить напоминание?");
    title.id = "delete-confirmation-title";

    const text = createTextElement("p", "modal-text", reminder.reminder_text);
    text.id = "delete-confirmation-description";

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

    let isClosed = false;

    function close(result) {
      if (isClosed) {
        return;
      }
      isClosed = true;
      document.removeEventListener("keydown", handleKeyDown);
      overlay.remove();
      elements.app.removeAttribute("inert");
      document.body.classList.remove("modal-open");

      if (!result && invoker?.isConnected) {
        invoker.focus({ preventScroll: true });
      }
      resolve(result);
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close(false);
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      if (event.shiftKey && document.activeElement === cancelButton) {
        event.preventDefault();
        confirmButton.focus();
      } else if (!event.shiftKey && document.activeElement === confirmButton) {
        event.preventDefault();
        cancelButton.focus();
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
    elements.app.setAttribute("inert", "");
    document.body.classList.add("modal-open");
    document.body.append(overlay);
    cancelButton.focus();
  });
}

async function deleteReminder(reminder, invoker) {
  if (state.isBusy) {
    return;
  }

  hideStatus("list");
  state.listScrollY = window.scrollY;

  const oldIndex = state.reminders.findIndex(
    (item) => Number(item.id) === Number(reminder.id),
  );

  const confirmed = await showDeleteConfirmation(reminder, invoker);

  if (!confirmed) {
    return;
  }

  let shouldRestoreInvokerFocus = false;
  setBusy(true);
  try {
    await apiRequest(`/api/tma/reminders/${reminder.id}`, {
      method: "DELETE",
    });

    state.reminders = state.reminders.filter(
      (item) => Number(item.id) !== Number(reminder.id),
    );
    const nextReminder =
      state.reminders[oldIndex] ||
      state.reminders[Math.max(0, oldIndex - 1)] ||
      null;
    renderReminders();
    showStatus("Напоминание удалено.", "success", "list");
    restoreListPositionAndFocus({
      reminderId: nextReminder?.id,
      mode: "delete",
      fallbackTarget: elements.createReminderButton,
    });
  } catch (error) {
    handleError(error);
    shouldRestoreInvokerFocus = true;
  } finally {
    setBusy(false);
    if (shouldRestoreInvokerFocus && invoker?.isConnected) {
      window.requestAnimationFrame(() =>
        invoker.focus({ preventScroll: true }),
      );
    }
  }
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

function isReminderScheduleField(element) {
  return [
    elements.startDate,
    elements.startTime,
    elements.yearlyMonth,
    elements.yearlyDay,
    elements.intervalDays,
    elements.intervalWeeks,
    elements.dayOfWeek,
    elements.monthDayOfWeek,
    elements.monthWeekNumber,
    elements.monthDay,
  ].includes(element);
}

function handleReminderFormChange(event) {
  hidePreview();

  if (isReminderScheduleField(event.target)) {
    markNextNotificationForPreview();
  }
}

function handleActionBlockPointerDown(event) {
  const openBlock = state.openActionBlock;
  if (openBlock && !openBlock.wrapper.contains(event.target)) {
    closeActionBlock({ restoreFocus: false });
  }
}

function handleActionBlockFocus(event) {
  const openBlock = state.openActionBlock;
  if (openBlock && !openBlock.wrapper.contains(event.target)) {
    closeActionBlock({ restoreFocus: false });
  }
}

function handleActionBlockKeyDown(event) {
  if (event.key === "Escape" && state.openActionBlock) {
    event.preventDefault();
    closeActionBlock({ restoreFocus: true });
  }
}

on(elements.reloadButton, "click", bootstrapApp);
on(elements.retryBootstrapButton, "click", bootstrapApp);
on(elements.createReminderButton, "click", openCreateForm);
on(elements.settingsButton, "click", openSettings);
on(elements.formBackButton, "click", cancelForm);
on(elements.settingsBackButton, "click", closeSettings);
on(elements.themeToggleButton, "click", toggleTheme);
on(elements.startAt, "input", clearStartAtError);
on(elements.startDate, "input", clearStartAtErrorAndSync);
on(elements.startTime, "input", clearStartAtErrorAndSync);
on(elements.yearlyMonth, "change", () => {
  fillYearlyDayOptions(elements.yearlyDay.value);
  clearStartAtErrorAndSync();
});
on(elements.yearlyDay, "change", clearStartAtErrorAndSync);
on(elements.scheduleType, "change", () => {
  updateConditionalFields();
  updateFormEditability();
  renderStartAtHint();
  hidePreview();
});
on(elements.reminderKind, "change", () => {
  updateReminderKindFields();
  hidePreview();
});
on(elements.requiresCompletion, "change", () => {
  updateCompletionFields();
  hidePreview();
});
on(elements.deleteAfterTwoDays, "change", () => {
  updateCompletionFields();
  hidePreview();
});
on(elements.form, "input", handleReminderFormChange);
on(elements.form, "change", handleReminderFormChange);
on(elements.previewButton, "click", () => handleAsync(previewReminder));
on(elements.useDeviceTimezoneButton, "click", () =>
  handleAsync(useDeviceTimezone),
);
on(elements.cancelEditButton, "click", cancelForm);
onSubmit(elements.form, saveReminder);
onSubmit(elements.timezoneForm, saveTimezone);
document.addEventListener("pointerdown", handleActionBlockPointerDown);
document.addEventListener("focusin", handleActionBlockFocus);
document.addEventListener("keydown", handleActionBlockKeyDown);

initTheme();
updateReminderKindFields();
updateFormEditability();
window.setTimeout(bootstrapApp, 0);
