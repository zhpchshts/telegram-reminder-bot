from app.config import APP_TIMEZONE_NAME
from app.database import get_chat_timezone


def get_chat_timezone_name(chat_id: int) -> str:
    return get_chat_timezone(chat_id) or APP_TIMEZONE_NAME
