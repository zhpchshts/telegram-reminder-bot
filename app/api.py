import importlib.metadata

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


from aiogram import Bot
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import tzdata

from app.api_auth import (
    get_tma_chat,
    get_tma_chat_id,
    get_tma_init_data,
    require_matching_chat_id,
)
from app.api_models import (
    ChatTimezoneResponse,
    ChatTimezoneUpdateRequest,
    DeleteReminderResponse,
    ReminderCreateRequest,
    ReminderPreviewRequest,
    ReminderFormOptionsResponse,
    ReminderPreviewResponse,
    ReminderResponse,
    TmaBootstrapResponse,
    TmaContextResponse,
    build_created_reminder_response,
    build_reminder_create_data,
    normalize_start_at,
    build_reminder_form_options_response,
    build_reminder_preview_response,
    build_reminder_response,
    build_tma_bootstrap_response,
    build_tma_context_response,
)
from app.config import API_ALLOWED_ORIGINS
from app.database import count_active_chats
from app.reminder_models import ReminderCreateData, ReminderReadData
from app.reminder_service import (
    create_scheduled_reminder,
    delete_active_reminder_for_chat,
    get_active_reminder_for_chat,
    get_chat_timezone_name,
    list_active_reminders_for_chat,
    set_chat_timezone_for_chat,
    update_active_reminder_for_chat,
    validate_reminder_create_data,
)
from app.schedule_calculations import get_yearly_datetime_on_or_after
from app.scheduler import get_next_run_at_for_schedule

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMA_STATIC_DIR = PROJECT_ROOT / "tma"


app = FastAPI(
    title="Telegram Reminder Bot API",
    version="0.1.0",
)

TMA_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.middleware("http")
async def add_no_cache_headers_for_tma(request, call_next):
    response = await call_next(request)

    if request.url.path == "/tma" or request.url.path.startswith("/tma/"):
        response.headers.update(TMA_NO_CACHE_HEADERS)

    return response


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


def mount_tma_static_files(
    fastapi_app: FastAPI,
    static_dir: Path,
) -> None:
    if not static_dir.exists():
        return

    fastapi_app.mount(
        "/tma",
        StaticFiles(directory=static_dir, html=True),
        name="tma",
    )


configure_cors(app, API_ALLOWED_ORIGINS)
mount_tma_static_files(app, TMA_STATIC_DIR)


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


def validate_reminder_update_data(
    *,
    current_reminder: ReminderReadData,
    request: ReminderCreateRequest,
) -> None:
    if request.reminder_kind != current_reminder.reminder_kind:
        raise HTTPException(
            status_code=400,
            detail="reminder_kind cannot be changed.",
        )

    if request.schedule_type != current_reminder.schedule_type:
        raise HTTPException(
            status_code=400,
            detail="schedule_type cannot be changed.",
        )


def build_repeating_reminder_update_request(
    *,
    current_reminder: ReminderReadData,
    request: ReminderCreateRequest,
) -> ReminderCreateRequest:
    requested_start_at = normalize_start_at(
        request.start_at,
        request.timezone_name,
    )
    current_start_at = normalize_start_at(
        current_reminder.start_at,
        request.timezone_name,
    )

    if current_reminder.schedule_type == "yearly_date":
        schedule_start_at = get_yearly_datetime_on_or_after(
            selected_start_at=requested_start_at,
            lower_bound=current_start_at,
        )
    else:
        schedule_start_at = datetime.combine(
            current_start_at.date(),
            requested_start_at.timetz(),
        )

    return ReminderCreateRequest(
        reminder_text=request.reminder_text,
        reminder_kind=request.reminder_kind,
        schedule_type=request.schedule_type,
        start_at=schedule_start_at,
        timezone_name=request.timezone_name,
        interval_days=request.interval_days,
        interval_weeks=request.interval_weeks,
        day_of_week=request.day_of_week,
        month_week_number=request.month_week_number,
        month_day=request.month_day,
    )


def build_validated_reminder_update_data(
    *,
    current_reminder: ReminderReadData,
    request: ReminderCreateRequest,
) -> ReminderCreateData:
    validate_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )

    if current_reminder.schedule_type == "once":
        return build_validated_reminder_create_data(request)

    try:
        repeating_request = build_repeating_reminder_update_request(
            current_reminder=current_reminder,
            request=request,
        )
    except ZoneInfoNotFoundError as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid timezone name.",
        ) from error

    return build_validated_reminder_create_data(
        repeating_request,
        allow_past_start_at=True,
    )


