from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import API_ALLOWED_ORIGINS

from app.api_auth import get_tma_chat_id, get_tma_init_data, require_matching_chat_id
from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderCreateRequest,
    ReminderFormOptionsResponse,
    ReminderResponse,
    TmaContextResponse,
    build_created_reminder_response,
    build_reminder_create_data,
    build_reminder_form_options_response,
    build_reminder_response,
    build_tma_context_response,
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


def configure_cors(
    fastapi_app: FastAPI,
    allowed_origins: list[str],
) -> None:
    if not allowed_origins:
        return

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


configure_cors(app, API_ALLOWED_ORIGINS)


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
    "/api/tma/context",
    response_model=TmaContextResponse,
)
def get_tma_context(
    init_data=Depends(get_tma_init_data),
    chat_id: int = Depends(get_tma_chat_id),
) -> TmaContextResponse:
    return build_tma_context_response(
        auth_date=init_data.auth_date,
        user=init_data.user,
        chat=init_data.chat,
        chat_id=chat_id,
        timezone_name=get_chat_timezone_name(chat_id),
        chat_type=init_data.chat_type,
        start_param=init_data.start_param,
    )


@app.get(
    "/api/tma/reminder-options",
    response_model=ReminderFormOptionsResponse,
)
def get_reminder_form_options(
    _init_data=Depends(get_tma_init_data),
) -> ReminderFormOptionsResponse:
    return build_reminder_form_options_response()


@app.get(
    "/api/chats/{chat_id}/reminders",
    response_model=list[ReminderResponse],
)
def get_chat_reminders(
    authorized_chat_id: int = Depends(require_matching_chat_id),
) -> list[ReminderResponse]:
    return [
        build_reminder_response(reminder)
        for reminder in list_active_reminders_for_chat(authorized_chat_id)
    ]


@app.post(
    "/api/chats/{chat_id}/reminders",
    response_model=ReminderResponse,
    status_code=201,
)
def create_chat_reminder(
    request: ReminderCreateRequest,
    authorized_chat_id: int = Depends(require_matching_chat_id),
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
            chat_id=authorized_chat_id,
            data=data,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return build_created_reminder_response(
        reminder_id=reminder_id,
        chat_id=authorized_chat_id,
        data=data,
    )


@app.get(
    "/api/chats/{chat_id}/timezone",
    response_model=ChatTimezoneResponse,
)
def get_chat_timezone(
    authorized_chat_id: int = Depends(require_matching_chat_id),
) -> ChatTimezoneResponse:
    return ChatTimezoneResponse(
        chat_id=authorized_chat_id,
        timezone_name=get_chat_timezone_name(authorized_chat_id),
    )


@app.put(
    "/api/chats/{chat_id}/timezone",
    response_model=ChatTimezoneResponse,
)
def update_chat_timezone(
    request: ChatTimezoneUpdateRequest,
    authorized_chat_id: int = Depends(require_matching_chat_id),
) -> ChatTimezoneResponse:
    is_timezone_updated = set_chat_timezone_for_chat(
        chat_id=authorized_chat_id,
        timezone_name=request.timezone_name,
    )

    if not is_timezone_updated:
        raise HTTPException(
            status_code=400,
            detail="Invalid timezone name.",
        )

    return ChatTimezoneResponse(
        chat_id=authorized_chat_id,
        timezone_name=request.timezone_name,
    )


@app.delete(
    "/api/chats/{chat_id}/reminders/{reminder_id}",
    response_model=DeleteReminderResponse,
)
def delete_chat_reminder(
    reminder_id: int,
    authorized_chat_id: int = Depends(require_matching_chat_id),
) -> DeleteReminderResponse:
    was_deleted = delete_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=authorized_chat_id,
    )

    if not was_deleted:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found.",
        )

    return DeleteReminderResponse(
        id=reminder_id,
        chat_id=authorized_chat_id,
        deleted=True,
    )
