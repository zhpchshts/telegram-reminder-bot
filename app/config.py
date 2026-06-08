import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = Path("reminders.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Check your .env file.")