from app.config import APP_TIMEZONE_NAME
from app.database import (
    get_active_reminder_for_chat,
    get_chat_timezone,
    mark_reminder_as_deleted,
)
from app.scheduler import scheduler


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
