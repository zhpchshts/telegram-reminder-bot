from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_tma_is_served_from_the_same_image_as_backend() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    backend_workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "backend.yml"
    ).read_text(encoding="utf-8")

    assert "/app/tma" not in compose
    assert "source: ./data" in compose
    assert "target: /data" in compose
    assert "create_host_path: false" in compose
    assert "driver: json-file" in compose
    assert 'max-size: "10m"' in compose
    assert 'max-file: "5"' in compose
    assert "./reminders.db:/data/reminders.db" not in compose
    assert dockerfile.startswith("FROM python:3.14.7-slim-trixie\n")
    assert "COPY . ." not in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY tma ./tma" in dockerfile
    assert "COPY tests ./tests" in dockerfile
    assert 'python-version: "3.14.7"' in backend_workflow


def test_docker_build_context_uses_an_explicit_allowlist() -> None:
    dockerignore_path = PROJECT_ROOT / ".dockerignore"
    if not dockerignore_path.is_file():
        pytest.skip(
            "The runtime image intentionally excludes source-only .dockerignore."
        )
    dockerignore = dockerignore_path.read_text(encoding="utf-8")

    ignored_paths = {
        line.strip().rstrip("/")
        for line in dockerignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "tma" not in ignored_paths
    assert "data" in ignored_paths
    assert "**" in ignored_paths
    assert {
        "!app/**",
        "!tma/**",
        "!tests/**",
        "!scripts/**",
    } <= ignored_paths

    ordered_rules = [
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    last_allow_rule = max(
        ordered_rules.index(rule)
        for rule in ("!app/**", "!tma/**", "!tests/**", "!scripts/**")
    )
    for sensitive_rule in (
        ".env.*",
        "**/.env.*",
        "*.db",
        "**/*.db",
        "*-wal",
        "**/*-wal",
    ):
        assert ordered_rules.index(sensitive_rule) > last_allow_rule


def test_docker_build_context_excludes_sqlite_sidecars() -> None:
    dockerignore_path = PROJECT_ROOT / ".dockerignore"
    if not dockerignore_path.is_file():
        pytest.skip(
            "The runtime image intentionally excludes source-only .dockerignore."
        )
    dockerignore = dockerignore_path.read_text(encoding="utf-8")
    ignored_paths = {
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        "*.db-*",
        "*.sqlite-*",
        "*.sqlite3-*",
        "*-journal",
        "*-wal",
        "*-shm",
    } <= ignored_paths


def test_deploy_is_fail_closed_and_checks_public_endpoints() -> None:
    backup_script = (PROJECT_ROOT / "scripts" / "backup-database.sh").read_text(
        encoding="utf-8"
    )
    deploy_script = (PROJECT_ROOT / "scripts" / "deploy-docker.sh").read_text(
        encoding="utf-8"
    )

    missing_database_block = backup_script.split(
        'if [ ! -f "$DB_FILE" ] || [ ! -s "$DB_FILE" ]; then', 1
    )[1].split("\nfi", 1)[0]
    assert "exit 1" in missing_database_block
    assert "PRAGMA quick_check;" in backup_script
    assert "sqlite_master" in backup_script
    assert "reminders', 'chat_settings" in backup_script
    assert 'if [ ! -s "$TEMP_BACKUP_FILE" ]; then' in backup_script
    assert 'mv -- "$TEMP_BACKUP_FILE" "$BACKUP_FILE"' in backup_script
    assert "$PROJECT_DIR/data/reminders.db" in backup_script

    assert '"$PUBLIC_BASE_URL/health"' in deploy_script
    assert '"$PUBLIC_BASE_URL/ready"' in deploy_script
    assert '"$PUBLIC_BASE_URL/tma/"' in deploy_script
    assert "curl -fsSI" in deploy_script
    assert "telegram-reminder-bot:rollback" in deploy_script
    assert "Legacy single-file database mount detected" in deploy_script
    assert "Both legacy and data-directory databases exist" in deploy_script
    assert "REMINDER_BOT_READINESS_TIMEOUT_SECONDS" in deploy_script
    assert "REMINDER_BOT_DEPLOY_BRANCH:-main" in deploy_script
    assert "REMINDER_BOT_DEPLOY_REMOTE:-origin" in deploy_script
    assert '"$current_branch" != "$EXPECTED_DEPLOY_BRANCH"' in deploy_script
    assert '"$upstream_branch" != "$EXPECTED_UPSTREAM"' in deploy_script
    assert '"$EXPECTED_DEPLOY_REMOTE" "$EXPECTED_DEPLOY_BRANCH"' in deploy_script
    assert "git diff --quiet" in deploy_script
    assert "git ls-files --others --exclude-standard" in deploy_script
    assert "docker inspect --format '{{.Image}}'" in deploy_script
    assert "docker compose config --quiet" in deploy_script
