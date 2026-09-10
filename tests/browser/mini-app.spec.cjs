const { test: base, expect } = require('@playwright/test');
const { createFixtureServer, reminder } = require('./fixture-server.cjs');

const test = base.extend({
  fixture: async ({}, use) => {
    const fixture = await createFixtureServer();
    try { await use(fixture); } finally { await fixture.close(); }
  },
  context: async ({ context, fixture }, use) => {
    const external = [];
    const errors = [];
    // Fail closed: no real Telegram, weather, or other network traffic during tests.
    await context.route('**/*', (route) => {
      const url = route.request().url();
      if (new URL(url).origin === fixture.url) return route.continue();
      external.push(url);
      return route.abort();
    });
    context.on('page', (page) => page.on('pageerror', (error) => errors.push(error.message)));
    await use(context);
    expect(external, 'Unexpected external requests').toEqual([]);
    expect(errors, 'Unhandled browser errors').toEqual([]);
  },
});

const requests = (fixture, method, pathname) => fixture.store.requests.filter(
  (entry) => entry.method === method && entry.pathname === pathname,
);
const card = (page, id = 1) => page.locator(`[data-reminder-id="${id}"]`);
const content = (page, id = 1) => page.locator(`[data-reminder-content-id="${id}"]`);
const menu = (page, id = 1) => page.locator(`[data-reminder-menu-id="${id}"]`);

async function openApp(page, fixture) {
  await page.goto(`${fixture.url}/tma/`);
  await expect(page.locator('#list-screen')).toBeVisible();
  await expect(page.locator('#create-reminder-button')).toBeEnabled();
}

async function createDraft(page, text = 'Купить тестовый чай') {
  await page.locator('#create-reminder-button').click();
  await page.locator('#reminder-text').fill(text);
  await page.locator('#start-date').fill('2035-05-20');
  await page.locator('#start-time').fill('12:00');
}

