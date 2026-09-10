// Local-only UI fixture. It never imports the backend, reads user data, or calls Telegram.
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');

const TMA_ROOT = path.resolve(__dirname, '../../tma');
const CHAT_ID = -1001234567890;
const DEFAULT_TIMEZONE = 'Asia/Yekaterinburg';
const SDK = `window.Telegram = { WebApp: {
  initData: 'synthetic-browser-test-init-data', platform: 'test', version: 'test',
  ready() {}, expand() {}
} };`;

const OPTIONS = {
  schedule_types: [
    ['once', 'Один раз', []],
    ['yearly_date', 'Каждый год в дату', []],
    ['every_days', 'Каждые N дней', ['interval_days']],
    ['every_week', 'Каждые N недель по дню недели', ['interval_weeks', 'day_of_week']],
    ['monthly_weekday', 'Каждый месяц в N-й день недели', ['month_week_number', 'day_of_week']],
    ['monthly_day', 'Каждый месяц в день месяца', ['month_day']],
  ].map(([value, label, required_fields]) => ({ value, label, required_fields })),
  weekdays: ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'].map((value, index) => ({
    value,
    label: ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'][index],
  })),
  month_week_numbers: [1, 2, 3, 4, 5],
  month_days: [...Array.from({ length: 31 }, (_, index) => index + 1), 0],
  completion_repeat_intervals: [[15, '15 минут'], [30, '30 минут'], [60, '1 час'],
    [120, '2 часа'], [240, '4 часа'], [480, '8 часов'], [720, '12 часов'], [1440, '24 часа']]
    .map(([value, label]) => ({ value, label })),
  completion_reminder_text_max_length: 3900,
  reminder_text_max_length: 3900,
  weather_reminder_text_max_length: 600,
  weather_location_max_length: 100,
  weather_location_max_count: 5,
};

function reminder(overrides = {}) {
  const value = {
    id: 1, chat_id: CHAT_ID, reminder_text: 'Полить тестовый цветок', reminder_kind: 'text',
    delete_after_two_days: false, requires_completion: false, repeat_interval_minutes: null,
    awaiting_completion: false, schedule_type: 'once', start_at: '2035-05-20T12:00:00+05:00',
    next_run_at: '2035-05-20T12:00:00+05:00', timezone_name: DEFAULT_TIMEZONE,
    is_repeating: false, period: 'одноразовое', interval_days: null, interval_weeks: null,
    day_of_week: null, month_week_number: null, month_day: null, revision: 1,
    ...overrides,
  };
  return value;
}

function responseFromPayload(payload, overrides = {}) {
  const { expected_revision, reminder_id, ...fields } = payload;
  // Only UI serialization is under test; this is deliberately not a scheduler.
  const offsets = { 'Asia/Yekaterinburg': '+05:00', 'Europe/Moscow': '+03:00', 'UTC': '+00:00' };
  const hasOffset = /(?:Z|[+-]\d\d:\d\d)$/.test(fields.start_at);
  if (!hasOffset && !offsets[fields.timezone_name]) {
    throw new Error('Use a canned response for timezones outside the fixed fixture offsets');
  }
  const seconds = fields.start_at.length === 16 ? ':00' : '';
  const startAt = hasOffset ? fields.start_at : `${fields.start_at}${seconds}${offsets[fields.timezone_name]}`;
  return reminder({
    ...fields, start_at: startAt, next_run_at: startAt,
    is_repeating: fields.schedule_type !== 'once',
    period: fields.schedule_type === 'once' ? 'одноразовое' : 'повторяющееся',
    ...overrides,
  });
}

