# Deploy

Инструкция по развёртыванию и эксплуатации Telegram Reminder Bot на VPS.

## Текущий прод-контур

Бот работает на VPS с Ubuntu через Docker Compose.

Основные параметры:

```text
Runtime: Docker Compose
Container: telegram-reminder-bot
Image: telegram-reminder-bot:latest
Database: SQLite
Bot mode: long polling
```

Бот не использует webhook, домен, SSL-сертификат и входящие HTTP-порты. Для работы нужен только исходящий доступ к Telegram Bot API:

```text
api.telegram.org:443
```

## Основные пути на сервере

```text
Проект:        /opt/telegram-reminder-bot
.env:          /opt/telegram-reminder-bot/.env
SQLite DB:     /opt/telegram-reminder-bot/reminders.db
Backups:       /opt/telegram-reminder-bot-backups
Deploy script: /opt/deploy-telegram-reminder-bot.sh
Backup script: /opt/backup-telegram-reminder-bot.sh
Compose file:  /opt/telegram-reminder-bot/docker-compose.yml
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

```powershell
ssh root@SERVER_IP
```

`SERVER_IP` нужно заменить на IP сервера.

Вход по паролю отключён. Подключение выполняется по SSH-ключу.

## Проверить статус бота

```bash
cd /opt/telegram-reminder-bot
docker compose ps
```

Ожидаемое состояние:

```text
telegram-reminder-bot   telegram-reminder-bot:latest   "python bot.py"   bot   ...   Up
```

Проверить контейнер напрямую:

```bash
docker ps
```

## Посмотреть логи бота

Последние 100 строк:

```bash
docker logs --tail 100 telegram-reminder-bot
```

Логи в режиме live:

```bash
docker logs -f telegram-reminder-bot
```

После старта в логах должно быть сообщение вида:

```text
Restored reminders: 9. Missed reminders: 0.
```

Число восстановленных напоминаний зависит от текущего состояния базы.

## Перезапустить бота

```bash
cd /opt/telegram-reminder-bot
docker compose restart
```

После перезапуска проверить:

```bash
docker compose ps
docker logs --tail 80 telegram-reminder-bot
```

## Остановить бота

```bash
cd /opt/telegram-reminder-bot
docker compose stop
```

## Запустить бота

```bash
cd /opt/telegram-reminder-bot
docker compose up -d
```

## Деплой новой версии

Обычный деплой выполняется скриптом:

```bash
/opt/deploy-telegram-reminder-bot.sh
```

Скрипт делает:

1. Создаёт backup базы.
2. Останавливает и отключает старый systemd-сервис Python-бота.
3. Выполняет `git pull --ff-only`.
4. Собирает Docker image через `docker compose build`.
5. Запускает проверки внутри Docker image:

   * `ruff format --check .`
   * `ruff check .`
   * `pytest`
6. Пересоздаёт контейнер через `docker compose up -d --force-recreate`.
7. Показывает статус Docker Compose.
8. Показывает последние логи контейнера.

После деплоя проверить:

```bash
cd /opt/telegram-reminder-bot
docker compose ps
docker logs --tail 80 telegram-reminder-bot
```

И проверить бота в Telegram:

```text
/list
```

## Старый systemd-сервис

Старый Python-сервис должен быть отключён и остановлен:

```bash
systemctl is-enabled telegram-reminder-bot.service || true
systemctl is-active telegram-reminder-bot.service || true
```

Ожидаемо:

```text
disabled
inactive
```

Не запускать старый `telegram-reminder-bot.service` одновременно с Docker-контейнером. Оба процесса будут использовать один и тот же `BOT_TOKEN`, из-за чего long polling может конфликтовать.

## Healthcheck

Бот отправляет периодические healthcheck-сообщения в `chat_id`, указанный в `.env`:

```env
HEALTHCHECK_CHAT_ID=...
HEALTHCHECK_INTERVAL_MINUTES=360
```

Если `HEALTHCHECK_CHAT_ID` не задан, healthcheck-сообщения отключены.

Ожидаемое сообщение:

```text
✅ Бот работает.

Время сервера UTC: ...
Scheduler: running
Запланированных jobs: ...
Активных напоминаний в базе: ...
```

Для текущей модели:

```text
Запланированных jobs = активные напоминания + 1 healthcheck job
```

## Ручной backup базы

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

## Автоматический backup

Backup запускается ежедневно через systemd timer.

Проверить статус таймера:

```bash
systemctl status telegram-reminder-bot-backup.timer
```

Посмотреть ближайшие запуски:

```bash
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

Пример содержимого:

```env
BOT_TOKEN=real_telegram_bot_token
APP_TIMEZONE=Asia/Yekaterinburg
DB_PATH=reminders.db
HEALTHCHECK_CHAT_ID=
HEALTHCHECK_INTERVAL_MINUTES=360
```

На сервере для Docker Compose `DB_PATH` переопределяется в `docker-compose.yml`:

```yaml
environment:
  DB_PATH: /data/reminders.db
```

Права на `.env`:

```bash
ls -la /opt/telegram-reminder-bot/.env
```

Ожидаемо:

```text
-rw------- 1 reminderbot reminderbot ... .env
```

Не выводить содержимое `.env` в консоль и не отправлять его в чаты.

## Проверки проекта в Docker

```bash
cd /opt/telegram-reminder-bot

docker run --rm -e BOT_TOKEN=dummy telegram-reminder-bot:latest ruff format --check .
docker run --rm -e BOT_TOKEN=dummy telegram-reminder-bot:latest ruff check .
docker run --rm -e BOT_TOKEN=dummy telegram-reminder-bot:latest pytest
```

## Проверить доступ до Telegram API

```bash
python3 - << 'PY'
import socket

socket.create_connection(("api.telegram.org", 443), timeout=10)
print("ok")
PY
```

Ожидаемый результат:

```text
ok
```

Если команда не возвращает `ok`, бот не сможет работать через long polling.

## Проверить свободное место

```bash
df -h
```

Размер проекта:

```bash
du -sh /opt/telegram-reminder-bot
```

Размер backup-папки:

```bash
du -sh /opt/telegram-reminder-bot-backups
```

Docker-образы и контейнеры:

```bash
docker images
docker ps -a
```

## Проверить firewall

```bash
ufw status verbose
```

Ожидаемое состояние:

```text
Status: active
Default: deny (incoming), allow (outgoing)
22/tcp (OpenSSH) ALLOW IN Anywhere
22/tcp (OpenSSH (v6)) ALLOW IN Anywhere (v6)
```

Боту не нужны входящие соединения, поэтому снаружи должен быть открыт только SSH.

## Проверить SSH-настройки

```bash
sshd -T | grep -E 'passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication'
```

Ожидаемо:

```text
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication no
permitrootlogin without-password
```

`permitrootlogin without-password` означает, что root-вход по паролю запрещён, но вход по SSH-ключу разрешён.

## Важное правило

Не запускать одновременно два экземпляра бота.

Нельзя одновременно запускать:

```bash
docker compose up -d
```

и:

```bash
systemctl start telegram-reminder-bot.service
```

Иначе Telegram long polling может конфликтовать между двумя процессами.
