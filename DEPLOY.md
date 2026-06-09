# Deploy

Инструкция по развёртыванию и эксплуатации Telegram Reminder Bot на VPS.

## Текущий прод-контур

Бот развёрнут на VPS с Ubuntu и работает как `systemd`-сервис.

Основные параметры:

```text
OS: Ubuntu
Runtime: Python 3
Process manager: systemd
Database: SQLite
Bot mode: long polling
```

Бот не использует webhook, домен и SSL-сертификат. Для работы ему нужен исходящий доступ к Telegram Bot API:

```text
api.telegram.org:443
```

## Основные пути на сервере

```text
Проект:       /opt/telegram-reminder-bot
.env:         /opt/telegram-reminder-bot/.env
SQLite DB:    /opt/telegram-reminder-bot/reminders.db
Backups:      /opt/telegram-reminder-bot-backups
Deploy script:/opt/deploy-telegram-reminder-bot.sh
Backup script:/opt/backup-telegram-reminder-bot.sh
```

## Сервисы systemd

Основной сервис бота:

```text
telegram-reminder-bot.service
```

Сервис бэкапа:

```text
telegram-reminder-bot-backup.service
```

Таймер ежедневного бэкапа:

```text
telegram-reminder-bot-backup.timer
```

## Подключение к серверу

```powershell
ssh root@SERVER_IP
```

`SERVER_IP` нужно заменить на IP сервера.

Вход по паролю отключён. Подключение должно выполняться по SSH-ключу.

## Проверить статус бота

```bash
systemctl status telegram-reminder-bot
```

Ожидаемое состояние:

```text
Active: active (running)
```

## Посмотреть логи бота

Последние 100 строк:

```bash
journalctl -u telegram-reminder-bot -n 100 --no-pager
```

Логи в режиме live:

```bash
journalctl -u telegram-reminder-bot -f
```

## Перезапустить бота

```bash
systemctl restart telegram-reminder-bot
```

Проверить после перезапуска:

```bash
systemctl status telegram-reminder-bot
```

## Остановить бота

```bash
systemctl stop telegram-reminder-bot
```

## Запустить бота

```bash
systemctl start telegram-reminder-bot
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

## Ручной деплой новой версии

Обычный деплой выполняется скриптом:

```bash
/opt/deploy-telegram-reminder-bot.sh
```

Скрипт делает:

1. Создаёт backup базы.
2. Останавливает сервис бота.
3. Выполняет `git pull`.
4. Обновляет зависимости.
5. Запускает проверки:

   * `ruff format --check .`
   * `ruff check .`
   * `pytest`
6. Запускает сервис бота.
7. Показывает статус сервиса.

После деплоя нужно проверить бота в Telegram:

```text
/list
```

## Ручной backup базы

```bash
/opt/backup-telegram-reminder-bot.sh
```

Проверить созданные backup-файлы:

```bash
ls -la /opt/telegram-reminder-bot-backups
```

Размер папки с backup-файлами:

```bash
du -sh /opt/telegram-reminder-bot-backups
```

## Автоматический backup

Backup запускается ежедневно через `systemd timer`.

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

## Проверить свободное место на диске

```bash
df -h
```

Проверить размер проекта:

```bash
du -sh /opt/telegram-reminder-bot
```

Проверить размер backup-папки:

```bash
du -sh /opt/telegram-reminder-bot-backups
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

## Где лежит `.env`

```text
/opt/telegram-reminder-bot/.env
```

Файл должен содержать:

```env
BOT_TOKEN=real_telegram_bot_token
APP_TIMEZONE=Asia/Yekaterinburg
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

## Проверки проекта на сервере

```bash
runuser -u reminderbot -- bash -lc 'cd /opt/telegram-reminder-bot && . .venv/bin/activate && ruff format --check . && ruff check . && pytest'
```

## Ручной запуск без systemd

Использовать только для диагностики, когда сервис остановлен.

Остановить сервис:

```bash
systemctl stop telegram-reminder-bot
```

Запустить вручную:

```bash
runuser -u reminderbot -- bash -lc 'cd /opt/telegram-reminder-bot && . .venv/bin/activate && python bot.py'
```

Остановить ручной запуск:

```text
Ctrl + C
```

После диагностики снова запустить сервис:

```bash
systemctl start telegram-reminder-bot
```

## Важное правило

Не запускать одновременно два экземпляра бота.

Если бот уже работает как `systemd`-сервис, не нужно параллельно запускать:

```bash
python bot.py
```

Иначе Telegram long polling может конфликтовать между двумя процессами.
