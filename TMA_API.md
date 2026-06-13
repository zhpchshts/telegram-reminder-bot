# TMA API contract

Контракт HTTP API для будущего Telegram Mini App.

Production runtime пока остаётся polling-only. FastAPI runtime опциональный. Важно: create/update/delete endpoints должны выполняться в том же процессе, где живёт APScheduler, иначе отдельный API-процесс сможет изменить SQLite, но не сможет корректно управлять scheduler jobs.

## Auth

Все `/api/tma/...` endpoints требуют заголовок:

```http
X-Telegram-Init-Data: <Telegram WebApp initData>
```

Backend валидирует Telegram Mini App `initData` и берёт `chat_id` только из подписанных данных Telegram.

Для endpoints вида `/api/chats/{chat_id}/...` backend дополнительно проверяет, что `chat.id` из signed `initData` совпадает с `chat_id` в path.

Ошибки:

- `401` — initData отсутствует или невалиден;
- `403` — signed `chat_id` не совпадает с `chat_id` в path.

## Public endpoint

```http
GET /health
```

Response:

```json
{
  "status": "ok"
}
```

## Main TMA endpoints

```http
GET    /api/tma/context
GET    /api/tma/reminder-options
GET    /api/tma/bootstrap

GET    /api/tma/reminders
POST   /api/tma/reminders
PUT    /api/tma/reminders/{reminder_id}
DELETE /api/tma/reminders/{reminder_id}

POST   /api/tma/reminder-preview

GET    /api/tma/timezone
PUT    /api/tma/timezone
```

Для Mini App предпочтительнее использовать именно `/api/tma/...`, а не `/api/chats/{chat_id}/...`, потому что frontend не должен сам выбирать `chat_id`.

## Bootstrap

```http
GET /api/tma/bootstrap
```

Возвращает всё, что нужно Mini App при старте:

```json
{
  "context": {
    "chat_id": -1001234567890,
    "timezone_name": "Asia/Yekaterinburg",
    "chat_type": "group",
    "start_param": null,
    "user": {
      "id": 123,
      "first_name": "Eugene"
    },
    "chat": {
      "id": -1001234567890,
      "type": "group",
      "title": "Дом"
    },
    "auth_date": 1781352000
  },
  "reminder_options": {
    "schedule_types": [],
    "weekdays": [],
    "month_week_numbers": [],
    "month_days": []
  },
  "active_reminders": []
}
```

## ReminderResponse

Все list/create/update responses возвращают напоминания в одном формате:

```json
{
  "id": 42,
  "chat_id": -1001234567890,
  "reminder_text": "Заказать воду",
  "schedule_type": "every_days",
  "start_at": "2099-06-10T12:12:00+05:00",
  "timezone_name": "Asia/Yekaterinburg",
  "is_repeating": true,
  "period": "каждые 3 дн.",
  "interval_days": 3,
  "interval_weeks": null,
  "day_of_week": null,
  "month_week_number": null,
  "month_day": null
}
```

Frontend должен использовать готовые display fields:

- `is_repeating`;
- `period`.

Frontend не должен дублировать backend-логику форматирования расписаний.

## Create/update request

Используется для:

```http
POST /api/tma/reminders
PUT  /api/tma/reminders/{reminder_id}
POST /api/tma/reminder-preview
```

Пример:

```json
{
  "reminder_text": "Заказать воду",
  "schedule_type": "every_days",
  "start_at": "2099-06-10T12:12:00",
  "timezone_name": "Asia/Yekaterinburg",
  "interval_days": 3,
  "interval_weeks": null,
  "day_of_week": null,
  "month_week_number": null,
  "month_day": null
}
```

Если `start_at` приходит без offset, backend интерпретирует его в `timezone_name` и возвращает нормализованное значение с timezone offset.

## Schedule types

### once

Одноразовое напоминание.

Required fields: none.

### every_days

Повтор каждые N дней.

Required fields:

```json
["interval_days"]
```

### every_week

Повтор каждые N недель в выбранный день недели.

Required fields:

```json
["interval_weeks", "day_of_week"]
```

### monthly_weekday

Повтор в N-й день недели месяца.

Required fields:

```json
["month_week_number", "day_of_week"]
```

### monthly_day

Повтор в конкретный день месяца.

Required fields:

```json
["month_day"]
```

## Preview

```http
POST /api/tma/reminder-preview
```

Endpoint валидирует форму и возвращает preview без создания записи в SQLite и без изменения scheduler jobs.

Response:

```json
{
  "reminder_text": "Заказать воду",
  "schedule_type": "every_days",
  "start_at": "2099-06-10T12:12:00+05:00",
  "timezone_name": "Asia/Yekaterinburg",
  "is_repeating": true,
  "period": "каждые 3 дн."
}
```

## Timezone

```http
GET /api/tma/timezone
PUT /api/tma/timezone
```

PUT request:

```json
{
  "timezone_name": "Europe/Moscow"
}
```

Response:

```json
{
  "chat_id": -1001234567890,
  "timezone_name": "Europe/Moscow"
}
```

## Frontend integration notes

Mini App frontend должен:

1. Взять `Telegram.WebApp.initData`.
2. Передавать его во все API-запросы в header `X-Telegram-Init-Data`.
3. При старте вызвать `GET /api/tma/bootstrap`.
4. Для формы использовать `reminder_options`.
5. Для preview вызвать `POST /api/tma/reminder-preview`.
6. Для создания вызвать `POST /api/tma/reminders`.
7. Для редактирования вызвать `PUT /api/tma/reminders/{reminder_id}`.
8. Для удаления вызвать `DELETE /api/tma/reminders/{reminder_id}`.
9. Для отображения периода использовать `period` из backend response.