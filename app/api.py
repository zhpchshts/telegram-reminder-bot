from fastapi import FastAPI

from app.api_models import ReminderResponse, build_reminder_response
from app.reminder_service import list_active_reminders_for_chat

app = FastAPI(
    title="Telegram Reminder Bot API",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/api/chats/{chat_id}/reminders",
    response_model=list[ReminderResponse],
)
def get_chat_reminders(chat_id: int) -> list[ReminderResponse]:
    return [
        build_reminder_response(reminder)
        for reminder in list_active_reminders_for_chat(chat_id)
    ]
