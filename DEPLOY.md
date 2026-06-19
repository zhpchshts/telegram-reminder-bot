# Deploy

Инструкция по развёртыванию и эксплуатации `telegram-reminder-bot` / Telegram Mini App «Незабудка» на VPS.

## Production-контур

Приложение работает на VPS через Docker Compose.

```text
Runtime: Docker Compose
Container: telegram-reminder-bot
Image: telegram-reminder-bot:latest
Database: SQLite
Bot mode: long polling
HTTP API: FastAPI / Uvicorn
Mini App static: /tma
Local API port: 127.0.0.1:8000
```

Webhook не используется. Бот работает через long polling, поэтому серверу нужен исходящий доступ к Telegram Bot API:

```text
api.telegram.org:443
```

Публичный HTTPS-домен проксирует запросы к backend runtime на VPS:

```text
127.0.0.1:8000
```

Не хранить в этом файле реальные токены, IP-адреса, chat_id, значения `.env` и приватные SSH-детали.

## Основные пути на сервере

```text
Project dir: /opt/telegram-reminder-bot
.env: /opt/telegram-reminder-bot/.env
SQLite DB: /opt/telegram-reminder-bot/reminders.db
TMA static: /opt/telegram-reminder-bot/tma
Backups: /opt/telegram-reminder-bot-backups
Deploy script: /opt/deploy-telegram-reminder-bot.sh
Backup script: /opt/backup-telegram-reminder-bot.sh
Compose file: /opt/telegram-reminder-bot/docker-compose.yml
```

SQLite-база хранится на хосте:

```text
/opt/telegram-reminder-bot/reminders.db
```

В контейнер она монтируется как:

```text
/data/reminders.db
```

## Подключение к серверу

```bash
ssh <user>@<server>
cd /opt/telegram-reminder-bot
```

## Быстрая диагностика

Проверить контейнер:

```bash
cd /opt/telegram-reminder-bot
docker compose ps
```

Посмотреть последние логи:

```bash
docker logs --tail 100 telegram-reminder-bot
```

Посмотреть логи в режиме live:

```bash
docker logs -f telegram-reminder-bot
```

Проверить локальный healthcheck:

```bash
curl -s http://127.0.0.1:8000/health
```

Ожидаемый ответ содержит:

```json
{
  "status": "ok",
  "active_chats_count": 0,
  "tzdata_package_version": "...",
  "tzdata_iana_version": "..."
}
```

`active_chats_count` и версии `tzdata` зависят от текущего состояния приложения.

Проверить, что backend отдаёт Mini App:

```bash
curl -I http://127.0.0.1:8000/tma/
```

Ожидаемо: успешный `2xx`-ответ.

Проверить публичный HTTPS-доступ:

```bash
curl -s https://<public-domain>/health
curl -I https://<public-domain>/tma/
```

`<public-domain>` нужно заменить на актуальный production-домен.

## Frontend-only deploy

Frontend-only deploy подходит, если менялись только файлы Mini App:

```text
tma/app.js
tma/styles.css
tma/index.html
```

Так как `tma/` смонтирована в контейнер как host-директория, пересборка backend image не нужна.

На VPS выполнить:

```bash
cd /opt/telegram-reminder-bot
git pull --ff-only
```

После этого проверить:

```bash
curl -I http://127.0.0.1:8000/tma/
curl -I https://<public-domain>/tma/
```

Контейнер перезапускать не нужно.

Для frontend-only deploy не выполнять:

```bash
docker compose build
docker compose up -d --force-recreate
```

## Полный deploy

Полный deploy нужен, если менялись:

* Python/backend-код;
* зависимости;
* Dockerfile;
* `docker-compose.yml`;
* runtime-настройки;
* структура базы или миграции.

На VPS выполнить:

```bash
/opt/deploy-telegram-reminder-bot.sh
```

Скрипт сам делает backup базы, обновляет код, собирает Docker image, запускает `ruff`/`pytest` внутри Docker image и пересоздаёт контейнер.

После полного deploy проверить:

```bash
cd /opt/telegram-reminder-bot
docker compose ps
docker logs --tail 80 telegram-reminder-bot
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8000/tma/
curl -s https://<public-domain>/health
curl -I https://<public-domain>/tma/
```

