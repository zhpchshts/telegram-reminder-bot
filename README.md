# Telegram Reminder Bot

Telegram Reminder Bot — бот для напоминаний в Telegram-чатах.

Бот позволяет создавать одноразовые и повторяющиеся напоминания прямо из Telegram. Напоминания принадлежат не отдельному пользователю, а Telegram-чату: в одном чате участники видят и удаляют напоминания этого чата, а данные разных чатов изолированы по `chat_id`.

## Что умеет бот

Бот поддерживает:

* одноразовые напоминания;
* повтор каждые N дней;
* повтор каждые N дней с указанной даты старта;
* повтор каждые N недель в выбранный день недели;
* повтор каждые N недель в выбранный день недели с указанной даты старта;
* повтор в N-й день недели месяца, например в первый понедельник месяца;
* повтор в N-й день недели месяца с указанной даты старта;
* повтор в конкретный день месяца, например 11 числа каждого месяца;
* повтор в конкретный день месяца с указанной даты старта;
* настройку таймзоны для каждого чата;
* просмотр активных напоминаний текущего чата;
* удаление активных напоминаний текущего чата;
* восстановление активных напоминаний после перезапуска;
* периодический healthcheck в заданный Telegram chat_id.

## Модель данных и доступа

Текущая модель продукта:

* напоминания принадлежат Telegram-чату;
* внутри одного чата любой участник может создавать, смотреть и удалять напоминания этого чата;
* между чатами данные изолированы по `chat_id`;
* `user_id` отправителя не хранится;
* ролевой модели нет;
* таймзона задаётся на чат через `/timezone`;
* таймзона сохраняется в напоминание на момент создания;
* `/list` показывает только напоминания текущего чата;
* `/delete ID` удаляет только напоминание текущего чата.

## Команды

### Базовые команды

```text
/start
```

Показать краткую информацию о боте.

```text
/help
```

Показать справку по командам.

```text
/examples
```

Показать примеры создания напоминаний.

```text
/list
```

Показать активные напоминания текущего чата.

```text
/delete ID
```

Удалить напоминание текущего чата по ID.

Пример:

```text
/delete 12
```

### Таймзона

```text
/timezone
```

Показать текущую таймзону чата.

```text
/timezone Asia/Yekaterinburg
```

Задать таймзону для новых напоминаний в текущем чате.

Таймзона указывается в IANA-формате, например:

```text
Asia/Yekaterinburg
Europe/Moscow
Asia/Almaty
```

Уже созданные напоминания остаются в той таймзоне, которая была установлена на момент их создания.

### Одноразовое напоминание

```text
/remind YYYY-MM-DD HH:MM Текст
```

Пример:

```text
/remind 2026-06-13 12:30 Позвонить в поддержку
```

### Повтор каждые N дней

```text
/every_days N HH:MM Текст
```

Пример:

```text
/every_days 3 09:00 Полить растения
```

Бот создаст повторяющееся напоминание каждые 3 дня. Первое срабатывание будет в ближайшее подходящее будущее время.

### Повтор каждые N дней с указанной даты старта

```text
/every_days_from N YYYY-MM-DD HH:MM Текст
```

Пример:

```text
/every_days_from 10 2026-06-20 09:00 Проверить фильтр
```

Бот создаст повторяющееся напоминание каждые 10 дней, начиная с указанной даты и времени.

### Повтор каждые N недель

```text
/every_week N DAY HH:MM Текст
```

Пример:

```text
/every_week 2 sunday 11:00 Воскресенье через воскресенье
```

Поддерживаются дни недели:

```text
monday
tuesday
wednesday
thursday
friday
saturday
sunday
```

### Повтор каждые N недель с указанной даты старта

```text
/every_week_from N DAY YYYY-MM-DD HH:MM Текст
```

Пример:

```text
/every_week_from 2 sunday 2026-06-21 11:00 Воскресенье через воскресенье
```