async function openDelete(page, id = 1) {
  await menu(page, id).click();
  await page.locator(`#reminder-actions-${id}`).getByRole('button', { name: 'Удалить', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
}

async function withHeldResponse(page, pathname, action) {
  let release;
  let markReached;
  const released = new Promise((resolve) => { release = resolve; });
  const reached = new Promise((resolve) => { markReached = resolve; });
  await page.route(`**${pathname}`, async (route) => {
    const response = await route.fetch();
    markReached();
    await released;
    await route.fulfill({ response });
  }, { times: 1 });
  try { await action(reached); } finally { release(); }
}

test('create, preview, edit and delete through visible controls', async ({ page, fixture }) => {
  await openApp(page, fixture);
  await expect(page.locator('#reminders-list')).toContainText('Пока нет активных напоминаний');
  const text = '<img src=x onerror=alert(1)> & тест';
  await createDraft(page, text);
  await page.locator('#preview-button').click();
  await expect(page.locator('#preview')).toContainText(text);
  await expect(page.locator('#preview img')).toHaveCount(0);
  expect(fixture.store.reminders).toHaveLength(0);
  await page.locator('#save-button').click();
  await expect(content(page)).toContainText(text);
  await expect(content(page)).toBeFocused();
  const created = requests(fixture, 'POST', '/api/tma/reminders')[0];
  expect(created.idempotencyKey).toBeTruthy();
  expect(created.body).toMatchObject({ start_at: '2035-05-20T12:00', timezone_name: 'Asia/Yekaterinburg' });
  expect(created.body).not.toHaveProperty('chat_id');
  await content(page).click();
  await page.locator('#reminder-text').fill('Тестовый чай куплен');
  await page.locator('#save-button').click();
  await expect(content(page)).toContainText('Тестовый чай куплен');
  expect(requests(fixture, 'PUT', '/api/tma/reminders/1')[0].body.expected_revision).toBe(1);
  await openDelete(page);
  await page.getByRole('dialog').getByRole('button', { name: 'Удалить', exact: true }).click();
  await expect(card(page)).toHaveCount(0);
  await expect(page.locator('#create-reminder-button')).toBeFocused();
  expect(requests(fixture, 'DELETE', '/api/tma/reminders/1')[0].query.expected_revision).toBe('2');
});

test('weather and completion options are exclusive and preview matches saved payload', async ({ page, fixture }) => {
  await openApp(page, fixture);
  await createDraft(page);
  await page.locator('#requires-completion').check();
  await page.locator('#completion-repeat-interval').selectOption('30');
  await page.locator('#delete-after-two-days').check();
  await page.locator('#preview-button').click();
  await expect(page.locator('#preview')).toContainText('До выполнения · 30 минут');
  await expect(page.locator('#preview')).toContainText('после выполнения');
  await page.locator('#save-button').click();
  await expect(card(page)).toContainText('До выполнения · 30 минут');
  expect(fixture.store.reminders[0]).toMatchObject({ requires_completion: true, repeat_interval_minutes: 30 });
  await createDraft(page);
  await page.locator('#requires-completion').check();
  await page.locator('#reminder-kind').selectOption('weather');
  await expect(page.locator('#completion-field')).toBeHidden();
  await expect(page.locator('#requires-completion')).not.toBeChecked();
  await page.locator('#reminder-text').fill('Екатеринбург; Пермь');
  await page.locator('#preview-button').click();
  await expect(page.locator('#preview')).toContainText('Погода');
  await expect(page.locator('#preview')).not.toContainText('До выполнения');
  await page.locator('#save-button').click();
  await expect(card(page, 2)).toContainText('Погода');
  expect(fixture.store.reminders[1]).toMatchObject({ reminder_kind: 'weather', requires_completion: false, repeat_interval_minutes: null });
});

test('weather limits stop invalid requests and preserve locations', async ({ page, fixture }) => {
  await openApp(page, fixture);
  await createDraft(page);
  await page.locator('#reminder-kind').selectOption('weather');
  const locations = 'Москва; Пермь; Омск; Томск; Уфа; Казань';
  await page.locator('#reminder-text').fill(locations);
  await page.locator('#preview-button').click();
  await expect(page.locator('#reminder-text-error')).toContainText('не больше 5');
  await expect(page.locator('#reminder-text')).toHaveValue(locations);
  expect(requests(fixture, 'POST', '/api/tma/reminder-preview')).toHaveLength(0);
});

for (const [schedule, field] of [['every_days', 'interval-days'], ['every_week', 'interval-weeks']]) {
  test(`invalid hidden ${schedule} field does not block changing to once`, async ({ page, fixture }) => {
    await openApp(page, fixture);
    await createDraft(page);
    await page.locator('#schedule-type').selectOption(schedule);
    await page.locator(`#${field}`).fill('0');
    await page.locator('#schedule-type').selectOption('once');
    await page.locator('#save-button').click();
    await expect(content(page)).toContainText('Купить тестовый чай');
    expect(requests(fixture, 'POST', '/api/tma/reminders')[0].body).toMatchObject({
      schedule_type: 'once', interval_days: null, interval_weeks: null,
    });
  });
}

test('double click on delayed create sends one request and locks the draft', async ({ page, fixture }) => {
  await openApp(page, fixture);
  await createDraft(page);
  await withHeldResponse(page, '/api/tma/reminders', async (reached) => {
    const bounds = await page.locator('#save-button').boundingBox();
    await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2, { clickCount: 2, delay: 30 });
    await reached;
    await expect(page.locator('#reminder-text')).toBeDisabled();
    await expect(page.locator('#form-back-button')).toBeDisabled();
  });
  await expect(content(page)).toBeVisible();
  expect(requests(fixture, 'POST', '/api/tma/reminders')).toHaveLength(1);
  expect(fixture.store.reminders).toHaveLength(1);
});

test('lost create response retries the same idempotency key without a duplicate', async ({ page, fixture }) => {
  await openApp(page, fixture);
  await createDraft(page);
  // Deliver the request to the fixture, then lose its response at the browser boundary.
  // Destroying a reused HTTP socket alone may trigger a transparent Chromium retry.
  await page.route('**/api/tma/reminders', async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    await route.abort('connectionreset');
  }, { times: 1 });
  await page.locator('#save-button').click();
  await expect(page.locator('#form-status')).toContainText('повтор не создаст дубликат');
  await expect(page.locator('#reminder-text')).toHaveValue('Купить тестовый чай');
  expect(fixture.store.reminders).toHaveLength(1);
  await page.locator('#save-button').click();
  await expect(content(page)).toBeVisible();
  const attempts = requests(fixture, 'POST', '/api/tma/reminders');
  expect(attempts).toHaveLength(2);
  expect(attempts[1].idempotencyKey).toBe(attempts[0].idempotencyKey);
  expect(attempts[1].body).toEqual(attempts[0].body);
  expect(fixture.store.reminders).toHaveLength(1);
});