В Telegram проверить:

```text
/app
/list
```

В Mini App проверить, что:

1. приложение открывается;
2. список напоминаний загружается;
3. форма создания/редактирования работает;
4. preview строится;
5. сохранение изменений работает.

Если менялась только документация, deploy не нужен.

Если менялись только тесты, deploy не нужен.

## Ручное управление контейнером

Перезапустить приложение:

```bash
cd /opt/telegram-reminder-bot
docker compose restart
```

Остановить приложение:

```bash
cd /opt/telegram-reminder-bot
docker compose stop
```

Запустить приложение:

```bash
cd /opt/telegram-reminder-bot
docker compose up -d
```

После ручного запуска или перезапуска проверить:

```bash
docker compose ps
docker logs --tail 80 telegram-reminder-bot
curl -s http://127.0.0.1:8000/health
```

## Backup

Сделать backup базы вручную:

```bash
/opt/backup-telegram-reminder-bot.sh
```

Проверить backup-файлы:

```bash
ls -la /opt/telegram-reminder-bot-backups
```

Проверить размер папки с backup-файлами:

```bash
du -sh /opt/telegram-reminder-bot-backups
```

Автоматический backup запускается через systemd timer.

Проверить timer:

```bash
systemctl status telegram-reminder-bot-backup.timer
systemctl list-timers telegram-reminder-bot-backup.timer
```

Посмотреть логи backup-сервиса:

```bash
journalctl -u telegram-reminder-bot-backup.service -n 50 --no-pager
```

Backup-файлы старше 14 дней удаляются автоматически.

## `.env`

Файл находится здесь:

```text
/opt/telegram-reminder-bot/.env
```

Важные переменные:

```text
BOT_TOKEN
APP_TIMEZONE
DB_PATH
HEALTHCHECK_CHAT_ID
HEALTHCHECK_INTERVAL_MINUTES
API_ALLOWED_ORIGINS
TMA_URL
TMA_BOT_USERNAME
TMA_DIRECT_URL
```

На сервере для Docker Compose `DB_PATH`, `API_HOST` и `API_PORT` переопределяются в `docker-compose.yml`.

Не выводить содержимое `.env` в консоль и не отправлять его в чаты.

Проверить права на `.env`:

```bash
ls -la /opt/telegram-reminder-bot/.env
```

## Healthcheck-сообщения в Telegram

Бот может отправлять периодические healthcheck-сообщения в чат, указанный через `.env`:

```text
HEALTHCHECK_CHAT_ID
HEALTHCHECK_INTERVAL_MINUTES
```

Если `HEALTHCHECK_CHAT_ID` не задан, healthcheck-сообщения отключены.

Ожидаемое сообщение содержит:

```text
✅ Бот работает.
Время сервера UTC: ...
Scheduler: running
Запланированных jobs: ...
Активных напоминаний в базе: ...
Чатов с активными напоминаниями: ...
```

Для текущей модели:

```text
Запланированных jobs = активные напоминания + 1 healthcheck job
```

если healthcheck job включён.

## Troubleshooting

Проверить доступ до Telegram API:

```bash
python3 - << 'PY'
import socket

socket.create_connection(("api.telegram.org", 443), timeout=10)
print("ok")
PY
```

Если команда не возвращает `ok`, бот не сможет работать через long polling.

Проверить свободное место:

```bash
df -h
du -sh /opt/telegram-reminder-bot
du -sh /opt/telegram-reminder-bot-backups
```

Проверить Docker-образы и контейнеры:

```bash
docker images
docker ps -a
```

Проверить firewall:

```bash
ufw status verbose
```

Порт `8000` не должен быть открыт наружу. Он должен быть доступен только локально на VPS:

```text
127.0.0.1:8000
```

## Важное правило

Не запускать одновременно два экземпляра бота.

Нельзя одновременно запускать Docker Compose runtime:

```bash
docker compose up -d
```

и старый systemd-сервис:

```bash
systemctl start telegram-reminder-bot.service
```

Оба процесса будут использовать один и тот же `BOT_TOKEN`, из-за чего Telegram long polling может конфликтовать.

Production runtime — Docker Compose.
