# Deploy

Инструкция по развёртыванию и эксплуатации `telegram-reminder-bot` / Telegram Mini App «Незабудка» на VPS.

## Production-контур

Приложение работает на VPS через Docker Compose.

```text
Runtime: Docker Compose
Container: telegram-reminder-bot
Image: telegram-reminder-bot:latest
Database: SQLite, persistent bind mount ./data -> /data
Bot mode: long polling
HTTP API: FastAPI / Uvicorn
Mini App static: /tma
Mini App static runtime: /app/tma inside Docker image
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

Текущий публичный адрес Mini App:

```text
Domain: nezabudka.zhpchshts.ru
Mini App URL: https://nezabudka.zhpchshts.ru/tma/
```

Не хранить в этом файле реальные токены, IP-адреса, chat_id, значения `.env` и приватные SSH-детали.

## Основные пути на сервере

```text
Project dir: /opt/telegram-reminder-bot
.env: /opt/telegram-reminder-bot/.env
SQLite data dir: /opt/telegram-reminder-bot/data
SQLite DB: /opt/telegram-reminder-bot/data/reminders.db
TMA source: /opt/telegram-reminder-bot/tma
TMA runtime: /app/tma inside Docker image
Backups: /opt/telegram-reminder-bot-backups
Deploy script: /opt/deploy-telegram-reminder-bot.sh
Backup script: /opt/backup-telegram-reminder-bot.sh
Backup script source: scripts/backup-database.sh
Compose file: /opt/telegram-reminder-bot/docker-compose.yml
```

## Подключение к серверу

```bash
ssh USER@SERVER
cd /opt/telegram-reminder-bot
```

`USER` и `SERVER` нужно заменить на актуальные значения из личных заметок.

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

Проверить локальные liveness и readiness:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

Ожидаемые ответы:

```json
{"status":"ok"}
{"status":"ready"}
```

`/health` подтверждает, что HTTP-процесс отвечает. `/ready` дополнительно
проверяет запуск bot/scheduler, завершение восстановления напоминаний и наличие
обязательных таблиц SQLite и фоновых scheduler jobs; именно `/ready` используется
healthcheck контейнера.

Проверить, что backend отдаёт Mini App:

```bash
curl -fsSI http://127.0.0.1:8000/tma/
```

Проверить публичный HTTPS-доступ:

```bash
curl -fsS https://nezabudka.zhpchshts.ru/health
curl -fsS https://nezabudka.zhpchshts.ru/ready
curl -fsSI https://nezabudka.zhpchshts.ru/tma/
```

## Deploy Mini App

Frontend-only deploy не поддерживается. Файлы `tma/` копируются в Docker image,
поэтому любое изменение `tma/app.js`, `tma/styles.css` или `tma/index.html`
требует полного deploy.

Это сохраняет одну совместимую версию API и Mini App: `git pull` не меняет
статику работающего контейнера, а новый backend и новые assets становятся
доступны вместе при пересоздании контейнера. В частности, frontend с
`expected_revision` и `Idempotency-Key` не должен преждевременно работать со
старым backend без этих гарантий.

## Полный deploy

Полный deploy нужен, если менялись:

* Python/backend-код;
* зависимости;
* Dockerfile;
* `docker-compose.yml`;
* файлы Mini App в `tma/`;
* runtime-настройки;
* структура базы или миграции.

На VPS выполнить:

```bash
/opt/deploy-telegram-reminder-bot.sh
```

Скрипт сам делает backup базы, обновляет код, собирает Docker image, запускает
`ruff`/`pytest` внутри Docker image и пересоздаёт контейнер. Ожидание `/ready`
ограничено 10 минутами; при обоснованно более долгом восстановлении его можно
увеличить через `REMINDER_BOT_READINESS_TIMEOUT_SECONDS`.

По умолчанию deploy разрешён только из ветки `main`. Если production-процесс
намеренно переведён на другую ветку, её нужно явно указать через
`REMINDER_BOT_DEPLOY_BRANCH`. Ожидаемый remote по умолчанию — `origin`, при
необходимости он задаётся через `REMINDER_BOT_DEPLOY_REMOTE`. Скрипт требует
точное соответствие upstream паре remote/branch, чистое рабочее дерево и делает
явный `git pull --ff-only` только из этой пары.

### Одноразовая миграция старого file-bind

Старый Compose монтировал только `./reminders.db` в `/data/reminders.db`.
SQLite создаёт rollback journal, WAL и SHM рядом с файлом; при таком file-bind
они оставались в writable layer контейнера и могли исчезнуть при recreate.
Новый Compose монтирует каталог `./data` целиком.

Эталонный deploy-скрипт намеренно завершается с ошибкой, если находит старый
`/opt/telegram-reminder-bot/reminders.db`: перенос production-базы нельзя делать
вслепую. Для первого deploy этой версии требуется отдельное согласованное окно и
прямое разрешение на доступ к production. Перед началом проверить фактический
Compose, установленный deploy/backup-скрипт и процесс backup на VPS. Также нужно
подтвердить, что Nginx проксирует `/tma/` в runtime, а не продолжает отдавать
статику из host-каталога; иначе атомарное переключение image не гарантируется.

Безопасная последовательность миграции:

1. Остановить сервис бота, чтобы SQLite завершила текущую транзакцию и закрыла
   rollback journal; не запускать второй экземпляр с тем же токеном.
2. Выполнить backup старой базы и проверить backup через `PRAGMA quick_check`.
3. Выполнить `git pull --ff-only`, проверить diff Compose и установить новые
   эталонные deploy/backup-скрипты. Подтвердить, что установленная копия
   `/opt/backup-telegram-reminder-bot.sh` и systemd timer теперь используют
   `data/reminders.db`, иначе автоматические backup после миграции прекратятся.
4. Создать `/opt/telegram-reminder-bot/data` с закрытыми правами, переместить туда
   `reminders.db` и существующие `reminders.db-wal`, `-shm`, `-journal`, если они
   фактически присутствуют, затем снова выполнить `PRAGMA quick_check`.
5. Запустить полный deploy и пройти локальные, публичные и Telegram-проверки.

Точные команды выполнять только после проверки фактического состояния VPS. Не
удалять исходный backup и не запускать Compose, если одновременно существуют две
разные копии базы: сначала определить каноническую.

Bind mount использует `create_host_path: false`: отсутствие каталога `data` не
должно молча создавать пустое хранилище. Перед миграцией нужно проверить, что
установленная версия Docker Compose поддерживает эту опцию. Для остановки дать
SQLite время завершить работу (`docker compose stop --timeout 120 bot`) и
убедиться, что контейнер действительно остановлен. Если остановка была жёсткой
или `quick_check` не выводит `ok`, старый контейнер не удалять: сначала сохранить
его состояние и согласовать восстановление.

После полного deploy проверить:

```bash
cd /opt/telegram-reminder-bot
docker compose ps
docker logs --tail 80 telegram-reminder-bot
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsSI http://127.0.0.1:8000/tma/
curl -fsS https://nezabudka.zhpchshts.ru/health
curl -fsS https://nezabudka.zhpchshts.ru/ready
curl -fsSI https://nezabudka.zhpchshts.ru/tma/
```

В Telegram проверить:

```text
/app
/list
```

В Mini App проверить, что приложение открывается, список напоминаний загружается, preview строится и сохранение изменений работает.

Уже открытая до deploy Mini App может продолжить выполнять старый JavaScript.
После переключения нужно закрыть её и открыть заново из свежей кнопки `/app`, а
изменённые сценарии проверять только в новом WebView. Новый backend отклоняет
старые edit/delete запросы без `expected_revision`, не ослабляй эту защиту ради
совместимости; повтор create после неизвестного сетевого результата безопасен
только в новой версии frontend, отправляющей `Idempotency-Key`.

Если менялась только документация, deploy не нужен.

Если менялись только тесты, deploy не нужен.

## Ручное управление контейнером

Перезапустить приложение:

```bash
cd /opt/telegram-reminder-bot
docker compose restart
```

После перезапуска проверить:

```bash
docker compose ps
docker logs --tail 80 telegram-reminder-bot
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