function createStore() {
  return {
    reminders: [], timezone: DEFAULT_TIMEZONE, requests: [], faults: [], idempotency: new Map(),
    nextId: 1,
    reset(data = {}) {
      this.reminders = (data.reminders || []).map((item) => reminder(item));
      this.timezone = data.timezone || DEFAULT_TIMEZONE;
      this.nextId = Math.max(0, ...this.reminders.map((item) => item.id)) + 1;
      this.requests = [];
      this.faults = [];
      this.idempotency.clear();
    },
    queueFault(method, pathname, fault) {
      this.faults.push({ method, pathname, ...fault });
    },
  };
}

async function readJson(request) {
  let text = '';
  for await (const chunk of request) {
    text += chunk;
    if (text.length > 100_000) throw new Error('Fixture request too large');
  }
  return text ? JSON.parse(text) : null;
}

function json(response, status, value) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(value));
}

async function createFixtureServer({ host = '127.0.0.1', port = 0 } = {}) {
  if (host !== '127.0.0.1') throw new Error('The synthetic fixture must only bind to loopback');
  const store = createStore();
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, 'http://127.0.0.1');
      const pathname = url.pathname;
      const method = request.method;
      if (pathname === '/__test/state' && method === 'GET') {
        return json(response, 200, { reminders: store.reminders, requests: store.requests, timezone: store.timezone });
      }
      if (pathname === '/__test/reset' && method === 'POST') {
        store.reset(await readJson(request) || {});
        return json(response, 200, { reset: true });
      }
      if (pathname === '/__test/fault' && method === 'POST') {
        const { method: targetMethod, pathname: targetPath, ...fault } = await readJson(request);
        store.queueFault(targetMethod, targetPath, fault);
        return json(response, 200, { queued: true });
      }
      if (pathname === '/telegram-web-app.js') {
        response.writeHead(200, { 'Content-Type': 'text/javascript' });
        return response.end(SDK);
      }
      const asset = { '/': 'index.html', '/tma/': 'index.html', '/tma/index.html': 'index.html',
        '/tma/app.js': 'app.js', '/tma/styles.css': 'styles.css' }[pathname];
      if (asset && method === 'GET') {
        let body = await fs.readFile(path.join(TMA_ROOT, asset), 'utf8');
        if (asset === 'index.html') {
          body = body.replace(/https:\/\/telegram\.org\/js\/telegram-web-app\.js\?[^"']+/, '/telegram-web-app.js');
        }
        response.writeHead(200, { 'Content-Type': {
          'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8',
          'styles.css': 'text/css; charset=utf-8',
        }[asset], 'Cache-Control': 'no-store' });
        return response.end(body);
      }
      if (!pathname.startsWith('/api/tma/')) return json(response, 404, { detail: 'Not found' });
      const body = await readJson(request);
      const entry = { method, pathname, query: Object.fromEntries(url.searchParams), body,
        idempotencyKey: request.headers['idempotency-key'] || null };
      store.requests.push(entry);
      const faultIndex = store.faults.findIndex((fault) => fault.method === method && fault.pathname === pathname);
      const fault = faultIndex < 0 ? null : store.faults.splice(faultIndex, 1)[0];
      if (fault?.delayMs) await new Promise((resolve) => setTimeout(resolve, fault.delayMs));
      if (fault?.disconnect) return response.destroy();
      if (fault?.status) return json(response, fault.status, fault.body ?? { detail: 'Synthetic API error' });
      if (fault && 'rawBody' in fault) {
        response.writeHead(200, { 'Content-Type': fault.contentType || 'application/json' });
        return response.end(fault.rawBody);
      }
      let result;
      if (pathname === '/api/tma/bootstrap' && method === 'GET') {
        result = { context: { auth_date: 2_000_000_000, user: { id: 123456, first_name: 'Тест' },
          chat: { id: CHAT_ID, title: 'Тестовый чат', type: 'supergroup' }, chat_id: CHAT_ID,
          timezone_name: store.timezone, chat_type: 'supergroup', start_param: 'synthetic' },
        reminder_options: OPTIONS, active_reminders: store.reminders };
      } else if (pathname === '/api/tma/reminders' && method === 'GET') {
        result = store.reminders;
      } else if (pathname === '/api/tma/reminders' && method === 'POST') {
        const cached = store.idempotency.get(entry.idempotencyKey);
        if (cached && cached.fingerprint !== JSON.stringify(body)) {
          return json(response, 409, { detail: 'Idempotency key reused with different payload' });
        }
        result = cached ? store.reminders.find((item) => item.id === cached.result.id) || cached.result
          : responseFromPayload(body, { id: store.nextId++ });
        if (!cached) {
          store.reminders.push(result);
          if (entry.idempotencyKey) store.idempotency.set(entry.idempotencyKey, { fingerprint: JSON.stringify(body), result });
        }
      } else if (pathname === '/api/tma/reminder-preview' && method === 'POST') {
        if (body.reminder_id) {
          const current = store.reminders.find((item) => item.id === body.reminder_id);
          if (!current) return json(response, 404, { detail: 'Reminder not found.' });
          if (current.revision !== body.expected_revision) {
            return json(response, 409, { detail: 'Reminder revision conflict.' });
          }
          if (current.schedule_type !== body.schedule_type || current.reminder_kind !== body.reminder_kind) {
            return json(response, 400, { detail: 'Reminder kind and schedule cannot be changed.' });
          }
        }
        const full = responseFromPayload(body);
        result = Object.fromEntries(['reminder_text', 'reminder_kind', 'delete_after_two_days',
          'requires_completion', 'repeat_interval_minutes', 'schedule_type', 'start_at',
          'timezone_name', 'is_repeating', 'period'].map((key) => [key, full[key]]));
        result.next_run_at = body.reminder_id ? full.next_run_at : null;
      } else if (pathname === '/api/tma/timezone' && method === 'PUT') {
        try { new Intl.DateTimeFormat('en', { timeZone: body.timezone_name }); }
        catch { return json(response, 400, { detail: 'Invalid timezone name.' }); }
        store.timezone = body.timezone_name;
        result = { chat_id: CHAT_ID, timezone_name: store.timezone };
      } else if (/^\/api\/tma\/reminders\/\d+$/.test(pathname) && ['PUT', 'DELETE'].includes(method)) {
        const id = Number(pathname.split('/').pop());
        const index = store.reminders.findIndex((item) => item.id === id);
        if (index < 0) return json(response, 404, { detail: 'Reminder not found.' });
        const revision = method === 'PUT' ? body.expected_revision : Number(url.searchParams.get('expected_revision'));
        if (revision !== store.reminders[index].revision) {
          return json(response, 409, { detail: 'Reminder revision conflict.' });
        }
        if (method === 'PUT') {
          if (store.reminders[index].schedule_type !== body.schedule_type || store.reminders[index].reminder_kind !== body.reminder_kind) {
            return json(response, 400, { detail: 'Reminder kind and schedule cannot be changed.' });
          }
          result = responseFromPayload(body, { id, revision: revision + 1 });
          store.reminders[index] = result;
        } else {
          store.reminders.splice(index, 1);
          result = { id, chat_id: CHAT_ID, deleted: true };
        }
      } else return json(response, 404, { detail: 'Unknown fixture API endpoint' });
      if (fault?.commitThenDisconnect) return response.destroy();
      return json(response, method === 'POST' && pathname === '/api/tma/reminders' ? 201 : 200, result);
    } catch (error) {
      json(response, 500, { detail: `Fixture error: ${error.message}` });
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, resolve);
  });
  return { url: `http://${host}:${server.address().port}`, store,
    close: () => new Promise((resolve, reject) => {
      server.close((error) => error ? reject(error) : resolve());
      server.closeAllConnections();
    }),
  };
}

module.exports = { createFixtureServer, reminder };

if (require.main === module) {
  createFixtureServer({ port: 4173 }).then(({ url }) => {
    process.stdout.write(`Synthetic Mini App fixture: ${url}/tma/\n`);
  }).catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