def get_next_run_at_for_reminder_data(
    data: ReminderCreateData,
) -> datetime | None:
    return get_next_run_at_for_schedule(
        schedule_type=data.schedule_type,
        start_at=data.start_at,
        interval_days=data.interval_days,
        interval_weeks=data.interval_weeks,
        day_of_week=data.day_of_week,
        month_week_number=data.month_week_number,
        month_day=data.month_day,
        timezone_name=data.timezone_name,
    )


def get_tma_chat_type(
    chat: dict[str, object],
    fallback_chat_type: str | None,
) -> str | None:
    chat_type = chat.get("type")
    if isinstance(chat_type, str):
        return chat_type

    return fallback_chat_type


def get_timezone_database_info() -> dict[str, str]:
    return {
        "tzdata_package_version": importlib.metadata.version("tzdata"),
        "tzdata_iana_version": tzdata.IANA_VERSION,
    }


@app.get("/health")
def health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "active_chats_count": count_active_chats(),
        **get_timezone_database_info(),
    }


@app.get(
    "/api/tma/context",
    response_model=TmaContextResponse,
)
def get_tma_context(
    init_data=Depends(get_tma_init_data),
    tma_chat: dict[str, object] = Depends(get_tma_chat),
    chat_id: int = Depends(get_tma_chat_id),
) -> TmaContextResponse:
    return build_tma_context_response(
        auth_date=init_data.auth_date,
        user=init_data.user,
        chat=tma_chat,
        chat_id=chat_id,
        timezone_name=get_chat_timezone_name(chat_id),
        chat_type=get_tma_chat_type(tma_chat, init_data.chat_type),
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
    "/api/tma/bootstrap",
    response_model=TmaBootstrapResponse,
    response_model_exclude_unset=True,
)
def get_tma_bootstrap(
    init_data=Depends(get_tma_init_data),
    tma_chat: dict[str, object] = Depends(get_tma_chat),
    chat_id: int = Depends(get_tma_chat_id),
) -> TmaBootstrapResponse:
    timezone_name = get_chat_timezone_name(chat_id)
    active_reminders = list_active_reminders_for_chat(chat_id)

    return build_tma_bootstrap_response(
        auth_date=init_data.auth_date,
        user=init_data.user,
        chat=tma_chat,
        chat_id=chat_id,
        timezone_name=timezone_name,
        chat_type=get_tma_chat_type(tma_chat, init_data.chat_type),
        start_param=init_data.start_param,
        active_reminders=active_reminders,
    )


@app.post(
    "/api/tma/reminder-preview",
    response_model=ReminderPreviewResponse,
    response_model_exclude_unset=True,
)
def preview_tma_reminder(
    request: ReminderPreviewRequest,
    _chat_id: int = Depends(get_tma_chat_id),
) -> ReminderPreviewResponse:
    if request.reminder_id is None:
        data = build_validated_reminder_create_data(request)
        return build_reminder_preview_response(data)

    current_reminder = get_active_reminder_for_chat(
        reminder_id=request.reminder_id,
        chat_id=_chat_id,
    )
    if current_reminder is None:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found.",
        )

    data = build_validated_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )
    return build_reminder_preview_response(
        data,
        next_run_at=get_next_run_at_for_reminder_data(data),
    )


@app.get(
    "/api/tma/reminders",
    response_model=list[ReminderResponse],
    response_model_exclude_unset=True,
)
def get_tma_reminders(
    chat_id: int = Depends(get_tma_chat_id),
) -> list[ReminderResponse]:
    return [
        build_reminder_response(reminder)
        for reminder in list_active_reminders_for_chat(chat_id)
    ]


@app.post(
    "/api/tma/reminders",
    response_model=ReminderResponse,
    response_model_exclude_unset=True,
    status_code=201,
)
def create_tma_reminder(
    request: ReminderCreateRequest,
    chat_id: int = Depends(get_tma_chat_id),
    bot: Bot = Depends(get_bot_from_app_state),
) -> ReminderResponse:
    return create_reminder_for_chat(
        request=request,
        chat_id=chat_id,
        bot=bot,
    )


