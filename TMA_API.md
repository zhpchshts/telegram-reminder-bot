# TMA API contract

Контракт HTTP API действующей Telegram Mini App.

Канонический production runtime — `python -m app.main_with_api`: polling бота,
FastAPI и APScheduler работают в одном процессе. Отдельный API-процесс не
поддерживается, потому что изменения SQLite должны сразу синхронизироваться с
scheduler jobs.

## Auth и кэширование

Все `/api/tma/...` endpoints требуют заголовок:

```http
X-Telegram-Init-Data: <Telegram WebApp initData>
```

Backend проверяет подпись Telegram Mini App `initData` и срок `auth_date`.
Контекст чата берётся из подписанного launch token, созданного ботом;
`chat_id` из frontend не считается доверенным.
Если Telegram передал signed `chat`, его id/type также должны совпасть с launch
context. Ссылка `/app` действует 30 дней и не привязана к конкретному
пользователю, поэтому одну кнопку могут открыть разные пользователи.

Для endpoints вида `/api/chats/{chat_id}/...` backend дополнительно проверяет,
что подписанный chat совпадает с `chat_id` в path. Mini App должна использовать
`/api/tma/...`, чтобы не выбирать `chat_id` на клиенте.

Ошибки авторизации:

- `401` — initData отсутствует, устарел или невалиден;
- `403` — signed chat не совпадает с launch context/path.

Все ответы `/api/...`, включая ошибки, возвращаются с
`Cache-Control: private, no-store` и `Vary: X-Telegram-Init-Data`.

## Состояние процесса

```http
GET|HEAD /health
GET|HEAD /ready
```

`/health` — минимальный liveness и отвечает `200 {"status":"ok"}` без метрик
и пользовательских данных. `/ready` отвечает `200 {"status":"ready"}` только
после запуска bot/scheduler, восстановления напоминаний, проверки обязательных
фоновых jobs и таблиц SQLite; до этого возвращает `503`.

## Основные TMA endpoints

```http
GET    /api/tma/context
GET    /api/tma/reminder-options
GET    /api/tma/bootstrap

GET    /api/tma/reminders
POST   /api/tma/reminders
PUT    /api/tma/reminders/{reminder_id}
DELETE /api/tma/reminders/{reminder_id}?expected_revision={revision}

POST   /api/tma/reminder-preview

GET    /api/tma/timezone
PUT    /api/tma/timezone
```

## Bootstrap

```http
GET /api/tma/bootstrap
```

Возвращает подписанный контекст, ограничения формы и активные напоминания:

```json
{
  "context": {
    "chat_id": -1001234567890,
    "timezone_name": "Asia/Yekaterinburg",
    "chat_type": "group",
    "start_param": "signed-launch-token",
    "user": {"id": 123, "first_name": "Eugene"},
    "chat": {"id": -1001234567890, "type": "group", "title": "Дом"},
    "auth_date": 1781352000
  },
  "reminder_options": {
    "schedule_types": [],
    "weekdays": [],
    "month_week_numbers": [],
    "month_days": [],
    "completion_repeat_intervals": [],
    "completion_reminder_text_max_length": 0,
    "reminder_text_max_length": 0,
    "weather_reminder_text_max_length": 0,
    "weather_location_max_length": 0,
    "weather_location_max_count": 0
  },
  "active_reminders": []
}
```

Числовые лимиты в примере намеренно не дублируют конфигурацию backend: frontend
должен брать фактические значения из `reminder_options`.

Для `reminder_kind: "weather"` frontend применяет одновременно общий
`reminder_text_max_length`, специальный `weather_reminder_text_max_length`,
максимальную длину каждого названия `weather_location_max_length` и число
уникальных названий `weather_location_max_count`. Для совместимости со старым
bootstrap безопасные fallback равны соответственно 3900, 600, 100 и 5.

## ReminderResponse

List/create/update возвращают напоминания в одном формате:

```json
{
  "id": 42,
  "chat_id": -1001234567890,
  "reminder_text": "Заказать воду",
  "reminder_kind": "text",
  "delete_after_two_days": true,
  "requires_completion": false,
  "repeat_interval_minutes": null,
  "awaiting_completion": false,
  "schedule_type": "every_days",
  "start_at": "2099-06-10T12:12:00+05:00",
  "next_run_at": "2099-06-10T12:12:00+05:00",
  "timezone_name": "Asia/Yekaterinburg",
  "is_repeating": true,
  "period": "каждые 3 дн.",
  "interval_days": 3,
  "interval_weeks": null,
  "day_of_week": null,
  "month_week_number": null,
  "month_day": null,
  "revision": 1
}
```

`next_run_at` может быть `null` или отсутствовать, когда scheduler job ещё не
доступен. Frontend использует готовые display fields `is_repeating` и `period`,
а `revision` — для защиты от перезаписи изменений из другого окна.

Для расписания `monthly_day` значение `month_day: 0` означает последний
календарный день месяца.

