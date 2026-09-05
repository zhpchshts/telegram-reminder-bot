# Архитектура «Незабудки»

Это компактная карта текущего кода для разработчиков и AI-агентов. Правила работы
с репозиторием находятся в [AGENTS.md](AGENTS.md), API-контракт Mini App — в
[TMA_API.md](TMA_API.md), production-процедуры — в [DEPLOY.md](DEPLOY.md).

## Точка входа и запуск

Канонический production runtime — `python -m app.main_with_api`; ту же команду
задаёт `Dockerfile`. `app.main_with_api` передаёт управление
`app.runtime.run_polling_and_api_runtime()`, который:

1. создаёт один `Bot`, `Dispatcher` и общий FastAPI `app`;
2. подключает обычные и completion-обработчики;
3. выполняет `database.init_db()`, запускает APScheduler и восстанавливает задания;
4. только после восстановления переводит `/ready` в готовое состояние;
5. совместно запускает Telegram polling и Uvicorn и останавливает вторую задачу,
   если первая завершилась или упала.

`app/runtime.py` — composition root. Другие модули не должны создавать второй
production runtime, отдельный scheduler или ещё один экземпляр бота с тем же
токеном.

## Направление зависимостей

Основной ход вызовов выглядит так:

```text
Telegram WebView -> tma/ -> api.py -> api_auth.py -> tma_auth.py + tma_launch.py
Telegram update  -> handlers.py -> reminder_parsing.py
api.py + handlers.py -> reminder_service.py + domain modules
reminder_service.py -> database.py
reminder_service.py -> scheduler.py -> database.py
scheduler.py -> completion_service.py -> database.py
scheduler.py -> weather_service.py -> database.py (cache)
completion_handlers.py -> completion_service.py
```

`app/completion_handlers.py` — отдельный Telegram-adapter для callback-кнопок.
`app/runtime.py` связывает верхние уровни. `app/api.py` также читает расчёт
следующего запуска из scheduler для ответа и проверяет scheduler в `/ready`, но
изменения напоминаний оркестрирует `reminder_service.py`. Слой базы не импортирует
HTTP-, Telegram- или service-слои.

## Владение модулей

| Область | Владелец | Ответственность |
| --- | --- | --- |
| Browser UI | `tma/index.html`, `tma/app.js`, `tma/styles.css` | Интерфейс, локальное состояние формы, вызовы только `/api/tma/*`; клиентские проверки не являются границей доверия. |
| HTTP | `app/api.py`, `app/api_models.py` | Маршруты, middleware, Pydantic-контракт, преобразование HTTP-ошибок и раздача `tma/`. |
| TMA trust boundary | `app/api_auth.py`, `app/tma_auth.py`, `app/tma_launch.py` | Проверка `initData`, срока и подписанного контекста запуска; получение серверного `chat_id`. |
| Telegram ingress | `app/handlers.py`, `app/completion_handlers.py` | Команды, ответы и callback-adapter; бизнес-операции делегируются сервисам. |
| Модель и вычисления | `app/reminder_models.py`, `app/schedule_calculations.py`, `app/reminder_parsing.py`, `app/reminder_mapping.py`, `app/formatting.py`, `app/constants.py` | Типы, разбор, вычисления расписаний, преобразование строк БД и представление. |
| Use cases | `app/reminder_service.py` | Валидация, CRUD в границах чата, idempotency/CAS и синхронизация записи с scheduler. |
| Persistence | `app/database.py` | Соединения, транзакции, запросы и атомарные переходы состояния. |
| Schema | `app/database_schema.py` | Только DDL, индексы, повторяемые миграции и ограниченные backfill/invalidation. |
| Scheduling и delivery | `app/scheduler.py` | APScheduler jobs, восстановление, catch-up, persistent delivery claims/retry, weather prefetch и очередь автоудаления сообщений. |
| Completion | `app/completion_service.py` | Доставка, повтор, claim/CAS и публикация результата напоминаний «до выполнения». |
| Weather | `app/weather_service.py` | Open-Meteo, retry/error mapping, геокодирование, построение безопасного HTML и location cache. |
| Composition/config | `app/runtime.py`, `app/main_with_api.py`, `app/config.py` | Жизненный цикл процесса и чтение конфигурации. |

## Ключевой сценарий: создание и обновление

1. Mini App отправляет `X-Telegram-Init-Data` с каждым запросом. Для создания
   `tma/app.js` добавляет `Idempotency-Key`, для обновления — `expected_revision`.
   Командный fallback получает `chat_id` непосредственно из Telegram update.
2. `api_auth.py` аутентифицирует TMA и передаёт endpoint уже проверенный
   `chat_id`. `api_models.py` нормализует HTTP-модель; `handlers.py` использует
   `reminder_parsing.py`. Оба входа приходят к `reminder_service.py`.
