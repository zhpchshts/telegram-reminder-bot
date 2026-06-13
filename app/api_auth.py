from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import BOT_TOKEN
from app.tma_auth import TelegramInitData, TelegramInitDataError
from app.tma_auth import validate_telegram_init_data

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


def get_tma_chat_id(
    init_data: TelegramInitData = Depends(get_tma_init_data),
) -> int:
    if init_data.chat is None:
        raise HTTPException(
            status_code=401,
            detail="Telegram init data chat is required.",
        )

    chat_id = init_data.chat.get("id")

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
