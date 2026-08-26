from datetime import datetime
import logging
from pathlib import Path
import sqlite3
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


from aiogram import Bot
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path as FastApiPath,
    Query,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.api_auth import (
    TMA_INIT_DATA_HEADER,
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
    ReminderUpdateRequest,
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
from app.constants import SQLITE_INT64_MAX
from app.database import get_connection
from app.reminder_models import ReminderCreateData, ReminderReadData
from app.reminder_service import (
    ReminderIdempotencyConflictError,
    ReminderIdempotencyPendingError,
    ReminderRevisionConflictError,
    ReminderSchedulingError,
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
from app.scheduler import (
    get_missing_required_scheduler_job_ids,
    get_next_run_at_for_schedule,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMA_STATIC_DIR = PROJECT_ROOT / "tma"
LOGGER = logging.getLogger(__name__)


app = FastAPI(
    title="Telegram Reminder Bot API",
    version="0.1.0",
)

TMA_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Expires": "0",
}
API_PRIVATE_NO_CACHE_CONTROL = "private, no-store"
MAX_API_REQUEST_BODY_BYTES = 16 * 1024
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9._:-]+$"
ReminderIdPath = Annotated[int, FastApiPath(ge=1, le=SQLITE_INT64_MAX)]
ReminderRevisionQuery = Annotated[int, Query(ge=1, le=SQLITE_INT64_MAX)]
IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_KEY_PATTERN,
    ),
]


def add_private_api_cache_headers(response) -> None:
    response.headers["Cache-Control"] = API_PRIVATE_NO_CACHE_CONTROL
    vary_header = response.headers.get("Vary")
    vary_values = {value.strip().casefold() for value in (vary_header or "").split(",")}
    if TMA_INIT_DATA_HEADER.casefold() not in vary_values:
        response.headers["Vary"] = (
            f"{vary_header}, {TMA_INIT_DATA_HEADER}"
            if vary_header
            else TMA_INIT_DATA_HEADER
        )


class ApiRequestBodyLimitMiddleware:
    def __init__(self, app, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send) -> None:
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        is_limited_request = (
            scope.get("type") == "http"
            and (path == "/api" or path.startswith("/api/"))
            and method in {"POST", "PUT", "PATCH"}
        )
        if not is_limited_request:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        content_length = headers.get("content-length")
        try:
            declared_size = int(content_length) if content_length is not None else None
        except ValueError:
            declared_size = None

        if declared_size is not None and declared_size > self.max_body_bytes:
            await self._send_too_large(scope, receive, send)
            return

        buffered_messages: list[dict[str, object]] = []
        received_size = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                buffered_messages.append(message)
                break

            body = message.get("body", b"")
            if isinstance(body, bytes):
                received_size += len(body)
            if received_size > self.max_body_bytes:
                await self._send_too_large(scope, receive, send)
                return

            buffered_messages.append(message)
            if not message.get("more_body", False):
                break

        message_index = 0

        async def replay_receive():
            nonlocal message_index
            if message_index < len(buffered_messages):
                message = buffered_messages[message_index]
                message_index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _send_too_large(self, scope, receive, send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Request body is too large."},
        )
        add_private_api_cache_headers(response)
        await response(scope, receive, send)


@app.middleware("http")
async def add_no_cache_headers_for_tma(request, call_next):
    is_api_request = request.url.path == "/api" or request.url.path.startswith("/api/")
    response = await call_next(request)

    if request.url.path == "/tma" or request.url.path.startswith("/tma/"):
        response.headers.update(TMA_NO_CACHE_HEADERS)

    if is_api_request:
        add_private_api_cache_headers(response)

    return response


app.add_middleware(
    ApiRequestBodyLimitMiddleware,
    max_body_bytes=MAX_API_REQUEST_BODY_BYTES,
)


def add_allowed_origin_headers(request: Request, response) -> None:
    origin = request.headers.get("origin")
    if not origin or not (origin in API_ALLOWED_ORIGINS or "*" in API_ALLOWED_ORIGINS):
        return

    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    vary_header = response.headers.get("Vary")
    vary_values = {value.strip().casefold() for value in (vary_header or "").split(",")}
    if "origin" not in vary_values:
        response.headers["Vary"] = f"{vary_header}, Origin" if vary_header else "Origin"


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, error: Exception):
    LOGGER.error(
        "Unhandled request error: method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=(type(error), error, error.__traceback__),
    )
    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )
    if request.url.path == "/api" or request.url.path.startswith("/api/"):
        add_private_api_cache_headers(response)
        add_allowed_origin_headers(request, response)
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
        delete_after_two_days=request.delete_after_two_days,
        requires_completion=request.requires_completion,
        repeat_interval_minutes=request.repeat_interval_minutes,
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
    except (ZoneInfoNotFoundError, ValueError) as error:
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