Если указанная дата не совпадает с нужным днём недели, бот найдёт первое подходящее срабатывание на указанную дату или позже.

### Повтор в N-й день недели месяца

```text
/monthly_weekday N DAY HH:MM Текст
```

Пример:

```text
/monthly_weekday 1 monday 09:00 Первый понедельник месяца
```

Это создаёт напоминание в первый понедельник каждого месяца.

Пример для второго воскресенья месяца:

```text
/monthly_weekday 2 sunday 11:00 Второе воскресенье месяца
```

### Повтор в N-й день недели месяца с указанной даты старта

```text
/monthly_weekday_from N DAY YYYY-MM-DD HH:MM Текст
```

Пример:

```text
/monthly_weekday_from 1 monday 2026-07-01 09:00 Первый понедельник месяца
```

Если первое подходящее срабатывание после указанной даты попадает уже на следующий месяц, бот покажет это при создании.

### Повтор в конкретный день месяца

```text
/monthly_day DAY HH:MM Текст
```

Пример:

```text
/monthly_day 11 12:12 Оплатить интернет
```

Это создаёт напоминание 11 числа каждого месяца.

Если в месяце нет указанного дня, напоминание в этом месяце не сработает. Например, напоминание на 31 число не сработает в феврале.

### Повтор в конкретный день месяца с указанной даты старта

```text
/monthly_day_from DAY YYYY-MM-DD HH:MM Текст
```

Пример:

```text
/monthly_day_from 11 2026-07-01 12:12 Оплатить интернет
```

Бот найдёт первое подходящее срабатывание на указанную дату или позже.

## Формат уведомлений

При срабатывании напоминания бот отправляет только текст напоминания.

Например, если создано напоминание:

```text
/remind 2026-06-13 12:30 Заказать воду
```

то в момент срабатывания бот отправит:

```text
Заказать воду
```

Без ID, периода, таймзоны и другой служебной информации.

## Формат списка напоминаний

Команда:

```text
/list
```

показывает активные напоминания текущего чата.

В списке сначала отображается текст напоминания, затем служебные детали:

```text
Активные напоминания в этом чате

Заказать воду
ID: 12
Период: каждый месяц 11 числа
Первое срабатывание: 11 июня в 12:12
Следующее срабатывание: 11 июля в 12:12
Таймзона: Asia/Yekaterinburg
```

В Telegram текст напоминания выделяется жирным, а ID и таймзона отображаются в моноширинном формате.

## Технологии

Проект использует:

* Python;
* aiogram;
* APScheduler;
* SQLite;
* Docker;
* Docker Compose;
* ruff;
* pytest;
* GitHub Actions.

В production бот работает через Docker Compose.

Бот использует long polling. Webhook не используется.

## Структура проекта

```text
telegram-reminder-bot/
├── app/
│   ├── config.py
│   ├── constants.py
│   ├── database.py
│   ├── formatting.py
│   ├── handlers.py
│   ├── main.py
│   ├── schedule_calculations.py
│   └── scheduler.py
├── tests/
│   ├── test_database.py
│   ├── test_formatting.py
│   ├── test_schedule_calculations.py
│   └── test_scheduler.py
├── scripts/
│   └── deploy-docker.sh
├── .dockerignore
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── DEPLOY.md
├── README.md
├── requirements.txt
├── pyproject.toml
└── bot.py
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

Для Windows можно создать файл `.env` вручную.

Пример содержимого:

```env
BOT_TOKEN=your_telegram_bot_token
APP_TIMEZONE=Asia/Yekaterinburg
DB_PATH=reminders.db

# Optional: chat_id for periodic healthcheck messages.
# Leave empty to disable healthcheck.
HEALTHCHECK_CHAT_ID=

