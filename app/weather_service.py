from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.database import (
    get_cached_weather_location,
    save_cached_weather_location,
)


GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

MAX_WEATHER_LOCATIONS = 5
OPEN_METEO_ATTRIBUTION = "Источник: Open-Meteo"
WEATHER_REQUEST_TIMEOUT_SECONDS = 4
WEATHER_REQUEST_ATTEMPTS = 3
WEATHER_REQUEST_RETRY_DELAYS_SECONDS = (1, 2)

LOGGER = logging.getLogger(__name__)

WEATHER_CODE_DESCRIPTIONS = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    56: "слабая ледяная морось",
    57: "ледяная морось",
    61: "слабый дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "слабый ледяной дождь",
    67: "ледяной дождь",
    71: "слабый снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "слабые ливни",
    81: "ливни",
    82: "сильные ливни",
    85: "слабый снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}

WEATHER_CODE_EMOJIS = {
    0: "☀️",
    1: "🌤",
    2: "🌤",
    3: "☁️",
    45: "🌫",
    48: "🌫",
    51: "🌦",
    53: "🌦",
    55: "🌦",
    56: "🌦",
    57: "🌦",
    61: "🌧",
    63: "🌧",
    65: "🌧",
    66: "🌧",
    67: "🌧",
    71: "🌨",
    73: "🌨",
    75: "🌨",
    77: "🌨",
    80: "🌧",
    81: "🌧",
    82: "🌧",
    85: "🌨",
    86: "🌨",
    95: "⛈",
    96: "⛈",
    99: "⛈",
}


class WeatherServiceError(Exception):
    """Raised when weather data cannot be loaded or parsed."""


class RetryableWeatherRequestError(Exception):
    """Raised when a weather request can be retried."""


def parse_weather_locations(raw_locations: str) -> list[str]:
    locations = [
        location.strip()
        for location in re.split(r"[;\n]+", raw_locations)
        if location.strip()
    ]

    unique_locations = []
    seen_locations = set()

    for location in locations:
        normalized_location = location.casefold()
        if normalized_location in seen_locations:
            continue

        unique_locations.append(location)
        seen_locations.add(normalized_location)

    if not unique_locations:
        raise ValueError("weather_locations are required.")

    if len(unique_locations) > MAX_WEATHER_LOCATIONS:
        raise ValueError(
            f"Можно указать не больше {MAX_WEATHER_LOCATIONS} населённых пунктов."
        )

    return unique_locations


def build_weather_report(raw_locations: str) -> str:
    locations = parse_weather_locations(raw_locations)

    location_blocks = []
    for location_name in locations:
        try:
            location = find_location(location_name)
            forecast = fetch_forecast(location)
            location_blocks.append(format_location_forecast(location, forecast))
        except WeatherServiceError as error:
            location_blocks.append(
                f"⚠️ <b>{escape_html(location_name)}</b>\n{escape_html(str(error))}"
            )

    return "\n\n".join(
        [
            "<b>Прогноз погоды на сегодня</b>",
            *location_blocks,
            OPEN_METEO_ATTRIBUTION,
        ]
    )


def find_location(location_name: str) -> dict[str, Any]:
    location_key = normalize_location_key(location_name)
    cached_location = get_cached_weather_location(location_key)

    if cached_location is not None:
        return cached_location

    payload = fetch_json(
        GEOCODING_API_URL,
        {
            "name": location_name,
            "count": 1,
            "language": "ru",
            "format": "json",
        },
        stage="geocoding",
        location_name=location_name,
    )
    results = payload.get("results")

    if not isinstance(results, list) or not results:
        raise WeatherServiceError("Не нашёл населённый пункт.")

    location = results[0]

    if not isinstance(location, dict):
        raise WeatherServiceError("Не смог прочитать данные населённого пункта.")

    if location.get("latitude") is None or location.get("longitude") is None:
        raise WeatherServiceError("Не нашёл координаты населённого пункта.")

    save_cached_weather_location(location_key, location)

    return location


def fetch_forecast(location: dict[str, Any]) -> dict[str, Any]:
    location_name = str(location.get("name") or "Населённый пункт")

    return fetch_json(
        FORECAST_API_URL,
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": (
                "temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            ),
            "daily": (
                "weather_code,"
                "temperature_2m_max,"
                "temperature_2m_min,"
                "precipitation_probability_max,"
                "precipitation_sum"
            ),
            "forecast_days": 1,
            "timezone": "auto",
        },
        stage="forecast",
        location_name=location_name,
    )