@app.put(
    "/api/tma/reminders/{reminder_id}",
    response_model=ReminderResponse,
    response_model_exclude_unset=True,
)
def update_tma_reminder(
    reminder_id: int,
    request: ReminderCreateRequest,
    chat_id: int = Depends(get_tma_chat_id),
    bot: Bot = Depends(get_bot_from_app_state),
) -> ReminderResponse:
    return update_reminder_for_chat(
        reminder_id=reminder_id,
        request=request,
        chat_id=chat_id,
        bot=bot,
    )


@app.get(
    "/api/tma/timezone",
    response_model=ChatTimezoneResponse,
)
def get_tma_timezone(
    chat_id: int = Depends(get_tma_chat_id),
) -> ChatTimezoneResponse:
    return ChatTimezoneResponse(
        chat_id=chat_id,
        timezone_name=get_chat_timezone_name(chat_id),
    )


@app.put(
    "/api/tma/timezone",
    response_model=ChatTimezoneResponse,
)
def update_tma_timezone(
    request: ChatTimezoneUpdateRequest,
    chat_id: int = Depends(get_tma_chat_id),
) -> ChatTimezoneResponse:
    return update_timezone_for_chat(
        request=request,
        chat_id=chat_id,
    )


@app.delete(
    "/api/tma/reminders/{reminder_id}",
    response_model=DeleteReminderResponse,
)
def delete_tma_reminder(
    reminder_id: int,
    chat_id: int = Depends(get_tma_chat_id),
) -> DeleteReminderResponse:
    return delete_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )


@app.get(
    "/api/chats/{chat_id}/reminders",
    response_model=list[ReminderResponse],
    response_model_exclude_unset=True,
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
    response_model_exclude_unset=True,
    status_code=201,
)
def create_chat_reminder(
    request: ReminderCreateRequest,
    authorized_chat_id: int = Depends(require_matching_chat_id),
    bot: Bot = Depends(get_bot_from_app_state),
) -> ReminderResponse:
    return create_reminder_for_chat(
        request=request,
        chat_id=authorized_chat_id,
        bot=bot,
    )


@app.put(
    "/api/chats/{chat_id}/reminders/{reminder_id}",
    response_model=ReminderResponse,
    response_model_exclude_unset=True,
)
def update_chat_reminder(
    reminder_id: int,
    request: ReminderCreateRequest,
    authorized_chat_id: int = Depends(require_matching_chat_id),
    bot: Bot = Depends(get_bot_from_app_state),
) -> ReminderResponse:
    return update_reminder_for_chat(
        reminder_id=reminder_id,
        request=request,
        chat_id=authorized_chat_id,
        bot=bot,
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
    return update_timezone_for_chat(
        request=request,
        chat_id=authorized_chat_id,
    )


@app.delete(
    "/api/chats/{chat_id}/reminders/{reminder_id}",
    response_model=DeleteReminderResponse,
)
def delete_chat_reminder(
    reminder_id: int,
    authorized_chat_id: int = Depends(require_matching_chat_id),
) -> DeleteReminderResponse:
    return delete_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=authorized_chat_id,
    )


def build_validated_reminder_create_data(
    request: ReminderCreateRequest,
    *,
    allow_past_start_at: bool = False,
) -> ReminderCreateData:
    try:
        data = build_reminder_create_data(request)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid timezone name.",
        ) from error

    if not allow_past_start_at and is_start_at_in_past(data):
        raise HTTPException(
            status_code=400,
            detail="start_at must be in the future.",
        )

    try:
        validate_reminder_create_data(data)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return data


def create_reminder_for_chat(
    *,
    request: ReminderCreateRequest,
    chat_id: int,
    bot: Bot,
) -> ReminderResponse:
    data = build_validated_reminder_create_data(request)

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


def update_reminder_for_chat(
    *,
    reminder_id: int,
    request: ReminderCreateRequest,
    chat_id: int,
    bot: Bot,
) -> ReminderResponse:
    current_reminder = get_active_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
    )
    if current_reminder is None:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found.",
        )

    data = build_validated_reminder_update_data(
        current_reminder=current_reminder,
        request=request,
    )

    try:
        reminder = update_active_reminder_for_chat(
            bot=bot,
            reminder_id=reminder_id,
            chat_id=chat_id,
            data=data,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    if reminder is None:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found.",
        )

    return build_reminder_response(reminder)


def update_timezone_for_chat(
    *,
    request: ChatTimezoneUpdateRequest,
    chat_id: int,
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


def delete_reminder_for_chat(
    *,
    reminder_id: int,
    chat_id: int,
) -> DeleteReminderResponse:
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
