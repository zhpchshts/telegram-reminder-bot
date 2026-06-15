# Deploy

Инструкция по развёртыванию и эксплуатации `telegram-reminder-bot` / Telegram Mini App «Незабудка» на VPS.

## Текущий production-контур

Приложение работает на VPS с Ubuntu через Docker Compose.

Основные параметры:

```text id="9uez6x"
Runtime: Docker Compose
Container: telegram-reminder-bot
Image: telegram-reminder-bot:latest
Database: SQLite
Bot mode: long polling
HTTP API: FastAPI / Uvicorn
Mini App static: /tma
Local API port: 127.0.0.1:8000
```

В одном контейнере запускаются:

* Telegram bot runtime;
* APScheduler для активных напоминаний;
* FastAPI HTTP API;
* отдача статических файлов Telegram Mini App.

Webhook не используется. Бот работает через long polling.

Для long polling нужен исходящий доступ к Telegram Bot API:

```text id="8dqj6p"
api.telegram.org:443
```

Для Telegram Mini App нужен публичный HTTPS-домен, который проксирует запросы к локальному FastAPI runtime на VPS:

```text id="lzylar"
127.0.0.1:8000
```

## Основные пути на сервере

```text id="4wrmbg"
Проект:       /opt/telegram-reminder-bot
.env:         /opt/telegram-reminder-bot/.env
SQLite DB:    /opt/telegram-reminder-bot/reminders.db
TMA static:   /opt/telegram-reminder-bot/tma
Backups:      /opt/telegram-reminder-bot-backups

Deploy script: /opt/deploy-telegram-reminder-bot.sh
Backup script: /opt/backup-telegram-reminder-bot.sh
Compose file:  /opt/telegram-reminder-bot/docker-compose.yml
```

SQLite-база хранится на хосте:

```text id="cftey4"
/opt/telegram-reminder-bot/reminders.db
```

В контейнер она монтируется как:

```text id="dixjb0"
/data/reminders.db
```

## Подключение к серверу

```powershell id="42kpqm"
ssh root@SERVER_IP
```

`SERVER_IP` нужно заменить на IP сервера.

Вход по паролю отключён. Подключение выполняется по SSH-ключу.

## Проверить статус контейнера

```bash id="wkz44n"
cd /opt/telegram-reminder-bot
docker compose ps
```

Ожидаемое состояние:

```text id="qqhm53"
telegram-reminder-bot   telegram-reminder-bot:latest   ...   Up
```

Проверить контейнер напрямую:

```bash id="w1vq1c"
docker ps
```

## Посмотреть логи приложения

Последние 100 строк:

```bash id="s4x7yz"
docker logs --tail 100 telegram-reminder-bot
```

Логи в режиме live:

```bash id="67b4ss"
docker logs -f telegram-reminder-bot
```

После старта в логах должно быть сообщение вида:

```text id="zpak7a"
Restored reminders: 9. Missed reminders: 0.
```

Число восстановленных и пропущенных напоминаний зависит от текущего состояния базы.

## Проверить HTTP API локально на сервере

Проверить healthcheck:

```bash id="6ra47v"
curl -s http://127.0.0.1:8000/health
```

Ожидаемый ответ содержит:

```json id="1zc6o4"
{
  "status": "ok",
  "active_chats_count": 1
}
```

Значение `active_chats_count` зависит от текущей базы.

Проверить, что backend отдаёт Mini App static:

```bash id="18b5k5"
curl -I http://127.0.0.1:8000/tma/
```

Ожидаемо:

```text id="8iu1lg"
HTTP/1.1 200 OK
```

или другой успешный `2xx`-ответ.

## Проверить публичный HTTPS-доступ

Публичный HTTPS-домен должен проксировать запросы к локальному backend runtime.

Проверить healthcheck снаружи:

```bash id="7udx87"
curl -s https://PUBLIC_DOMAIN/health
```

Ожидаемый ответ содержит:

```json id="bdstte"
{
  "status": "ok",
  "active_chats_count": 1
}
```

Проверить Mini App:

```bash id="xgsv2n"
curl -I https://PUBLIC_DOMAIN/tma/
```

Ожидаемо:

```text id="yws58j"
HTTP/2 200
```

или другой успешный `2xx`-ответ.

`PUBLIC_DOMAIN` нужно заменить на актуальный production-домен.

## Перезапустить приложение

```bash id="jzvx0i"
cd /opt/telegram-reminder-bot
docker compose restart
```

После перезапуска проверить:

