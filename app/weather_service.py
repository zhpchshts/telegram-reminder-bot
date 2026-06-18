from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

MAX_WEATHER_LOCATIONS = 5
OPEN_METEO_ATTRIBUTION = "Данные: Open-Meteo"

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


class WeatherServiceError(Exception):
    """Raised when weather data cannot be loaded or parsed."""


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
            f"weather_locations must contain no more than "
            f"{MAX_WEATHER_LOCATIONS} locations."
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
            location_blocks.append(f"⚠️ {location_name}\n{error}")

    return "\n\n".join(
        [
            "Погода на сегодня",
            *location_blocks,
            OPEN_METEO_ATTRIBUTION,
        ]
    )


def find_location(location_name: str) -> dict[str, Any]:
    payload = fetch_json(
        GEOCODING_API_URL,
        {
            "name": location_name,
            "count": 1,
            "language": "ru",
            "format": "json",
        },
    )

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise WeatherServiceError("Не нашёл населённый пункт.")

    location = results[0]
    if not isinstance(location, dict):
        raise WeatherServiceError("Не смог прочитать данные населённого пункта.")

    if location.get("latitude") is None or location.get("longitude") is None:
        raise WeatherServiceError("Не нашёл координаты населённого пункта.")

    return location


def fetch_forecast(location: dict[str, Any]) -> dict[str, Any]:
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
    )


def fetch_json(
    base_url: str,
    params: dict[str, object],
    *,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    url = build_url(base_url, params)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "telegram-reminder-bot"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise WeatherServiceError("Погодный сервис временно недоступен.")

            raw_body = response.read()
    except TimeoutError as error:
        raise WeatherServiceError("Погодный сервис не ответил вовремя.") from error
    except urllib.error.URLError as error:
        raise WeatherServiceError("Погодный сервис временно недоступен.") from error

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise WeatherServiceError(
            "Погодный сервис вернул некорректный ответ."
        ) from error

    if not isinstance(payload, dict):
        raise WeatherServiceError("Погодный сервис вернул некорректный ответ.")

    return payload


def build_url(base_url: str, params: dict[str, object]) -> str:
    return f"{base_url}?{urllib.parse.urlencode(params)}"


def format_location_forecast(
    location: dict[str, Any],
    forecast: dict[str, Any],
) -> str:
    current = get_dict(forecast, "current")
    daily = get_dict(forecast, "daily")

    current_temperature = format_temperature(current.get("temperature_2m"))
    apparent_temperature = format_temperature(current.get("apparent_temperature"))
    current_weather = format_weather_code(current.get("weather_code"))

    min_temperature = format_temperature(first(daily.get("temperature_2m_min")))
    max_temperature = format_temperature(first(daily.get("temperature_2m_max")))
    daily_weather = format_weather_code(first(daily.get("weather_code")))

    precipitation_probability = first(daily.get("precipitation_probability_max"))
    precipitation_sum = first(daily.get("precipitation_sum"))
    precipitation_line = format_precipitation_line(
        precipitation_probability,
        precipitation_sum,
    )

    wind_speed = format_number(current.get("wind_speed_10m"))

    return "\n".join(
        [
            f"🌤 {format_location_name(location)}",
            f"Сейчас: {current_temperature}, ощущается как "
            f"{apparent_temperature}, {current_weather}",
            f"Днём: {min_temperature}…{max_temperature}, {daily_weather}",
            precipitation_line,
            f"Ветер: {wind_speed} м/с",
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
    admin1 = location.get("admin1")
    country = location.get("country")

    if admin1:
        return f"{name}, {admin1}"

    if country:
        return f"{name}, {country}"

    return name


def format_temperature(value: object) -> str:
    if value is None:
        return "—"

    return f"{round(float(value))}°"


def format_weather_code(value: object) -> str:
    if value is None:
        return "погода неизвестна"

    weather_code = int(value)
    return WEATHER_CODE_DESCRIPTIONS.get(weather_code, "погода неизвестна")


def format_precipitation_line(
    precipitation_probability: object,
    precipitation_sum: object,
) -> str:
    precipitation_sum_text = format_number(precipitation_sum)

    if precipitation_probability is None:
        return f"Осадки: {precipitation_sum_text} мм"

    probability_text = f"{round(float(precipitation_probability))}%"
    return f"Осадки: {probability_text}, {precipitation_sum_text} мм"


def format_number(value: object) -> str:
    if value is None:
        return "—"

    number = float(value)
    if number.is_integer():
        return str(int(number))

    return f"{number:.1f}"
