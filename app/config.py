import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DB_PATH = Path(os.getenv("DB_PATH", "reminders.db"))

APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Asia/Yekaterinburg")
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)

HEALTHCHECK_CHAT_ID_TEXT = os.getenv("HEALTHCHECK_CHAT_ID")
HEALTHCHECK_CHAT_ID = (
    int(HEALTHCHECK_CHAT_ID_TEXT) if HEALTHCHECK_CHAT_ID_TEXT else None
)
HEALTHCHECK_INTERVAL_MINUTES = int(os.getenv("HEALTHCHECK_INTERVAL_MINUTES", "360"))

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
TMA_URL = os.getenv("TMA_URL")
TMA_BOT_USERNAME = os.getenv("TMA_BOT_USERNAME", "ZhpchshtsReminderBot")
TMA_DIRECT_URL = os.getenv(
    "TMA_DIRECT_URL",
    f"https://t.me/{TMA_BOT_USERNAME}?startapp=",
)
API_ALLOWED_ORIGINS_TEXT = os.getenv("API_ALLOWED_ORIGINS", "")
API_ALLOWED_ORIGINS = [
    origin.strip() for origin in API_ALLOWED_ORIGINS_TEXT.split(",") if origin.strip()
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set.\nCheck your .env file.")
