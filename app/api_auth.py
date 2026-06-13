from typing import Annotated

from fastapi import Header, HTTPException

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
