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


def get_tma_chat(
    init_data: TelegramInitData = Depends(get_tma_init_data),
) -> dict[str, object]:
    if init_data.chat is not None:
        return init_data.chat

    if init_data.user is None:
        raise HTTPException(
            status_code=401,
            detail="Telegram init data chat or user is required.",
        )

    user_id = init_data.user.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise HTTPException(
            status_code=401,
            detail="Telegram init data user.id must be an integer.",
        )

    private_chat: dict[str, object] = {
        "id": user_id,
        "type": "private",
    }

    for field_name in ("first_name", "last_name", "username"):
        field_value = init_data.user.get(field_name)
        if isinstance(field_value, str):
            private_chat[field_name] = field_value

    return private_chat


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
