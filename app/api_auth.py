from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.config import BOT_TOKEN, require_bot_token
from app.tma_auth import TelegramInitData, TelegramInitDataError
from app.tma_auth import validate_telegram_init_data
from app.tma_launch import (
    TmaLaunchContext,
    TmaLaunchTokenError,
    validate_tma_launch_token,
)

TMA_INIT_DATA_HEADER = "X-Telegram-Init-Data"


def require_api_bot_token(bot_token: str | None) -> str:
    try:
        return require_bot_token(bot_token)
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail="Bot token is not configured.",
        ) from error


def get_api_bot_token(request: Request) -> str:
    return require_api_bot_token(getattr(request.app.state, "bot_token", BOT_TOKEN))


def get_tma_init_data(
    request: Request,
    x_telegram_init_data: Annotated[
        str | None,
        Header(alias=TMA_INIT_DATA_HEADER),
    ] = None,
) -> TelegramInitData:
    if x_telegram_init_data is None:
        raise HTTPException(
            status_code=401,
            detail="Telegram init data is required.",
        )

    try:
        return validate_telegram_init_data(
            x_telegram_init_data,
            bot_token=get_api_bot_token(request),
        )
    except TelegramInitDataError as error:
        raise HTTPException(
            status_code=401,
            detail=str(error),
        ) from error


def get_tma_chat(
    init_data: TelegramInitData,
    *,
    bot_token: str | None = None,
) -> dict[str, object]:
    return build_tma_chat_from_launch_context(
        get_tma_launch_context(
            init_data,
            bot_token=require_api_bot_token(
                BOT_TOKEN if bot_token is None else bot_token
            ),
        ),
    )


def get_tma_chat_dependency(
    request: Request,
    init_data: TelegramInitData = Depends(get_tma_init_data),
) -> dict[str, object]:
    return get_tma_chat(
        init_data,
        bot_token=get_api_bot_token(request),
    )


def get_tma_launch_context(
    init_data: TelegramInitData,
    *,
    bot_token: str,
) -> TmaLaunchContext:
    if not init_data.start_param:
        raise HTTPException(
            status_code=401,
            detail="Telegram init data start_param is required.",
        )

    try:
        launch_context = validate_tma_launch_token(
            init_data.start_param,
            secret=bot_token,
        )
    except TmaLaunchTokenError as error:
        raise HTTPException(
            status_code=401,
            detail=str(error),
        ) from error

    _validate_signed_tma_chat(init_data, launch_context)
    return launch_context


def _validate_signed_tma_chat(
    init_data: TelegramInitData,
    launch_context: TmaLaunchContext,
) -> None:
    if init_data.chat is None:
        return

    if "id" in init_data.chat:
        chat_id = init_data.chat["id"]
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            raise HTTPException(
                status_code=401,
                detail="Telegram init data chat.id must be an integer.",
            )
        if chat_id != launch_context.chat_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Telegram init data chat.id does not match "
                    "TMA launch token chat_id."
                ),
            )

    if "type" in init_data.chat:
        chat_type = init_data.chat["type"]
        if not isinstance(chat_type, str) or not chat_type:
            raise HTTPException(
                status_code=401,
                detail="Telegram init data chat.type must be a non-empty string.",
            )
        if chat_type != launch_context.chat_type:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Telegram init data chat.type does not match "
                    "TMA launch token chat_type."
                ),
            )


def build_tma_chat_from_launch_context(
    launch_context: TmaLaunchContext,
) -> dict[str, object]:
    chat: dict[str, object] = {
        "id": launch_context.chat_id,
        "type": launch_context.chat_type,
    }

    if launch_context.chat_title:
        chat["title"] = launch_context.chat_title

    return chat


def get_tma_chat_id(
    chat: dict[str, object] = Depends(get_tma_chat_dependency),
) -> int:
    chat_id = chat.get("id")
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        raise HTTPException(
            status_code=401,
            detail="Telegram init data chat.id must be an integer.",
        )

    return chat_id