## Backup

Эталонный backup-скрипт хранится в `scripts/backup-database.sh`. Установленная
копия на VPS должна совпадать с ним:

```bash
install -o root -g root -m 0755 \
  /opt/telegram-reminder-bot/scripts/backup-database.sh \
  /opt/backup-telegram-reminder-bot.sh
```

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

После миграции data-каталога обязательно проверить фактический `ExecStart`
backup-сервиса через `systemctl cat telegram-reminder-bot-backup.service`,
запустить `/opt/backup-telegram-reminder-bot.sh` вручную и проверить новый файл
через `PRAGMA quick_check` и наличие таблиц `reminders`, `chat_settings`. Одного
статуса timer недостаточно.

Посмотреть логи backup-сервиса:

```bash
journalctl -u telegram-reminder-bot-backup.service -n 50 --no-pager
```

Backup создаётся через online backup API SQLite, проверяется командой
`PRAGMA quick_check` и только после успешной проверки получает итоговое имя.
Отсутствующая база, `sqlite3` или неуспешная проверка завершают скрипт с ошибкой,
поэтому deploy в таком состоянии не продолжается. Backup-файлы старше 14 дней
удаляются только после создания нового проверенного backup.

Локальные backup на том же VPS защищают от ошибки deploy, но не от потери самого
сервера или диска. Для полного disaster recovery нужен отдельно согласованный
off-host backup или snapshot; его фактическое наличие проверяется только на VPS.

### Проверка восстановления