```bash id="nw61ht"
docker compose ps
docker logs --tail 80 telegram-reminder-bot
curl -s http://127.0.0.1:8000/health
```

## Остановить приложение

```bash id="uivfe9"
cd /opt/telegram-reminder-bot
docker compose stop
```

## Запустить приложение

```bash id="aii7r2"
cd /opt/telegram-reminder-bot
docker compose up -d
```

После запуска проверить:

```bash id="d3omr6"
docker compose ps
docker logs --tail 80 telegram-reminder-bot
curl -s http://127.0.0.1:8000/health
```

## Деплой новой версии

Обычный деплой выполняется скриптом:

```bash id="n6sc3n"
/opt/deploy-telegram-reminder-bot.sh
```

Скрипт делает:

1. Создаёт backup базы.
2. Останавливает и отключает старый systemd-сервис Python-бота.
3. Выполняет `git pull --ff-only`.
4. Собирает Docker image через `docker compose build`.
5. Запускает проверки внутри Docker image:

   * `ruff format --check .`;
   * `ruff check .`;
   * `pytest`.
6. Пересоздаёт контейнер через `docker compose up -d --force-recreate`.
7. Показывает статус Docker Compose.
8. Показывает последние логи контейнера.

Frontend syntax check выполняется в GitHub Actions:

```bash id="27bjbd"
node --check tma/app.js
```

Локально на VPS Node для этого ставить не нужно.

## Проверить после деплоя

Проверить контейнер и логи:

```bash id="rryr06"
cd /opt/telegram-reminder-bot
docker compose ps
docker logs --tail 80 telegram-reminder-bot
```

Проверить локальный HTTP API:

```bash id="vq17d3"
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8000/tma/
```

Проверить публичный HTTPS-доступ:

```bash id="79pbfq"
curl -s https://PUBLIC_DOMAIN/health
curl -I https://PUBLIC_DOMAIN/tma/
```

Проверить в Telegram:

```text id="nfu0pv"
/list
/app
```

В Mini App проверить:

1. приложение открывается из кнопки «Открыть Незабудку»;
2. список напоминаний загружается;
3. preview напоминания строится;
4. создание тестового напоминания работает;
5. созданное напоминание отображается в списке;
6. удаление тестового напоминания работает.

Если менялась только документация, деплой не нужен.

Если менялись только тесты, деплой не нужен.

Если менялся только frontend и он уже попал в production-контейнер после деплоя, достаточно проверить Mini App.

Если менялся backend/Python-код, нужно проверить и Telegram-команды, и HTTP API, и Mini App.

## Старый systemd-сервис

Старый Python-сервис должен быть отключён и остановлен:

```bash id="sp0mvs"
systemctl is-enabled telegram-reminder-bot.service || true
systemctl is-active telegram-reminder-bot.service || true
```

Ожидаемо:

```text id="v0s7b7"
disabled
inactive
```

Не запускать старый `telegram-reminder-bot.service` одновременно с Docker-контейнером.

Оба процесса будут использовать один и тот же `BOT_TOKEN`, из-за чего long polling может конфликтовать.

## Healthcheck-сообщения в Telegram

Бот отправляет периодические healthcheck-сообщения в `chat_id`, указанный в `.env`:

```env id="0vpkjy"
HEALTHCHECK_CHAT_ID=
HEALTHCHECK_INTERVAL_MINUTES=360
```

Если `HEALTHCHECK_CHAT_ID` не задан, healthcheck-сообщения отключены.

Ожидаемое сообщение:

```text id="i0kde7"
✅ Бот работает.

Время сервера UTC: ...
Scheduler: running
Запланированных jobs: ...
Активных напоминаний в базе: ...
Чатов с активными напоминаниями: ...
```

Для текущей модели:

```text id="4s1f0m"
Запланированных jobs = активные напоминания + 1 healthcheck job
```

если healthcheck job включён.

## Ручной backup базы

```bash id="bw2kfe"
/opt/backup-telegram-reminder-bot.sh
```

Проверить backup-файлы:

```bash id="hkgix4"
ls -la /opt/telegram-reminder-bot-backups
```

Проверить размер папки с backup-файлами:

```bash id="vc5m1h"
du -sh /opt/telegram-reminder-bot-backups
```

## Автоматический backup

Backup запускается ежедневно через systemd timer.

Проверить статус таймера:

```bash id="2fg34t"
systemctl status telegram-reminder-bot-backup.timer
```

Посмотреть ближайшие запуски:

