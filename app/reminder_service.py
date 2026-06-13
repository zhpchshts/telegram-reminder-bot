from app.config import APP_TIMEZONE_NAME
from app.database import (
    get_active_reminder_for_chat,
    get_active_reminders_for_chat,
    get_chat_timezone,
    mark_reminder_as_deleted,
)
from app.formatting import format_reminder_for_list, get_int
from app.scheduler import format_next_run_line, scheduler


def get_chat_timezone_name(chat_id: int) -> str:
    return get_chat_timezone(chat_id) or APP_TIMEZONE_NAME


def delete_active_reminder_for_chat(reminder_id: int, chat_id: int) -> bool:
    reminder = get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )

    if not reminder:
        return False

    job = scheduler.get_job(str(reminder_id))
    if job:
        scheduler.remove_job(str(reminder_id))

    mark_reminder_as_deleted(reminder_id)

    return True


def build_active_reminders_list_text_for_chat(chat_id: int) -> str | None:
    reminders = get_active_reminders_for_chat(chat_id)

    if not reminders:
        return None

    lines = ["Активные напоминания в этом чате\n"]

    lines.extend(
        format_reminder_for_list(
            reminder,
            format_next_run_line(get_int(reminder, "id")),
        )
        for reminder in reminders
    )

    return "\n\n".join(lines)