Восстановление всегда выполняется при остановленном контейнере. Оно не входит в
обычный deploy и не запускается автоматически при ошибке readiness. Указать
фактически существующий backup вместо `<точный-файл>`; скрипт ниже работает в
fail-fast subshell, проверяет пути, целостность и обязательные таблицы до замены.
Текущая база и SQLite sidecar-файлы архивируются, а не удаляются:

```bash
export BACKUP_FILE=/opt/telegram-reminder-bot-backups/<точный-файл>.db
bash <<'SCRIPT'
set -euo pipefail

PROJECT_DIR=/opt/telegram-reminder-bot
BACKUP_DIR=/opt/telegram-reminder-bot-backups
CONTAINER_NAME=telegram-reminder-bot
cd "$PROJECT_DIR"

: "${BACKUP_FILE:?Set BACKUP_FILE to an exact verified backup path}"
RESOLVED_BACKUP="$(realpath -e -- "$BACKUP_FILE")"
case "$RESOLVED_BACKUP" in
  "$BACKUP_DIR"/reminders_*.db) ;;
  *) echo "Backup path is outside $BACKUP_DIR" >&2; exit 1 ;;
esac
if [ -L "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ] || [ ! -s "$BACKUP_FILE" ]; then
  echo "Backup must be a non-empty regular file." >&2
  exit 1
fi
test "$(sqlite3 "$BACKUP_FILE" 'PRAGMA quick_check;')" = "ok"
test "$(sqlite3 "$BACKUP_FILE" \
  "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('reminders','chat_settings');")" = "2"

DATA_DIR="$(realpath -e -- "$PROJECT_DIR/data")"
test "$DATA_DIR" = "$PROJECT_DIR/data"
DB_FILE="$DATA_DIR/reminders.db"
RESTORE_FILE="$DATA_DIR/reminders.db.restore"
if [ -L "$DB_FILE" ] || [ ! -f "$DB_FILE" ] || [ ! -s "$DB_FILE" ] \
  || [ -e "$RESTORE_FILE" ]; then
  echo "Current database layout is unsafe for restore." >&2
  exit 1
fi

RESTORE_STAMP="$(date +'%Y-%m-%d_%H-%M-%S')"
docker compose stop --timeout 120 bot
test "$(docker inspect --format '{{.State.Status}}' "$CONTAINER_NAME")" = "exited"
install -m 0600 "$BACKUP_FILE" "$RESTORE_FILE"
test "$(sqlite3 "$RESTORE_FILE" 'PRAGMA quick_check;')" = "ok"
test "$(sqlite3 "$RESTORE_FILE" \
  "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('reminders','chat_settings');")" = "2"

for sidecar in "$DB_FILE-wal" "$DB_FILE-shm" "$DB_FILE-journal"; do
  if [ -e "$sidecar" ]; then
    mv -- "$sidecar" "$sidecar.before-restore_$RESTORE_STAMP"
  fi
done
mv -- "$DB_FILE" "$DB_FILE.before-restore_$RESTORE_STAMP"
mv -- "$RESTORE_FILE" "$DB_FILE"
docker compose up -d --no-build
curl -fsS http://127.0.0.1:8000/ready
SCRIPT
```

После восстановления проверить логи, `/health`, `/ready`, `/tma/` и один
существующий пользовательский сценарий. Архив исходной базы не удалять до
подтверждения результата.

## Rollback образа

Перед сборкой эталонный deploy-скрипт сохраняет предыдущий image как
`telegram-reminder-bot:rollback`. При неуспешной локальной или публичной проверке
скрипт возвращает ошибку и не объявляет deploy успешным. После изучения логов
можно вернуть только предыдущий код и image, не заменяя постоянную базу:

```bash
cd /opt/telegram-reminder-bot
docker image inspect telegram-reminder-bot:rollback
docker image tag telegram-reminder-bot:rollback telegram-reminder-bot:latest
docker compose up -d --force-recreate --no-build
curl -fsS http://127.0.0.1:8000/ready
curl -fsS https://nezabudka.zhpchshts.ru/ready
```

Этот rollback допустим только для обратно совместимых аддитивных миграций. Базу
из backup автоматически не восстанавливать: сначала определить причину сбоя и
согласовать восстановление отдельно.

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
API_ALLOWED_ORIGINS
TMA_BOT_USERNAME
TMA_DIRECT_URL
```

На сервере для Docker Compose `DB_PATH`, `API_HOST` и `API_PORT` переопределяются в `docker-compose.yml`.

Не выводить содержимое `.env` в консоль и не отправлять его в чаты.

## Стартовое healthcheck-сообщение в Telegram

Если `HEALTHCHECK_CHAT_ID` задан, бот отправляет одно healthcheck-сообщение при
каждом запуске процесса. Периодические healthcheck-сообщения не отправляются.

Если `HEALTHCHECK_CHAT_ID` не задан, стартовое сообщение отключено.

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

Не запускать одновременно два экземпляра бота с одним `BOT_TOKEN`.

Production runtime — Docker Compose.