@app.head("/health", include_in_schema=False)
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.head("/ready", include_in_schema=False)
@app.get("/ready")
def readiness(request: Request) -> dict[str, str]:
    runtime_scheduler = getattr(request.app.state, "scheduler", None)
    is_restored = getattr(request.app.state, "reminders_restored", False)
    bot = getattr(request.app.state, "bot", None)

    if bot is None or runtime_scheduler is None or not runtime_scheduler.running:
        raise HTTPException(status_code=503, detail="Service is not ready.")
    if not is_restored:
        raise HTTPException(status_code=503, detail="Service is not ready.")

    try:
        missing_job_ids = get_missing_required_scheduler_job_ids(runtime_scheduler)
    except Exception as error:
        raise HTTPException(status_code=503, detail="Service is not ready.") from error
    if missing_job_ids:
        raise HTTPException(status_code=503, detail="Service is not ready.")

    try:
        with get_connection() as connection:
            connection.execute("SELECT 1 FROM reminders LIMIT 1").fetchone()
            connection.execute("SELECT 1 FROM chat_settings LIMIT 1").fetchone()
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail="Service is not ready.") from error

    return {"status": "ready"}


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
    if (
        request.expected_revision is None
        or request.expected_revision != current_reminder.revision
    ):
        raise HTTPException(
            status_code=409,
            detail="Reminder was changed. Refresh it and try again.",
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
    idempotency_key: IdempotencyKeyHeader = None,
) -> ReminderResponse:
    return create_reminder_for_chat(
        request=request,
        chat_id=chat_id,
        bot=bot,
        idempotency_key=idempotency_key,
    )


@app.put(
    "/api/tma/reminders/{reminder_id}",
    response_model=ReminderResponse,
    response_model_exclude_unset=True,
)
def update_tma_reminder(
    reminder_id: ReminderIdPath,
    request: ReminderUpdateRequest,
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
    reminder_id: ReminderIdPath,
    expected_revision: ReminderRevisionQuery,
    chat_id: int = Depends(get_tma_chat_id),
) -> DeleteReminderResponse:
    return delete_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=chat_id,
        expected_revision=expected_revision,
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
    idempotency_key: IdempotencyKeyHeader = None,
) -> ReminderResponse:
    return create_reminder_for_chat(
        request=request,
        chat_id=authorized_chat_id,
        bot=bot,
        idempotency_key=idempotency_key,
    )


@app.put(
    "/api/chats/{chat_id}/reminders/{reminder_id}",
    response_model=ReminderResponse,
    response_model_exclude_unset=True,
)
def update_chat_reminder(
    reminder_id: ReminderIdPath,
    request: ReminderUpdateRequest,
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
    reminder_id: ReminderIdPath,
    expected_revision: ReminderRevisionQuery,
    authorized_chat_id: int = Depends(require_matching_chat_id),
) -> DeleteReminderResponse:
    return delete_reminder_for_chat(
        reminder_id=reminder_id,
        chat_id=authorized_chat_id,
        expected_revision=expected_revision,
    )


def build_validated_reminder_create_data(
    request: ReminderCreateRequest,
    *,
    allow_past_start_at: bool = False,
) -> ReminderCreateData:
    try:
        data = build_reminder_create_data(request)
    except (ZoneInfoNotFoundError, ValueError) as error:
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
    idempotency_key: str | None = None,
) -> ReminderResponse:
    data = build_validated_reminder_create_data(
        request,
        allow_past_start_at=idempotency_key is not None,
    )

    try:
        if idempotency_key is None:
            reminder_id = create_scheduled_reminder(
                bot=bot,
                chat_id=chat_id,
                data=data,
            )
        else:
            reminder_id = create_scheduled_reminder(
                bot=bot,
                chat_id=chat_id,
                data=data,
                idempotency_key=idempotency_key,
            )
    except ReminderIdempotencyConflictError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error
    except ReminderIdempotencyPendingError as error:
        raise HTTPException(
            status_code=425,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
    except ReminderSchedulingError as error:
        raise HTTPException(
            status_code=503,
            detail="Reminder was not created because scheduling failed.",
        ) from error

    if idempotency_key is not None:
        stored_reminder = get_active_reminder_for_chat(
            reminder_id=reminder_id,
            chat_id=chat_id,
        )
        if stored_reminder is not None:
            return build_reminder_response(stored_reminder)

    return build_created_reminder_response(
        reminder_id=reminder_id,
        chat_id=chat_id,
        data=data,
    )


def update_reminder_for_chat(
    *,
    reminder_id: int,
    request: ReminderUpdateRequest,
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
    expected_revision = getattr(
        request,
        "expected_revision",
        current_reminder.revision,
    )
    if current_reminder.revision != expected_revision:
        raise HTTPException(
            status_code=409,
            detail="Reminder was changed. Refresh it and try again.",
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
            expected_revision=expected_revision,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
    except ReminderRevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail="Reminder was changed. Refresh it and try again.",
        ) from error
    except ReminderSchedulingError as error:
        raise HTTPException(
            status_code=503,
            detail="Reminder was updated, but rescheduling failed.",
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
    expected_revision: int | None = None,
) -> DeleteReminderResponse:
    try:
        was_deleted = delete_active_reminder_for_chat(
            reminder_id=reminder_id,
            chat_id=chat_id,
            expected_revision=expected_revision,
        )
    except ReminderRevisionConflictError as error:
        raise HTTPException(
            status_code=409,
            detail="Reminder was changed. Refresh it and try again.",
        ) from error
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