for (const [name, rawBody, contentType] of [
  ['HTML', '<html>Proxy maintenance</html>', 'text/html'],
  ['null', 'null', 'application/json'],
  ['empty object', '{}', 'application/json'],
]) {
  test(`invalid successful create response (${name}) preserves draft and safe retry`, async ({ page, fixture }) => {
    await openApp(page, fixture);
    await createDraft(page);
    fixture.store.queueFault('POST', '/api/tma/reminders', { rawBody, contentType });
    await page.locator('#save-button').click();
    await expect(page.locator('#form-status')).toContainText('некорректный ответ');
    await expect(page.locator('#form-screen')).toBeVisible();
    await expect(page.locator('#reminder-text')).toHaveValue('Купить тестовый чай');
    await expect(page.locator('#save-button')).toBeFocused();
    await page.locator('#save-button').click();
    await expect(content(page)).toBeVisible();
    const attempts = requests(fixture, 'POST', '/api/tma/reminders');
    expect(attempts).toHaveLength(2);
    expect(attempts[1].idempotencyKey).toBe(attempts[0].idempotencyKey);
    await expect(page.locator('.reminder-card')).toHaveCount(1);
  });
}

for (const action of ['save', 'preview']) {
  test(`two windows: stale ${action} preserves draft and requires explicit save after revision refresh`, async ({ page, context, fixture }) => {
    fixture.store.reset({ reminders: [reminder()] });
    await openApp(page, fixture);
    const other = await context.newPage();
    await openApp(other, fixture);
    await content(page).click();
    await content(other).click();
    await page.locator('#reminder-text').fill('Мой несохранённый черновик');
    await other.locator('#reminder-text').fill('Изменено в другом окне');
    await other.locator('#save-button').click();
    await expect(content(other)).toContainText('Изменено в другом окне');
    await page.locator(action === 'save' ? '#save-button' : '#preview-button').click();
    await expect(page.locator('#form-status')).toContainText('Черновик сохранён, версия обновлена');
    await expect(page.locator('#reminder-text')).toHaveValue('Мой несохранённый черновик');
    await expect(page.locator('#preview')).toBeHidden();
    expect(fixture.store.reminders[0]).toMatchObject({ reminder_text: 'Изменено в другом окне', revision: 2 });
    expect(requests(fixture, 'PUT', '/api/tma/reminders/1')).toHaveLength(action === 'save' ? 2 : 1);
    await page.locator('#preview-button').click();
    await expect(page.locator('#preview')).toContainText('Мой несохранённый черновик');
    expect(requests(fixture, 'POST', '/api/tma/reminder-preview').at(-1).body.expected_revision).toBe(2);
    await page.locator('#save-button').click();
    await expect(content(page)).toContainText('Мой несохранённый черновик');
    expect(fixture.store.reminders[0].revision).toBe(3);
    await other.close();
  });
}

test('delete modal cancel, Escape and keyboard focus leave the reminder intact', async ({ page, fixture }) => {
  fixture.store.reset({ reminders: [reminder()] });
  await openApp(page, fixture);
  await openDelete(page);
  const dialog = page.getByRole('dialog');
  const cancel = dialog.getByRole('button', { name: 'Отменить' });
  const confirm = dialog.getByRole('button', { name: 'Удалить', exact: true });
  await expect(cancel).toBeFocused();
  await expect(page.locator('#app')).toHaveAttribute('inert', '');
  await page.keyboard.press('Shift+Tab');
  await expect(confirm).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(cancel).toBeFocused();
  await cancel.click();
  await expect(dialog).toHaveCount(0);
  await expect(menu(page)).toBeFocused();
  await openDelete(page);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(menu(page)).toBeFocused();
  await expect(page.locator('#app')).not.toHaveAttribute('inert', '');
  expect(requests(fixture, 'DELETE', '/api/tma/reminders/1')).toHaveLength(0);
  expect(fixture.store.reminders).toHaveLength(1);
});

