from datetime import timedelta


MONTH_NAMES_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

VALID_WEEKDAYS = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}

APSCHEDULER_WEEKDAYS = {
    "MON": "mon",
    "TUE": "tue",
    "WED": "wed",
    "THU": "thu",
    "FRI": "fri",
    "SAT": "sat",
    "SUN": "sun",
}

REMINDER_KIND_TEXT = "text"
REMINDER_KIND_WEATHER = "weather"

MESSAGE_DELETION_DELAY = timedelta(hours=47, minutes=45)

VALID_REMINDER_KINDS = {
    REMINDER_KIND_TEXT,
    REMINDER_KIND_WEATHER,
}

COMPLETION_REPEAT_INTERVAL_OPTIONS = (
    (15, "15 минут"),
    (30, "30 минут"),
    (60, "1 час"),
    (120, "2 часа"),
    (240, "4 часа"),
    (480, "8 часов"),
    (720, "12 часов"),
    (1440, "24 часа"),
)
VALID_COMPLETION_REPEAT_INTERVALS = {
    value for value, _label in COMPLETION_REPEAT_INTERVAL_OPTIONS
}
TELEGRAM_MESSAGE_MAX_LENGTH = 4096
COMPLETION_REMINDER_TEXT_MAX_LENGTH = 3900
COMPLETION_MESSAGE_SUFFIX = "\n\n✅ Выполнено"

WEEKDAY_NAMES_RU_PLURAL = {
    "MON": "понедельникам",
    "TUE": "вторникам",
    "WED": "средам",
    "THU": "четвергам",
    "FRI": "пятницам",
    "SAT": "субботам",
    "SUN": "воскресеньям",
}

WEEKDAY_NAMES_RU_SINGLE = {
    "MON": "понедельник",
    "TUE": "вторник",
    "WED": "среду",
    "THU": "четверг",
    "FRI": "пятницу",
    "SAT": "субботу",
    "SUN": "воскресенье",
}

ORDINAL_NAMES_RU = {
    1: "1-й",
    2: "2-й",
    3: "3-й",
    4: "4-й",
    5: "5-й",
}

REMINDER_COLUMNS = """
    id,
    chat_id,
    text,
    reminder_kind,
    schedule_type,
    status,
    start_at,
    interval_days,
    interval_weeks,
    day_of_week,
    month_week_number,
    month_day,
    timezone,
    delete_after_two_days,
    requires_completion,
    repeat_interval_minutes,
    revision,
    delivery_tracking_started_at_utc,
    last_handled_scheduled_for_utc,
    EXISTS (
        SELECT 1
        FROM reminder_completion_occurrences AS completion_occurrence
        WHERE completion_occurrence.reminder_id = reminders.id
          AND completion_occurrence.reminder_revision = reminders.revision
          AND (
              completion_occurrence.status = 'active'
              OR completion_occurrence.status = 'completing'
              OR (
                  completion_occurrence.status = 'pending'
                  AND completion_occurrence.current_message_id IS NOT NULL
              )
          )
    ) AS awaiting_completion
"""

SCHEMA_MIGRATIONS = {
    "reminder_kind": "reminder_kind TEXT NOT NULL DEFAULT 'text'",
    "interval_weeks": "interval_weeks INTEGER",
    "day_of_week": "day_of_week TEXT",
    "month_week_number": "month_week_number INTEGER",
    "month_day": "month_day INTEGER",
    "timezone": "timezone TEXT",
    "delete_after_two_days": ("delete_after_two_days INTEGER NOT NULL DEFAULT 0"),
    "requires_completion": "requires_completion INTEGER NOT NULL DEFAULT 0",
    "repeat_interval_minutes": "repeat_interval_minutes INTEGER",
    "revision": "revision INTEGER NOT NULL DEFAULT 1",
    "delivery_tracking_started_at_utc": "delivery_tracking_started_at_utc TEXT",
    "last_handled_scheduled_for_utc": "last_handled_scheduled_for_utc TEXT",
}

WEEKDAY_HELP = "MON, TUE, WED, THU, FRI, SAT, SUN"

TIMEZONE_LOOKUP_URL = "https://www.addevent.com/c/documentation/tools/time-zone-lookup"
