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


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Check your .env file.")