test('stale delete refreshes the card and requires another explicit confirmation', async ({ page, context, fixture }) => {
  fixture.store.reset({ reminders: [reminder()] });
  await openApp(page, fixture);
  const other = await context.newPage();
  await openApp(other, fixture);
  await content(other).click();
  await other.locator('#reminder-text').fill('Важное изменение другого окна');
  await other.locator('#save-button').click();
  await expect(content(other)).toContainText('Важное изменение другого окна');
  await openDelete(page);
  await page.getByRole('dialog').getByRole('button', { name: 'Удалить', exact: true }).click();
  await expect(page.locator('#list-status')).toContainText('повтори удаление');
  await expect(content(page)).toContainText('Важное изменение другого окна');
  expect(fixture.store.reminders).toHaveLength(1);
  expect(requests(fixture, 'DELETE', '/api/tma/reminders/1')).toHaveLength(1);
  await openDelete(page);
  await expect(page.getByRole('dialog')).toContainText('Важное изменение другого окна');
  await page.getByRole('dialog').getByRole('button', { name: 'Удалить', exact: true }).click();
  await expect(card(page)).toHaveCount(0);
  expect(requests(fixture, 'DELETE', '/api/tma/reminders/1')[1].query.expected_revision).toBe('2');
  await other.close();
});

test('bootstrap service failure can be retried without leaving loading controls disabled', async ({ page, fixture }) => {
  // An HTTP failure is deliberately distinct from a connection failure in the next case.
  fixture.store.queueFault('GET', '/api/tma/bootstrap', { status: 503 });
  await page.goto(`${fixture.url}/tma/`);
  await expect(page.locator('#fatal-error-screen')).toBeVisible();
  await expect(page.locator('#retry-bootstrap-button')).toBeEnabled();
  await page.locator('#retry-bootstrap-button').click();
  await expect(page.locator('#list-screen')).toBeVisible();
  await expect(page.locator('#create-reminder-button')).toBeEnabled();
});

test('bootstrap disconnected network reports error then retries successfully', async ({ page, fixture }) => {
  await page.route('**/api/tma/bootstrap', (route) => route.abort('internetdisconnected'), { times: 1 });
  await page.goto(`${fixture.url}/tma/`);
  await expect(page.locator('#fatal-error-message')).toContainText('Не удалось связаться с сервером');
  await page.locator('#retry-bootstrap-button').click();
  await expect(page.locator('#list-screen')).toBeVisible();
});

test('expired bootstrap session explains reopening Telegram', async ({ page, fixture }) => {
  fixture.store.queueFault('GET', '/api/tma/bootstrap', { status: 401, body: { detail: 'init_data is expired.' } });
  await page.goto(`${fixture.url}/tma/`);
  await expect(page.locator('#fatal-error-screen')).toBeVisible();
  await expect(page.locator('#fatal-error-message')).toContainText('Открой Незабудку заново');
  await expect(page.locator('#list-screen')).toBeHidden();
  expect(requests(fixture, 'POST', '/api/tma/reminders')).toHaveLength(0);
});

test('timezone field locks while pending and error leaves its draft available', async ({ page, fixture }) => {
  await openApp(page, fixture);
  await page.locator('#settings-button').click();
  await page.locator('#chat-timezone-name').fill('Europe/Moscow');
  fixture.store.queueFault('PUT', '/api/tma/timezone', { status: 503 });
  await withHeldResponse(page, '/api/tma/timezone', async (reached) => {
    await page.locator('#timezone-save-button').click();
    await reached;
    await expect(page.locator('#chat-timezone-name')).toBeDisabled();
    await expect(page.locator('#settings-back-button')).toBeDisabled();
  });
  await expect(page.locator('#settings-status')).toContainText('временно недоступен');
  await expect(page.locator('#chat-timezone-name')).toBeEnabled();
  await expect(page.locator('#chat-timezone-name')).toHaveValue('Europe/Moscow');
  expect(fixture.store.timezone).toBe('Asia/Yekaterinburg');
  await page.locator('#timezone-save-button').click();
  await expect(page.locator('#timezone-summary-text')).toContainText('Europe/Moscow');
});

test('invalid timezone preserves previous setting and existing reminder timezone', async ({ page, fixture }) => {
  fixture.store.reset({ reminders: [reminder()] });
  await openApp(page, fixture);
  await page.locator('#settings-button').click();
  await page.locator('#chat-timezone-name').fill('Invalid/Timezone');
  await page.locator('#timezone-save-button').click();
  await expect(page.locator('#settings-status')).toContainText('Такой таймзоны нет');
  await expect(page.locator('#chat-timezone-name')).toHaveValue('Invalid/Timezone');
  expect(fixture.store.timezone).toBe('Asia/Yekaterinburg');
  await page.locator('#chat-timezone-name').fill('Europe/Moscow');
  await page.locator('#timezone-save-button').click();
  await expect(page.locator('#settings-status')).toContainText('обновлена');
  await page.locator('#settings-back-button').click();
  await expect(content(page)).toContainText('Asia/Yekaterinburg');
  await content(page).click();
  await expect(page.locator('#timezone-name')).toHaveValue('Asia/Yekaterinburg');
});

