# Telegram Reminder Bot / Mini App «Незабудка»

Telegram Reminder Bot — бот для напоминаний в Telegram-чатах с Telegram Mini App «Незабудка».

Основной пользовательский сценарий — управление напоминаниями через Mini App: создать, посмотреть, изменить или удалить напоминание можно в интерфейсе внутри Telegram. Текстовые команды остаются запасным способом управления.

Напоминания принадлежат Telegram-чату, а не отдельному пользователю: участники одного чата видят и управляют напоминаниями этого чата, а данные разных чатов изолированы по `chat_id`.

## Возможности

Поддерживается:

* создание одноразовых напоминаний;
* создание ежегодных напоминаний в конкретную дату;
* повтор каждые N дней;
* повтор каждые N недель в выбранный день недели;
* повтор в N-й день недели месяца, например в первый понедельник месяца;
* повтор в конкретный день месяца, например 11 числа каждого месяца;
* предварительный просмотр следующего срабатывания перед созданием;
* просмотр активных напоминаний текущего чата;
* редактирование активных напоминаний;
* удаление активных напоминаний;
* настройка таймзоны для каждого чата;
* восстановление активных напоминаний после перезапуска;
* периодический healthcheck в заданный Telegram chat_id.

## Как это устроено

Приложение состоит из нескольких частей:

* Telegram bot runtime на `aiogram`;
* планировщик напоминаний на `APScheduler`;
* SQLite-база для хранения напоминаний и настроек чатов;
* FastAPI HTTP API для Telegram Mini App;
* статические файлы Mini App в каталоге `tma/`.

Бот работает через long polling. Webhook не используется.

Mini App отдаётся backend-приложением по пути:

```text
/tma
```

HTTP API для Mini App находится под:

```text
/api/tma/...
```

Технический healthcheck доступен по пути:

```text
/health
```

## Модель данных и доступа

Текущая модель продукта:

* напоминания принадлежат Telegram-чату;
* внутри одного чата любой участник может создавать, смотреть, редактировать и удалять напоминания этого чата;
* между чатами данные изолированы по `chat_id`;
* ролевой модели нет;
* таймзона задаётся на чат;
* таймзона сохраняется в напоминание на момент создания;
* список напоминаний показывает только активные напоминания текущего чата.

## Управление через Telegram

Основной способ управления — Mini App «Незабудка».

Команды:

```text
/start
/help
/app
```

открывают Mini App или показывают кнопку «Открыть Незабудку».

Текстовые команды остаются запасным способом управления:

| Команда                | Назначение                                  |
| ---------------------- | ------------------------------------------- |
| `/examples`            | Показать примеры текстовых команд           |
| `/list`                | Показать активные напоминания текущего чата |
| `/delete ID`           | Удалить напоминание текущего чата           |
| `/timezone`            | Показать текущую таймзону чата              |
| `/timezone Area/City`  | Задать таймзону чата                        |
| `/remind ...`          | Создать одноразовое напоминание             |
| `/every_days ...`      | Создать повтор каждые N дней                |
| `/every_week ...`      | Создать повтор каждые N недель              |
| `/monthly_weekday ...` | Создать повтор в N-й день недели месяца     |
| `/monthly_day ...`     | Создать повтор в конкретный день месяца     |

Подробные примеры текстовых команд доступны через:

```text
/examples
```

## Формат уведомлений

При срабатывании напоминания бот отправляет только текст напоминания.

Например, если создано напоминание:

```text
Позвонить в поддержку
```

то в момент срабатывания бот отправит:

```text
Позвонить в поддержку
```

Без ID, периода, таймзоны и другой служебной информации.

## Технологии

Проект использует:

* Python;
* aiogram;
* APScheduler;
* FastAPI;
* Uvicorn;
* SQLite;
* HTML/CSS/JavaScript для Telegram Mini App;
* Docker;
* Docker Compose;
* ruff;
* pytest;
* GitHub Actions.

## Структура проекта

```text
telegram-reminder-bot/
├── app/
│   ├── api.py                  # FastAPI routes
│   ├── api_auth.py             # авторизация Telegram Mini App
│   ├── api_models.py           # API-модели
│   ├── config.py               # конфигурация приложения
│   ├── database.py             # SQLite-слой
│   ├── handlers.py             # Telegram bot handlers
│   ├── reminder_models.py      # доменные модели напоминаний
│   ├── reminder_service.py     # сервисный слой напоминаний
│   ├── runtime.py              # запуск bot runtime и API runtime
│   ├── schedule_calculations.py
│   └── scheduler.py
├── tma/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── tests/
├── scripts/
├── Dockerfile
├── docker-compose.yml
├── DEPLOY.md
├── README.md
├── requirements.txt
└── pyproject.toml
```

## Локальный запуск

### 1. Клонировать репозиторий