3. Сервис проверяет данные и заранее строит APScheduler trigger, чтобы заведомо
   неверное расписание не стало активной строкой.
4. При создании `database.py` атомарно применяет лимит чата и, если передан ключ,
   сохраняет ключ, hash payload и статус запроса. После записи сервис создаёт job;
   при ошибке нового scheduling строка деактивируется.
5. При обновлении сервис берёт локальный lock напоминания, читает запись только по
   `(reminder_id, chat_id)` и выполняет revision-CAS. Успешная запись увеличивает
   revision, сбрасывает delivery watermark и отменяет зависимые pending delivery,
   completion и подготовленный weather report. Job получает имя с новой revision;
   reconciliation сверяет scheduler с канонической строкой БД.

База — источник истины. Успешная запись обновления может сохраниться даже при
ошибке последующего reschedule; вызывающая граница получает явную ошибку, а
reconciliation работает с канонической revision.

## Ключевой сценарий: доставка и completion

1. APScheduler вызывает `run_scheduled_reminder()`. Startup restore и минутный
   worker также находят пропущенные или незавершённые срабатывания.
2. Для обычного напоминания `scheduler.py` создаёт/захватывает persistent delivery
   occurrence по `(reminder_id, revision, scheduled_for_utc)`. Claim имеет timeout,
   heartbeat, ограниченные попытки и durable retry.
3. Weather-напоминание получает подготовленный отчёт либо вызывает
   `weather_service.py`; устаревший catch-up погоды помечается обработанным без
   отправки. Обычный текст отправляется напрямую.
4. После Telegram send watermark напоминания закрывается revision-CAS, occurrence
   финализируется, а при включённом автоудалении сообщение ставится в durable
   очередь. Telegram и SQLite не образуют общей транзакции, поэтому физическая
   доставка гарантируется как at-least-once, а не exactly-once.
5. Для `requires_completion` управление переходит в `completion_service.py`:
   occurrence захватывается в БД, сообщение получает callback-кнопку, а worker
   повторяет его до завершения. Callback проходит через
   `completion_handlers.py`, атомарно сверяет occurrence, чат и сообщение,
   фиксирует пользователя и публикует/редактирует финальное состояние. Старые
   revision и заменённые сообщения не должны оживлять напоминание.

## Граница доверия TMA

`chat_id` из body, query string или состояния JavaScript не является доверенным.
Цепочка доверия одна:

1. бот создаёт launch token из Telegram `chat.id`, `chat.type` и необязательного
   display title и подписывает его секретом бота;
2. Telegram передаёт token как `start_param` внутри `initData`;
3. `tma_auth.validate_telegram_init_data()` проверяет HMAC и срок `auth_date`;
4. `tma_launch.validate_tma_launch_token()` проверяет подпись и срок token;
5. если Telegram прислал объект `chat`, его `id` и `type` сверяются с token;
6. endpoint получает `chat_id` только из проверенного `TmaLaunchContext`.

Чтение `tgWebAppData` из URL в `tma/app.js` — лишь запасной способ перенести те же
подписанные байты. Оно не ослабляет серверную проверку. Владение напоминаниями и
настройками всегда определяется чатом, а не пользователем, открывшим WebView.

## Инварианты

- **Chat scope:** чтение и мутации пользовательских объектов ограничены
  серверным `chat_id`; нельзя добавлять доверие к клиентскому идентификатору чата.
- **Timezone:** настройка чата хранится отдельно, исторический fallback —
  `Asia/Yekaterinburg`; каждое напоминание сохраняет собственную IANA timezone.
  Изменение настройки чата не переписывает существующие напоминания. Delivery-
  timestamps и watermarks хранятся как UTC.
- **Revision/CAS:** edit-preview и TMA update/delete требуют
  `expected_revision`; командный `/delete` сохраняет совместимый сценарий без
  revision. Update увеличивает revision. Scheduler jobs, delivery/completion
  occurrences и weather report cache связаны с revision и не могут закрыть более
  новую версию.
- **Idempotency:** create-key уникален внутри чата и связан с hash payload. Повтор
  того же запроса возвращает созданную запись; другой payload конфликтует;
  незавершённое создание возвращает состояние pending, а не создаёт дубликат.
- **Данные:** `reminders` и `chat_settings` — пользовательские данные. Таблицы
  delivery/completion и очередь удаления — durable operational state. Только
  `weather_location_cache` и `weather_report_cache` являются производными кэшами,
  которые можно инвалидировать явно и с тестом.

## SQLite: schema/init boundary