test('320px screen keeps long text, actions and modal within viewport', async ({ page, fixture }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 640 });
  fixture.store.reset({ reminders: [reminder({ reminder_text: 'ДлинноеСлово'.repeat(100) })] });
  await openApp(page, fixture);
  const noOverflow = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(await noOverflow()).toBe(true);
  const headerLayout = await page.locator('#list-screen-title').evaluate((title) => {
    const range = document.createRange();
    range.selectNodeContents(title);
    const text = range.getBoundingClientRect();
    const heading = title.getBoundingClientRect();
    const buttons = [...document.querySelectorAll('.header-actions button')]
      .map((button) => button.getBoundingClientRect());
    return {
      textFitsHeading: text.left >= heading.left - 1 && text.right <= heading.right + 1,
      textFitsViewport: text.left >= 0 && text.right <= window.innerWidth,
      textOverlapsButtons: buttons.some((button) => text.left < button.right && text.right > button.left
        && text.top < button.bottom && text.bottom > button.top),
    };
  });
  expect(headerLayout).toEqual({ textFitsHeading: true, textFitsViewport: true, textOverlapsButtons: false });
  await openDelete(page);
  expect(await noOverflow()).toBe(true);
  const modal = await page.getByRole('dialog').boundingBox();
  expect(modal.x).toBeGreaterThanOrEqual(0);
  expect(modal.x + modal.width).toBeLessThanOrEqual(321);
  const screenshotPath = testInfo.outputPath('320px-delete-dialog.png');
  await page.screenshot({ path: screenshotPath });
  await testInfo.attach('Диалог удаления при ширине 320px', { path: screenshotPath, contentType: 'image/png' });
  await page.keyboard.press('Escape');
  await content(page).click();
  expect(await noOverflow()).toBe(true);
  await expect(page.locator('#save-button')).toBeVisible();
});

for (const [schedule, controls, expected] of [
  ['yearly_date', [], {}],
  ['every_days', [['#interval-days', '3', 'fill']], { interval_days: 3 }],
  ['every_week', [['#interval-weeks', '2', 'fill'], ['#day-of-week', 'MON']], { interval_weeks: 2, day_of_week: 'MON' }],
  ['monthly_weekday', [['#month-week-number', '2'], ['#month-day-of-week', 'FRI']], { month_week_number: 2, day_of_week: 'FRI' }],
  ['monthly_day', [['#month-day', '0']], { month_day: 0 }],
]) {
  test(`${schedule} serializes only the selected schedule fields`, async ({ page, fixture }) => {
    await openApp(page, fixture);
    await createDraft(page);
    await page.locator('#schedule-type').selectOption(schedule);
    for (const [selector, value, action] of controls) {
      if (action === 'fill') await page.locator(selector).fill(value);
      else await page.locator(selector).selectOption(value);
    }
    await page.locator('#preview-button').click();
    await expect(page.locator('#preview')).toBeVisible();
    const preview = requests(fixture, 'POST', '/api/tma/reminder-preview')[0].body;
    expect(preview).toMatchObject({ schedule_type: schedule, start_at: '2035-05-20T12:00',
      interval_days: null, interval_weeks: null, day_of_week: null, month_week_number: null, month_day: null, ...expected });
    await page.locator('#save-button').click();
    await expect(content(page)).toBeVisible();
    expect(requests(fixture, 'POST', '/api/tma/reminders')[0].body).toEqual(preview);
    await content(page).click();
    await expect(page.locator('#schedule-type')).toBeDisabled();
    await expect(page.locator('#reminder-kind')).toBeDisabled();
    await expect(page.locator('#start-date-field')).toBeHidden();
    await expect(page.locator('#start-time')).toBeVisible();
  });
}