def fetch_json(
    base_url: str,
    params: dict[str, object],
    *,
    stage: str = "request",
    location_name: str = "unknown",
    timeout_seconds: float = WEATHER_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = build_url(base_url, params)

    for attempt in range(1, WEATHER_REQUEST_ATTEMPTS + 1):
        started_at = time.monotonic()

        try:
            raw_body = fetch_response_body(url, timeout_seconds)
        except (OSError, RetryableWeatherRequestError) as error:
            elapsed_seconds = time.monotonic() - started_at
            retrying = attempt < WEATHER_REQUEST_ATTEMPTS

            log_weather_request_failure(
                stage=stage,
                location_name=location_name,
                attempt=attempt,
                elapsed_seconds=elapsed_seconds,
                retrying=retrying,
                error=error,
            )

            if not retrying:
                if is_timeout_error(error):
                    raise WeatherServiceError(
                        "Погодный сервис не ответил вовремя."
                    ) from error

                raise WeatherServiceError(
                    "Погодный сервис временно недоступен."
                ) from error

            time.sleep(WEATHER_REQUEST_RETRY_DELAYS_SECONDS[attempt - 1])
            continue

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise WeatherServiceError(
                "Погодный сервис вернул некорректный ответ."
            ) from error

        if not isinstance(payload, dict):
            raise WeatherServiceError("Погодный сервис вернул некорректный ответ.")

        return payload

    raise RuntimeError("Weather request retry loop ended unexpectedly.")


def fetch_response_body(url: str, timeout_seconds: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "telegram-reminder-bot"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status

            if status_code != 200:
                if status_code is not None and 500 <= status_code < 600:
                    raise RetryableWeatherRequestError(f"HTTP status {status_code}")

                raise WeatherServiceError("Погодный сервис временно недоступен.")

            return response.read()
    except urllib.error.HTTPError as error:
        if 500 <= error.code < 600:
            raise RetryableWeatherRequestError(f"HTTP status {error.code}") from error

        raise WeatherServiceError("Погодный сервис временно недоступен.") from error


def normalize_location_key(location_name: str) -> str:
    return " ".join(location_name.casefold().split())


def is_timeout_error(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return True

    return isinstance(error, urllib.error.URLError) and isinstance(
        error.reason, TimeoutError
    )


def log_weather_request_failure(
    *,
    stage: str,
    location_name: str,
    attempt: int,
    elapsed_seconds: float,
    retrying: bool,
    error: Exception,
) -> None:
    LOGGER.warning(
        (
            "Weather request failed: stage=%s location=%r attempt=%s/%s "
            "duration_seconds=%.2f retrying=%s error=%s"
        ),
        stage,
        location_name,
        attempt,
        WEATHER_REQUEST_ATTEMPTS,
        elapsed_seconds,
        retrying,
        format_weather_request_error(error),
    )


def format_weather_request_error(error: Exception) -> str:
    if isinstance(error, RetryableWeatherRequestError):
        return str(error)

    if isinstance(error, urllib.error.URLError):
        return f"{type(error.reason).__name__}: {error.reason}"

    return type(error).__name__


def build_url(base_url: str, params: dict[str, object]) -> str:
    return f"{base_url}?{urllib.parse.urlencode(params)}"


def format_location_forecast(
    location: dict[str, Any],
    forecast: dict[str, Any],
) -> str:
    current = get_dict(forecast, "current")
    daily = get_dict(forecast, "daily")

    current_temperature = format_temperature(current.get("temperature_2m"))
    max_temperature = format_temperature(first(daily.get("temperature_2m_max")))

    daily_weather_code = first(daily.get("weather_code"))
    daily_weather = format_weather_sentence(daily_weather_code)
    weather_emoji = format_weather_emoji(daily_weather_code)

    precipitation_probability = first(daily.get("precipitation_probability_max"))
    precipitation_sum = first(daily.get("precipitation_sum"))

    return "\n".join(
        [
            f"{weather_emoji} <b>{format_location_name(location)}</b>",
            f"Сейчас {current_temperature}, днём до {max_temperature}. "
            f"{daily_weather}.",
            format_precipitation_line(
                precipitation_probability,
                precipitation_sum,
            ),
        ]
    )


def get_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise WeatherServiceError("Не смог прочитать прогноз погоды.")

    return value


def first(value: object) -> object:
    if isinstance(value, list) and value:
        return value[0]

    return None


def format_location_name(location: dict[str, Any]) -> str:
    name = str(location.get("name") or "Населённый пункт")
    admin1 = normalize_location_part(location.get("admin1"))
    country = normalize_location_part(location.get("country"))

    if admin1 and admin1.casefold() != name.casefold():
        return escape_html(f"{name} · {admin1}")

    if country and country.casefold() != name.casefold():
        return escape_html(f"{name} · {country}")

    return escape_html(name)


def normalize_location_part(value: object) -> str:
    if not value:
        return ""

    return str(value).strip().capitalize()


def escape_html(value: object) -> str:
    return html.escape(str(value), quote=False)


def format_temperature(value: object) -> str:
    if value is None:
        return "—"

    return f"{round(float(value))}°"


def format_weather_code(value: object) -> str:
    if value is None:
        return "погода неизвестна"

    weather_code = int(value)
    return WEATHER_CODE_DESCRIPTIONS.get(weather_code, "погода неизвестна")


def format_weather_sentence(value: object) -> str:
    description = format_weather_code(value)

    if description == "погода неизвестна":
        return "Погода неизвестна"

    return description.capitalize()


def format_weather_emoji(value: object) -> str:
    if value is None:
        return "🌡"

    weather_code = int(value)
    return WEATHER_CODE_EMOJIS.get(weather_code, "🌡")


def format_precipitation_line(
    precipitation_probability: object,
    precipitation_sum: object,
) -> str:
    probability = as_float(precipitation_probability)
    precipitation = as_float(precipitation_sum)

    if is_precipitation_likely(probability, precipitation):
        return "Осадки вероятны."

    if is_precipitation_possible(probability, precipitation):
        return "Осадки возможны."

    return "Осадки маловероятны."


def is_precipitation_likely(
    probability: float | None,
    precipitation: float | None,
) -> bool:
    if probability is not None and probability >= 70:
        return True

    return precipitation is not None and precipitation >= 5


def is_precipitation_possible(
    probability: float | None,
    precipitation: float | None,
) -> bool:
    if probability is not None and probability >= 30:
        return True

    return precipitation is not None and precipitation > 0


def as_float(value: object) -> float | None:
    if value is None:
        return None

    return float(value)


def format_number(value: object) -> str:
    if value is None:
        return "—"

    number = float(value)
    if number.is_integer():
        return str(int(number))

    return f"{number:.1f}"
