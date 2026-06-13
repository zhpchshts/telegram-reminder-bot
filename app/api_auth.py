from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import BOT_TOKEN
from app.tma_auth import TelegramInitData, TelegramInitDataError
from app.tma_auth import validate_telegram_init_data
from app.tma_launch import (
    TmaLaunchContext,
    TmaLaunchTokenError,
    validate_tma_launch_token,
)

TMA_INIT_DATA_HEADER = "X-Telegram-Init-Data"


def get_tma_init_data(
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
            bot_token=BOT_TOKEN,
        )
    except TelegramInitDataError as error:
        raise HTTPException(
            status_code=401,
            detail=str(error),
        ) from error


def get_tma_chat(
    init_data: TelegramInitData = Depends(get_tma_init_data),
) -> dict[str, object]:
    return build_tma_chat_from_launch_context(
        get_tma_launch_context(init_data),
    )


def get_tma_launch_context(
    init_data: TelegramInitData,
) -> TmaLaunchContext:
    if not init_data.start_param:
        raise HTTPException(
            status_code=401,
            detail="Telegram init data start_param is required.",
        )

    try:
        return validate_tma_launch_token(
            init_data.start_param,
            secret=BOT_TOKEN,
        )
    except TmaLaunchTokenError as error:
        raise HTTPException(
            status_code=401,
            detail=str(error),
        ) from error


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
    chat: dict[str, object] = Depends(get_tma_chat),
) -> int:
    chat_id = chat.get("id")
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        raise HTTPException(
            status_code=401,
            detail="Telegram init data chat.id must be an integer.",
        )

    return chat_id


def require_matching_chat_id(
    chat_id: int,
    tma_chat_id: int = Depends(get_tma_chat_id),
) -> int:
    if tma_chat_id != chat_id:
        raise HTTPException(
            status_code=403,
            detail="Telegram init data chat_id does not match requested chat_id.",
        )

    return tma_chat_id