`app.database.init_db()` остаётся публичным фасадом. Он открывает управляемое
соединение и внутри одной transaction boundary вызывает
`app.database_schema.initialize_database_schema(connection,
migration_now_utc=...)`. Schema-модуль не открывает соединения и не содержит
бизнес-запросов; `database.py` не содержит DDL.

Инициализация выполняется runtime до старта восстановления scheduler. Миграции
должны быть повторяемыми, сохранять пользовательские строки и получать время
backfill явно. `/ready` не запускает миграции: он только проверяет доступность
обязательных таблиц `reminders`, `chat_settings`,
`reminder_completion_occurrences` и `reminder_delivery_occurrences`.

Группы таблиц:

- source data: `reminders`, `chat_settings`;
- delivery state: `reminder_delivery_occurrences`,
  `reminder_completion_occurrences`, `reminder_message_deletion_queue`;
- derived cache: `weather_location_cache`, `weather_report_cache`.

## От функции к файлам и тестам

| Функция | Основные файлы | Основные тесты |
| --- | --- | --- |
| Startup, shutdown, readiness | `main_with_api.py`, `runtime.py`, `api.py`, `Dockerfile` | `test_main_entrypoints.py`, `test_runtime.py`, `test_api_http.py` |
| TMA auth и chat context | `handlers.py`, `tma_auth.py`, `tma_launch.py`, `api_auth.py` | `test_tma_auth.py`, `test_tma_launch.py`, `test_api_auth.py`, `test_api_http.py`, `test_handlers.py` |
| TMA UI и HTTP-контракт | `tma/*`, `api.py`, `api_models.py`, `TMA_API.md` | `test_tma_ux.py`, `test_tma_completion.py`, `test_tma_auto_delete.py`, `test_api.py`, `test_api_models.py`, `test_api_http.py` |
| CRUD, CAS, idempotency | `reminder_service.py`, `database.py`, `scheduler.py` | `test_reminder_service.py`, `test_database.py`, `test_api.py`, `test_api_http.py`, `test_recurring_reminder_edit.py` |
| Парсинг и расчёт расписаний | `reminder_parsing.py`, `schedule_calculations.py`, `scheduler.py` | `test_reminder_parsing.py`, `test_schedule_calculations.py`, `test_scheduler.py` |
| Доставка, retry, restore, автоудаление | `scheduler.py`, `database.py` | `test_scheduler.py`, `test_database.py`, `test_tma_auto_delete.py` |
| Completion | `completion_handlers.py`, `completion_service.py`, `database.py`, `scheduler.py` | `test_completion_handlers.py`, `test_completion.py`, `test_tma_completion.py` |
| Weather | `weather_service.py`, `scheduler.py`, `database.py` | `test_weather_service.py`, `test_scheduler.py`, `test_database.py` |
| Telegram-команды и форматирование | `handlers.py`, `reminder_parsing.py`, `formatting.py`, `reminder_mapping.py` | `test_handlers.py`, `test_reminder_parsing.py`, `test_formatting.py`, `test_reminder_mapping.py` |
| Schema, config и deploy contract | `database_schema.py`, `database.py`, `config.py`, `Dockerfile`, `docker-compose.yml`, `scripts/*` | `test_database.py`, `test_deploy_config.py`, `test_runtime.py` |

Все пути `app/*.py` и `tests/*.py` в таблице указаны относительно одноимённых
каталогов репозитория.

## Безопасное изменение

1. Начать с [AGENTS.md](AGENTS.md), `git status --short` и строки нужной функции в
   таблице выше; прочитать ingress, service/persistence и соответствующие тесты.
2. Не обходить `reminder_service.py` из новых HTTP- или command-сценариев и не
   переносить server-side проверки только во frontend.
3. Изменять schema только повторяемой миграцией через `database_schema.py`, не
   удаляя source/delivery state. Invalidation допустима лишь для weather cache и
   должна быть закреплена migration-тестом.
4. При изменении API одновременно проверить `tma/app.js`, `api_models.py`,
   `TMA_API.md` и старый открытый WebView. При изменении env-контракта синхронно
   проверить `config.py`, `.env.example` и `DEPLOY.md`.
5. Не читать `.env*`, базы, backup и иные секреты/пользовательские данные. Не
   запускать production/deploy без отдельного разрешения; порядок описан в
   [DEPLOY.md](DEPLOY.md).

Базовые проверки из PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Если изменён `tma/app.js` и Node.js уже установлен:

```powershell
node --check tma/app.js
```

Node.js, Docker и внешние сервисы не устанавливаются и не запускаются только ради
проверки без явной необходимости и разрешения. Для Docker/Compose и production
следовать [AGENTS.md](AGENTS.md) и [DEPLOY.md](DEPLOY.md).
