#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/telegram-reminder-bot"
DATA_DIR="$PROJECT_DIR/data"
DB_FILE="$DATA_DIR/reminders.db"
LEGACY_DB_FILE="$PROJECT_DIR/reminders.db"
IMAGE_NAME="telegram-reminder-bot:latest"
ROLLBACK_IMAGE_NAME="telegram-reminder-bot:rollback"
CONTAINER_NAME="telegram-reminder-bot"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://nezabudka.zhpchshts.ru}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL%/}"
READINESS_TIMEOUT_SECONDS="${REMINDER_BOT_READINESS_TIMEOUT_SECONDS:-600}"
EXPECTED_DEPLOY_BRANCH="${REMINDER_BOT_DEPLOY_BRANCH:-main}"
EXPECTED_DEPLOY_REMOTE="${REMINDER_BOT_DEPLOY_REMOTE:-origin}"
EXPECTED_UPSTREAM="$EXPECTED_DEPLOY_REMOTE/$EXPECTED_DEPLOY_BRANCH"
rollback_available=0

report_failed_deploy() {
    echo "Deployment verification failed; the new version is not ready for production." >&2
    docker compose ps >&2 || true
    docker compose logs --no-color --tail 80 bot >&2 || true
    if [[ "$rollback_available" -eq 1 ]]; then
        echo "Previous image is preserved as $ROLLBACK_IMAGE_NAME." >&2
        echo "Review the logs before following the rollback procedure in DEPLOY.md." >&2
    fi
}

if ! [[ "$READINESS_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "REMINDER_BOT_READINESS_TIMEOUT_SECONDS must be a positive integer." >&2
    exit 1
fi
if [[ ! "$EXPECTED_DEPLOY_REMOTE" =~ ^[A-Za-z0-9._-]+$ \
    || "$EXPECTED_DEPLOY_REMOTE" == -* ]]; then
    echo "REMINDER_BOT_DEPLOY_REMOTE must be a safe Git remote name." >&2
    exit 1
fi
if ! runuser -u reminderbot -- git check-ref-format --branch \
    "$EXPECTED_DEPLOY_BRANCH" >/dev/null; then
    echo "REMINDER_BOT_DEPLOY_BRANCH must be a valid Git branch name." >&2
    exit 1
fi

cd "$PROJECT_DIR"

if ! current_branch="$(
    runuser -u reminderbot -- git symbolic-ref --quiet --short HEAD
)"; then
    echo "Deploy requires a checked-out Git branch." >&2
    exit 1
fi
if [[ "$current_branch" != "$EXPECTED_DEPLOY_BRANCH" ]]; then
    echo "Deploy requires branch $EXPECTED_DEPLOY_BRANCH; found $current_branch." >&2
    exit 1
fi
if ! upstream_branch="$(
    runuser -u reminderbot -- git rev-parse \
        --abbrev-ref --symbolic-full-name '@{upstream}'
)"; then
    echo "Deploy requires a configured upstream branch." >&2
    exit 1
fi
if [[ "$upstream_branch" != "$EXPECTED_UPSTREAM" ]]; then
    echo "Deploy requires upstream $EXPECTED_UPSTREAM; found $upstream_branch." >&2
    exit 1
fi
if ! runuser -u reminderbot -- git diff --quiet \
    || ! runuser -u reminderbot -- git diff --cached --quiet \
    || [[ -n "$(runuser -u reminderbot -- git ls-files --others --exclude-standard)" ]]; then
    echo "Deploy requires a clean Git worktree." >&2
    exit 1
fi

if [[ -e "$LEGACY_DB_FILE" && -e "$DB_FILE" ]]; then
    echo "Both legacy and data-directory databases exist." >&2
    echo "Deploy stopped: determine the canonical database before continuing." >&2
    exit 1
fi

if [[ -e "$LEGACY_DB_FILE" ]]; then
    echo "Legacy single-file database mount detected: $LEGACY_DB_FILE" >&2
    echo "Deploy stopped. Follow the one-time data-directory migration in DEPLOY.md." >&2
    exit 1
fi

if [[ -L "$DB_FILE" || ! -f "$DB_FILE" || ! -s "$DB_FILE" ]]; then
    echo "Database must be a non-empty regular file: $DB_FILE" >&2
    echo "Deploy stopped to avoid starting with an empty database." >&2
    exit 1
fi

echo "Creating database backup..."
REMINDER_BOT_DB_FILE="$DB_FILE" bash "$PROJECT_DIR/scripts/backup-database.sh"

echo "Updating code..."
runuser -u reminderbot -- git pull --ff-only \
    "$EXPECTED_DEPLOY_REMOTE" "$EXPECTED_DEPLOY_BRANCH"

running_image_id="$(
    docker inspect --format '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null || true
)"
if [[ -n "$running_image_id" ]] \
    && curl -fsS --max-time 3 http://127.0.0.1:8000/ready >/dev/null \
    && docker image inspect "$running_image_id" >/dev/null 2>&1; then
    docker image tag "$running_image_id" "$ROLLBACK_IMAGE_NAME"
    rollback_available=1
elif docker image inspect "$ROLLBACK_IMAGE_NAME" >/dev/null 2>&1; then
    rollback_available=1
elif [[ -n "$running_image_id" ]] \
    && docker image inspect "$running_image_id" >/dev/null 2>&1; then
    docker image tag "$running_image_id" "$ROLLBACK_IMAGE_NAME"
    rollback_available=1
fi

echo "Validating Docker Compose configuration..."
docker compose config --quiet

echo "Building Docker image..."
docker compose build

echo "Running checks inside Docker image..."
docker run --rm -e BOT_TOKEN=dummy "$IMAGE_NAME" ruff format --check .
docker run --rm -e BOT_TOKEN=dummy "$IMAGE_NAME" ruff check .
docker run --rm -e BOT_TOKEN=dummy "$IMAGE_NAME" pytest

echo "Restarting Docker Compose service..."
if ! docker compose up -d --force-recreate; then
    report_failed_deploy
    exit 1
fi

echo "Waiting for local readiness..."
ready=0
readiness_deadline=$((SECONDS + READINESS_TIMEOUT_SECONDS))
while (( SECONDS < readiness_deadline )); do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/ready >/dev/null; then
        ready=1
        break
    fi

    sleep 2
done

if [[ "$ready" -ne 1 ]]; then
    report_failed_deploy
    exit 1
fi

echo "Checking local HTTP endpoints..."
if ! curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null \
    || ! curl -fsSI --max-time 3 http://127.0.0.1:8000/tma/ >/dev/null; then
    report_failed_deploy
    exit 1
fi

echo "Checking public HTTPS endpoints..."
if ! curl -fsS --max-time 5 "$PUBLIC_BASE_URL/health" >/dev/null \
    || ! curl -fsS --max-time 5 "$PUBLIC_BASE_URL/ready" >/dev/null \
    || ! curl -fsSI --max-time 5 "$PUBLIC_BASE_URL/tma/" >/dev/null; then
    report_failed_deploy
    exit 1
fi

echo "Docker Compose status:"
docker compose ps

echo "Container logs:"
docker logs --tail 80 "$CONTAINER_NAME"

echo "Deploy completed."
