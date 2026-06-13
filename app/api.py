from fastapi import FastAPI, HTTPException

from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderResponse,
    build_reminder_response,
)
from app.reminder_service import (
    delete_active_reminder_for_chat,
    get_chat_timezone_name,
    list_active_reminders_for_chat,
    set_chat_timezone_for_chat,
)

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


@app.get(
    "/api/chats/{chat_id}/timezone",
    response_model=ChatTimezoneResponse,
)
def get_chat_timezone(chat_id: int) -> ChatTimezoneResponse:
    return ChatTimezoneResponse(
        chat_id=chat_id,
        timezone_name=get_chat_timezone_name(chat_id),
    )


@app.put(
    "/api/chats/{chat_id}/timezone",
    response_model=ChatTimezoneResponse,
)
def update_chat_timezone(
    chat_id: int,
    request: ChatTimezoneUpdateRequest,
) -> ChatTimezoneResponse:
    is_timezone_updated = set_chat_timezone_for_chat(
        chat_id=chat_id,
        timezone_name=request.timezone_name,
    )

    if not is_timezone_updated:
        raise HTTPException(
            status_code=400,
            detail="Invalid timezone name.",
        )

    return ChatTimezoneResponse(
        chat_id=chat_id,
        timezone_name=request.timezone_name,
    )


@app.delete(
    "/api/chats/{chat_id}/reminders/{reminder_id}",
    response_model=DeleteReminderResponse,
)
def delete_chat_reminder(chat_id: int, reminder_id: int) -> DeleteReminderResponse:
    was_deleted = delete_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )

    if not was_deleted:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found.",
        )

    return DeleteReminderResponse(
        id=reminder_id,
        chat_id=chat_id,
        deleted=True,
    )
