import os
from pathlib import Path
from zoneinfo import ZoneInfo


from dotenv import load_dotenv


load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = Path("reminders.db")
APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Asia/Yekaterinburg")
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Check your .env file.")
