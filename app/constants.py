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
    schedule_type,
    status,
    start_at,
    interval_days,
    interval_weeks,
    day_of_week,
    month_week_number
"""

SCHEMA_MIGRATIONS = {
    "interval_weeks": "interval_weeks INTEGER",
    "day_of_week": "day_of_week TEXT",
    "month_week_number": "month_week_number INTEGER",
}

WEEKDAY_HELP = "MON, TUE, WED, THU, FRI, SAT, SUN"