test('yearly edit sends February 29 without exposing a fake year and displays backend next date', async ({ page, fixture }) => {
  fixture.store.reset({ reminders: [reminder({ schedule_type: 'yearly_date', is_repeating: true,
    start_at: '2023-06-01T12:00:00+05:00', next_run_at: '2035-06-01T12:00:00+05:00' })] });
  await openApp(page, fixture);
  await content(page).click();
  await expect(page.locator('#yearly-date-field')).toBeVisible();
  await page.locator('#yearly-month').selectOption('2');
  await page.locator('#yearly-day').selectOption('29');
  await page.locator('#start-time').fill('08:15');
  // Dates are canned backend results; no scheduling algorithm is reimplemented here.
  const preview = {
    reminder_text: 'Полить тестовый цветок', reminder_kind: 'text', schedule_type: 'yearly_date',
    start_at: '2024-02-29T08:15:00+05:00', next_run_at: '2036-02-29T08:15:00+05:00',
    timezone_name: 'Asia/Yekaterinburg', is_repeating: true, period: 'каждый год 29 февраля',
    delete_after_two_days: false, requires_completion: false, repeat_interval_minutes: null,
  };
  fixture.store.queueFault('POST', '/api/tma/reminder-preview', { rawBody: JSON.stringify(preview) });
  await page.locator('#preview-button').click();
  await expect(page.locator('#next-notification-value')).toContainText('2036');
  await expect(page.locator('#preview')).toContainText('29 февраля');
  const payload = requests(fixture, 'POST', '/api/tma/reminder-preview')[0].body;
  expect(payload).toMatchObject({ start_at: '2000-02-29T08:15', reminder_id: 1, expected_revision: 1 });
  const saved = reminder({ ...preview, revision: 2 });
  fixture.store.queueFault('PUT', '/api/tma/reminders/1', { rawBody: JSON.stringify(saved) });
  await page.locator('#save-button').click();
  await expect(content(page)).toContainText('2036');
  expect(requests(fixture, 'PUT', '/api/tma/reminders/1')[0].body.start_at).toBe('2000-02-29T08:15');
});

for (const action of ['save', 'preview']) {
  test(`${action} HTTP 500 keeps the draft and re-enables form controls`, async ({ page, fixture }) => {
    await openApp(page, fixture);
    await createDraft(page);
    const pathname = action === 'save' ? '/api/tma/reminders' : '/api/tma/reminder-preview';
    fixture.store.queueFault('POST', pathname, { status: 500 });
    await page.locator(action === 'save' ? '#save-button' : '#preview-button').click();
    await expect(page.locator('#form-status')).toContainText('ошибки сервера');
    await expect(page.locator('#reminder-text')).toHaveValue('Купить тестовый чай');
    await expect(page.locator('#reminder-text')).toBeEnabled();
    await expect(page.locator('#save-button')).toBeEnabled();
    await expect(page.locator(action === 'save' ? '#save-button' : '#preview-button')).toBeFocused();
    expect(fixture.store.reminders).toHaveLength(0);
  });
}

test('422 validation error names the field without discarding the draft', async ({ page, fixture }) => {
  await openApp(page, fixture);
  await createDraft(page);
  fixture.store.queueFault('POST', '/api/tma/reminders', { status: 422,
    body: { detail: [{ loc: ['body', 'start_at'], msg: 'Input should be a valid datetime' }] } });
  await page.locator('#save-button').click();
  await expect(page.locator('#form-status')).toContainText('Время срабатывания: укажи корректные дату и время');
  await expect(page.locator('#reminder-text')).toHaveValue('Купить тестовый чай');
  await expect(page.locator('#start-date')).toHaveValue('2035-05-20');
  expect(fixture.store.reminders).toHaveLength(0);
});

test('preview timeout aborts after 20 seconds and restores the form', async ({ page, fixture }) => {
  await page.clock.install();
  await openApp(page, fixture);
  await createDraft(page);
  await withHeldResponse(page, '/api/tma/reminder-preview', async (reached) => {
    await page.locator('#preview-button').click();
    await reached;
    await expect(page.locator('#reminder-text')).toBeDisabled();
    await page.clock.fastForward(20_001);
    await expect(page.locator('#form-status')).toContainText('отвечает слишком долго');
    await expect(page.locator('#reminder-text')).toBeEnabled();
    await expect(page.locator('#reminder-text')).toHaveValue('Купить тестовый чай');
    await expect(page.locator('#preview-button')).toBeFocused();
  });
  await page.locator('#preview-button').click();
  await expect(page.locator('#preview')).toBeVisible();
  expect(fixture.store.reminders).toHaveLength(0);
});
