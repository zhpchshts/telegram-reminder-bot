from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from fastapi import Depends, FastAPI, HTTPException, Request

from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderCreateRequest,
    ReminderResponse,
    build_created_reminder_response,
    build_reminder_create_data,
    build_reminder_response,
)
from app.reminder_models import ReminderCreateData
from app.reminder_service import (
    create_scheduled_reminder,
    delete_active_reminder_for_chat,
    get_chat_timezone_name,
    list_active_reminders_for_chat,
    set_chat_timezone_for_chat,
)

app = FastAPI(
    title="Telegram Reminder Bot API",
    version="0.1.0",
)


def get_bot_from_app_state(request: Request) -> Bot:
    bot = getattr(request.app.state, "bot", None)

    if bot is None:
        raise HTTPException(
            status_code=503,
            detail="Bot is not configured for API.",
        )

    return bot


def is_start_at_in_past(data: ReminderCreateData) -> bool:
    timezone = ZoneInfo(data.timezone_name)
    now = datetime.now(timezone)
    start_at = data.start_at

    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone)

    return start_at <= now


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


@app.post(
    "/api/chats/{chat_id}/reminders",
    response_model=ReminderResponse,
    status_code=201,
)
def create_chat_reminder(
    chat_id: int,
    request: ReminderCreateRequest,
    bot: Bot = Depends(get_bot_from_app_state),
) -> ReminderResponse:
    try:
        data = build_reminder_create_data(request)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid timezone name.",
        ) from error

    if is_start_at_in_past(data):
        raise HTTPException(
            status_code=400,
            detail="start_at must be in the future.",
        )

    try:
        reminder_id = create_scheduled_reminder(
            bot=bot,
            chat_id=chat_id,
            data=data,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return build_created_reminder_response(
        reminder_id=reminder_id,
        chat_id=chat_id,
        data=data,
    )


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