```bash
git clone https://github.com/zhpchshts/telegram-reminder-bot.git
cd telegram-reminder-bot
```

### 2. Создать виртуальное окружение

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Если PowerShell запрещает запуск скриптов в текущем окне:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Установить зависимости

```bash
pip install -r requirements.txt
```

### 4. Создать `.env`

Скопировать пример:

```bash
cp .env.example .env
```

Для Windows можно создать `.env` вручную.

Минимальный пример:

```env
BOT_TOKEN=your_telegram_bot_token
APP_TIMEZONE=Asia/Yekaterinburg
DB_PATH=reminders.db
HEALTHCHECK_CHAT_ID=
HEALTHCHECK_INTERVAL_MINUTES=360
API_ALLOWED_ORIGINS=
TMA_URL=
```

Переменные:

| Переменная                     | Назначение                                      |
| ------------------------------ | ----------------------------------------------- |
| `BOT_TOKEN`                    | Токен Telegram-бота из BotFather                |
| `APP_TIMEZONE`                 | Дефолтная таймзона приложения                   |
| `DB_PATH`                      | Путь к SQLite-базе                              |
| `HEALTHCHECK_CHAT_ID`          | Chat ID для периодических healthcheck-сообщений |
| `HEALTHCHECK_INTERVAL_MINUTES` | Интервал healthcheck-сообщений в минутах        |
| `API_ALLOWED_ORIGINS`          | Список origin'ов для CORS через запятую         |
| `TMA_URL`                      | Публичный HTTPS URL Mini App                    |

Если `HEALTHCHECK_CHAT_ID` не задан, периодические healthcheck-сообщения не отправляются.

### 5. Запустить приложение

```bash
python bot.py
```

## Локальный запуск через Docker

Собрать образ:

```bash
docker build -t telegram-reminder-bot:latest .
```

Запустить через Docker Compose:

```bash
docker compose up -d
```

Проверить контейнер:

```bash
docker compose ps
docker logs --tail 80 telegram-reminder-bot
```

Остановить:

```bash
docker compose stop
```

В Docker Compose HTTP API публикуется на хосте локально:

```text
127.0.0.1:8000
```

Проверить healthcheck:

```bash
curl http://127.0.0.1:8000/health
```

Проверить Mini App static:

```bash
curl -I http://127.0.0.1:8000/tma/
```

## Проверки

Для backend/Python-правок:

```bash
ruff format
ruff check .
pytest
git diff --check
```

Для frontend-only правок:

```bash
git diff --check
```

JavaScript Mini App проверяется в GitHub Actions через:

```bash
node --check tma/app.js
```

Локально Node ставить не обязательно, если frontend-check достаточно проверить в CI.

## Production deployment

Эксплуатационная документация находится в [`DEPLOY.md`](DEPLOY.md).

Кратко:

* production работает через Docker Compose;
* SQLite-база хранится на хосте и монтируется в контейнер;
* Telegram bot работает через long polling;
* FastAPI API публикуется локально и должен быть закрыт reverse proxy;
* Mini App требует публичный HTTPS URL;
* перед deploy создаётся backup базы;
* после deploy контейнер пересоздаётся через Docker Compose.

Не нужно запускать одновременно Docker-контейнер и старый systemd-сервис Python-бота: два процесса с одним `BOT_TOKEN` будут конфликтовать в long polling.

## Healthcheck

Бот умеет отправлять периодические служебные сообщения о состоянии в заданный Telegram chat_id.

Пример:

```text
✅ Бот работает.

Время сервера UTC: ...
Scheduler: running
Запланированных jobs: ...
Активных напоминаний в базе: ...
Чатов с активными напоминаниями: ...
```

HTTP healthcheck возвращает техническое состояние API:

```json
{
  "status": "ok",
  "active_chats_count": 1
}
```

## Текущий статус

Проект находится на стадии production MVP.

Уже реализованы:

* Telegram-бот для напоминаний;
* Telegram Mini App «Незабудка»;
* основные типы одноразовых и повторяющихся напоминаний;
* настройка таймзоны чата;
* изоляция данных по Telegram-чатам;
* сохранение и восстановление активных напоминаний после перезапуска;
* FastAPI HTTP API для Mini App;
* отдача TMA-статики по `/tma`;
* periodic healthcheck;
* автотесты для ключевой логики;
* CI-проверки в GitHub Actions;
* Dockerfile и Docker Compose-конфигурация;
* production-деплой через Docker Compose;
* эксплуатационная документация в [`DEPLOY.md`](DEPLOY.md).

Ближайший фокус:

* обновить эксплуатационную документацию под Mini App runtime;
* развязать frontend-deploy и backend-deploy для TMA-статики;
* улучшить обработку ошибок в Mini App;
* доработать UX формы создания и редактирования напоминаний.