## Создание

```http
POST /api/tma/reminders
Idempotency-Key: <8..128 ASCII-символов [A-Za-z0-9._:-]>
```

```json
{
  "reminder_text": "Заказать воду",
  "reminder_kind": "text",
  "delete_after_two_days": true,
  "requires_completion": false,
  "repeat_interval_minutes": null,
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

Успех возвращает `201`. Повтор с тем же ключом и тем же payload возвращает то
же сохранённое напоминание, поэтому после timeout/network/5xx безопасно повторить
неизменённый запрос с прежним ключом. Возможные специальные ответы:

- `409` — тот же ключ уже связан с другим payload;
- `425` — первый запрос ещё завершает постановку в scheduler; повторить позже;
- `503` — запись не подтверждена scheduler и создание отменено.

Без `Idempotency-Key` endpoint сохраняет обратную совместимость, но не защищает
повтор POST после неизвестного сетевого результата.

## Редактирование и удаление

```http
PUT /api/tma/reminders/{reminder_id}
DELETE /api/tma/reminders/{reminder_id}?expected_revision={revision}
```

PUT принимает тот же payload, что POST, и обязательное поле:

```json
{
  "expected_revision": 3
}
```

Это поле входит в полный JSON PUT рядом с остальными полями. Успешное изменение
увеличивает `revision`. Для PUT, DELETE и preview редактирования несовпавшая
revision возвращает `409`. Для edit preview/PUT клиент сохраняет открытый draft,
загружает свежий список и новую `revision`, но не повторяет изменяющий запрос
автоматически: пользователь сначала заново проверяет preview и явно сохраняет
форму. Для DELETE клиент остаётся в списке, обновляет его и предлагает повторить
удаление по свежей версии. Удаление возвращает:

```json
{"id": 42, "chat_id": -1001234567890, "deleted": true}
```

## Preview

```http
POST /api/tma/reminder-preview
```

Для новой записи endpoint принимает payload создания. При редактировании к нему
добавляются обязательные для этого сценария `reminder_id` и
`expected_revision`. Preview валидирует форму и рассчитывает отображаемые поля,
не создавая запись в SQLite и не изменяя scheduler jobs.

```json
{
  "reminder_text": "Заказать воду",
  "reminder_kind": "text",
  "delete_after_two_days": true,
  "requires_completion": false,
  "repeat_interval_minutes": null,
  "schedule_type": "every_days",
  "start_at": "2099-06-10T12:12:00+05:00",
  "timezone_name": "Asia/Yekaterinburg",
  "is_repeating": true,
  "period": "каждые 3 дн.",
  "next_run_at": "2099-06-10T12:12:00+05:00"
}
```

## Расписания и валидация

Поддерживаются `once`, `yearly_date`, `every_days`, `every_week`,
`monthly_weekday` и `monthly_day`. Обязательные поля каждого типа приходят в
`reminder_options.schedule_types[].required_fields`.

`reminder_kind` принимает `text` или `weather`. Для напоминания с подтверждением
используются `requires_completion: true` и один из разрешённых
`repeat_interval_minutes`; варианты также возвращает `reminder-options`.

Request models строгие: неизвестные поля, неверные типы, превышение лимитов и
несовместимые комбинации отклоняются. Если `start_at` приходит без offset,
backend интерпретирует его в `timezone_name` и возвращает нормализованное значение
с timezone offset.

`delete_after_two_days` — строго булева настройка автоудаления сообщения,
отправленного ботом. Если она была включена в момент успешной отправки, сообщение
попадает в постоянную очередь удаления через 47 часов 45 минут. Последующее
изменение настройки или удаление напоминания эту задачу не отменяет.

## Timezone

```http
GET /api/tma/timezone
PUT /api/tma/timezone
```

PUT request:

```json
{"timezone_name": "Europe/Moscow"}
```

Response:

```json
{"chat_id": -1001234567890, "timezone_name": "Europe/Moscow"}
```

## Frontend integration notes

1. Взять `Telegram.WebApp.initData` и передавать его во все API-запросы в
   `X-Telegram-Init-Data`.
2. При старте вызвать `GET /api/tma/bootstrap` и брать ограничения формы из
   `reminder_options`.
3. Для create хранить случайный `Idempotency-Key` до подтверждённого успеха или
   фактического изменения payload.
4. Для edit/delete хранить snapshot `revision`. При `409` edit preview/PUT не
   закрывать форму и не терять draft: загрузить свежий список/revision, попросить
   проверить preview и повторить сохранение вручную. DELETE после `409` обновляет
   список без автоматического повтора.
5. Для отображения расписаний использовать `period` и `next_run_at` из backend.
6. Считать любой ответ не-2xx ошибкой и не кэшировать API-ответы локально.
7. `401` и `403` показывать как необходимость заново открыть Mini App из нужного
   Telegram-чата; диагностический backend detail для `403` пользователю не
   показывать.