```bash id="n4i0zm"
systemctl list-timers telegram-reminder-bot-backup.timer
```

Посмотреть логи backup-сервиса:

```bash id="axlf3t"
journalctl -u telegram-reminder-bot-backup.service -n 50 --no-pager
```

Backup-файлы старше 14 дней удаляются автоматически.

## `.env`

Файл находится здесь:

```text id="ot6r8a"
/opt/telegram-reminder-bot/.env
```

Пример содержимого:

```env id="71jztp"
BOT_TOKEN=real_telegram_bot_token
APP_TIMEZONE=Asia/Yekaterinburg
DB_PATH=reminders.db
HEALTHCHECK_CHAT_ID=
HEALTHCHECK_INTERVAL_MINUTES=360
API_ALLOWED_ORIGINS=
TMA_URL=
```

Переменные:

| Переменная                     | Назначение                                        |
| ------------------------------ | ------------------------------------------------- |
| `BOT_TOKEN`                    | Токен Telegram-бота                               |
| `APP_TIMEZONE`                 | Дефолтная таймзона приложения                     |
| `DB_PATH`                      | Путь к SQLite-базе                                |
| `HEALTHCHECK_CHAT_ID`          | Chat ID для periodic healthcheck-сообщений        |
| `HEALTHCHECK_INTERVAL_MINUTES` | Интервал periodic healthcheck-сообщений в минутах |
| `API_ALLOWED_ORIGINS`          | Origin'ы для CORS через запятую                   |
| `TMA_URL`                      | Публичный HTTPS URL Mini App                      |

На сервере для Docker Compose `DB_PATH`, `API_HOST` и `API_PORT` переопределяются в `docker-compose.yml`:

```yaml id="dax5j5"
environment:
  DB_PATH: /data/reminders.db
  API_HOST: 0.0.0.0
  API_PORT: 8000
ports:
  - "127.0.0.1:8000:8000"
```

Права на `.env`:

```bash id="ywq2ft"
ls -la /opt/telegram-reminder-bot/.env
```

Ожидаемо:

```text id="b062ol"
-rw------- 1 reminderbot reminderbot ... .env
```

Не выводить содержимое `.env` в консоль и не отправлять его в чаты.

## Проверки проекта в Docker

```bash id="wd3t98"
cd /opt/telegram-reminder-bot

docker run --rm -e BOT_TOKEN=dummy telegram-reminder-bot:latest ruff format --check .
docker run --rm -e BOT_TOKEN=dummy telegram-reminder-bot:latest ruff check .
docker run --rm -e BOT_TOKEN=dummy telegram-reminder-bot:latest pytest
```

Перед commit локально также проверить пробелы и окончания строк:

```bash id="c4jyg2"
git diff --check
```

## Проверить доступ до Telegram API

```bash id="z0ltcj"
python3 - << 'PY'
import socket

socket.create_connection(("api.telegram.org", 443), timeout=10)
print("ok")
PY
```

Ожидаемый результат:

```text id="yewqkc"
ok
```

Если команда не возвращает `ok`, бот не сможет работать через long polling.

## Проверить свободное место

```bash id="rf1s7d"
df -h
```

Размер проекта:

```bash id="hy37r0"
du -sh /opt/telegram-reminder-bot
```

Размер backup-папки:

```bash id="hhb2zl"
du -sh /opt/telegram-reminder-bot-backups
```

Docker-образы и контейнеры:

```bash id="rkmurc"
docker images
docker ps -a
```

## Проверить firewall

```bash id="jr66za"
ufw status verbose
```

Ожидаемое состояние зависит от reverse proxy.

Минимально должны быть разрешены:

* SSH;
* HTTPS для Telegram Mini App;
* при необходимости HTTP для redirect на HTTPS.

Порт `8000` не должен быть открыт наружу. Он должен быть доступен только локально на VPS:

```text id="6b2nac"
127.0.0.1:8000
```

## Проверить SSH-настройки

```bash id="7gwynj"
sshd -T | grep -E 'passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication'
```

Ожидаемо:

```text id="sdh1zk"
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication no
permitrootlogin without-password
```

`permitrootlogin without-password` означает, что root-вход по паролю запрещён, но вход по SSH-ключу разрешён.

## Важное правило

Не запускать одновременно два экземпляра бота.

Нельзя одновременно запускать:

```bash id="69n7ze"
docker compose up -d
```

и:

```bash id="9hsdx0"
systemctl start telegram-reminder-bot.service
```

Иначе Telegram long polling может конфликтовать между двумя процессами.