# Optional: healthcheck interval in minutes.
HEALTHCHECK_INTERVAL_MINUTES=360
```

Пояснения:

* `BOT_TOKEN` — токен Telegram-бота из BotFather.
* `APP_TIMEZONE` — дефолтная таймзона приложения.
* `DB_PATH` — путь к SQLite-базе. По умолчанию используется `reminders.db`.
* `HEALTHCHECK_CHAT_ID` — chat_id, куда бот будет отправлять периодические healthcheck-сообщения.
* `HEALTHCHECK_INTERVAL_MINUTES` — интервал healthcheck-сообщений в минутах.

Если `HEALTHCHECK_CHAT_ID` не задан, healthcheck-сообщения не отправляются.

### 5. Запустить бота

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

Для локального запуска через Docker нужен корректный `.env`.

## Проверки

Форматирование:

```bash
ruff format .
```

Проверка ruff:

```bash
ruff check .
```

Тесты:

```bash
pytest
```

Полная локальная проверка перед коммитом:

```bash
ruff format .
ruff check .
pytest
```

## Production deployment

Эксплуатационная документация находится в [`DEPLOY.md`](DEPLOY.md).

Кратко:

* production работает через Docker Compose;
* SQLite-база хранится на хосте и монтируется в контейнер;
* старый systemd-сервис Python-бота должен быть отключён;
* deploy выполняется скриптом `/opt/deploy-telegram-reminder-bot.sh`;
* перед deploy создаётся backup базы;
* проверки запускаются внутри Docker image;
* после deploy контейнер пересоздаётся через Docker Compose.

Не запускать одновременно Docker-контейнер и старый `telegram-reminder-bot.service`, иначе два процесса будут использовать один `BOT_TOKEN` и конфликтовать в long polling.

## Backup

На production настроены ежедневные backup-копии SQLite-базы через systemd timer.

База хранится на сервере как:

```text
/opt/telegram-reminder-bot/reminders.db
```

Backup-файлы хранятся в:

```text
/opt/telegram-reminder-bot-backups
```

Подробности — в [`DEPLOY.md`](DEPLOY.md).

## Healthcheck

Бот умеет отправлять периодические служебные сообщения о состоянии в заданный Telegram chat_id.

Пример сообщения:

```text
✅ Бот работает.

Время сервера UTC: 2026-06-13T10:58:33+00:00
Scheduler: running
Запланированных jobs: 10
Активных напоминаний в базе: 9
```

Для включения healthcheck нужно задать в `.env`:

```env
HEALTHCHECK_CHAT_ID=123456789
HEALTHCHECK_INTERVAL_MINUTES=360
```

В текущей модели:

```text
Запланированных jobs = активные напоминания + 1 healthcheck job
```

Если `HEALTHCHECK_CHAT_ID` не задан, healthcheck отключён.

## Текущий статус

Проект находится на стадии production MVP.

Уже реализованы:

* создание одноразовых и повторяющихся напоминаний;
* все текущие типы расписаний;
* настройка таймзоны чата;
* изоляция данных по Telegram-чатам;
* сохранение и восстановление активных напоминаний после перезапуска;
* просмотр и удаление активных напоминаний текущего чата;
* отправка напоминаний без служебной metadata — только текст напоминания;
* улучшенное форматирование `/list`;
* periodic healthcheck в заданный Telegram chat_id;
* автотесты для ключевой логики;
* CI-проверки в GitHub Actions;
* Dockerfile и Docker Compose-конфигурация;
* Docker-based deploy-скрипт;
* ежедневные backup-копии SQLite-базы;
* базовая настройка firewall и SSH-доступа;
* документация по эксплуатации и деплою в [`DEPLOY.md`](DEPLOY.md);
* оформление профиля бота через BotFather.

Ближайшие возможные доработки:

* провести пилотное использование в 1–2 чатах;
* собрать обратную связь по понятности команд и форматов;
* улучшить пользовательский ввод команд;
* добавить более дружелюбные сценарии создания напоминаний без сложного синтаксиса;
* добавить внешний backup, например выгрузку копий базы за пределы VPS;
* проработать интерфейс управления напоминаниями через Telegram Mini App.
