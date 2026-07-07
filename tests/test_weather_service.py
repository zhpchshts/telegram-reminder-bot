from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from app import weather_service


class FakeResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_json_retries_after_timeout(monkeypatch) -> None:
    timeouts = []
    retry_delays = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)

        if len(timeouts) == 1:
            raise TimeoutError

        return FakeResponse({"ok": True})

    monkeypatch.setattr(
        weather_service.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        weather_service.time,
        "sleep",
        retry_delays.append,
    )

    payload = weather_service.fetch_json(
        "https://weather.example.test/forecast",
        {"city": "Yekaterinburg"},
        stage="forecast",
        location_name="Екатеринбург",
    )

    assert payload == {"ok": True}
    assert timeouts == [
        weather_service.WEATHER_REQUEST_TIMEOUT_SECONDS,
        weather_service.WEATHER_REQUEST_TIMEOUT_SECONDS,
    ]
    assert retry_delays == [1]


def test_fetch_json_returns_timeout_error_after_all_attempts(monkeypatch) -> None:
    timeouts = []
    retry_delays = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(
        weather_service.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        weather_service.time,
        "sleep",
        retry_delays.append,
    )

    with pytest.raises(
        weather_service.WeatherServiceError,
        match="Погодный сервис не ответил вовремя.",
    ):
        weather_service.fetch_json(
            "https://weather.example.test/forecast",
            {"city": "Yekaterinburg"},
            stage="forecast",
            location_name="Екатеринбург",
        )

    assert timeouts == [
        weather_service.WEATHER_REQUEST_TIMEOUT_SECONDS,
        weather_service.WEATHER_REQUEST_TIMEOUT_SECONDS,
        weather_service.WEATHER_REQUEST_TIMEOUT_SECONDS,
    ]
    assert retry_delays == [1, 2]


def test_find_location_returns_cached_location_without_network(monkeypatch) -> None:
    cached_location = {
        "name": "Екатеринбург",
        "admin1": "Свердловская область",
        "country": "Россия",
        "latitude": 56.8519,
        "longitude": 60.6122,
    }
    requested_keys = []

    def fake_get_cached_weather_location(location_key: str):
        requested_keys.append(location_key)
        return cached_location

    def fail_fetch_json(*args, **kwargs):
        raise AssertionError("Network request must not be made for cached location.")

    monkeypatch.setattr(
        weather_service,
        "get_cached_weather_location",
        fake_get_cached_weather_location,
    )
    monkeypatch.setattr(
        weather_service,
        "fetch_json",
        fail_fetch_json,
    )

    location = weather_service.find_location("  Екатеринбург  ")

    assert location == cached_location
    assert requested_keys == ["екатеринбург"]


def test_find_location_saves_new_location_to_cache(monkeypatch) -> None:
    found_location = {
        "name": "Хургада",
        "admin1": "Red Sea",
        "country": "Egypt",
        "latitude": 27.2579,
        "longitude": 33.8116,
    }
    saved_locations = []
    fetch_calls = []

    def fake_fetch_json(*args, **kwargs):
        fetch_calls.append((args, kwargs))
        return {"results": [found_location]}

    def fake_save_cached_weather_location(location_key: str, location: dict) -> None:
        saved_locations.append((location_key, location))

    monkeypatch.setattr(
        weather_service,
        "get_cached_weather_location",
        lambda location_key: None,
    )
    monkeypatch.setattr(
        weather_service,
        "fetch_json",
        fake_fetch_json,
    )
    monkeypatch.setattr(
        weather_service,
        "save_cached_weather_location",
        fake_save_cached_weather_location,
    )

    location = weather_service.find_location("Хургада")

    assert location == found_location
    assert saved_locations == [("хургада", found_location)]
    assert fetch_calls[0][0][0] == weather_service.GEOCODING_API_URL
    assert fetch_calls[0][1]["stage"] == "geocoding"
    assert fetch_calls[0][1]["location_name"] == "Хургада"


@pytest.mark.parametrize(
    ("current_time", "expected_names"),
    [
        (datetime(2026, 7, 7, 2, 59), ("ночью", "утром")),
        (datetime(2026, 7, 7, 3, 0), ("утром", "днём")),
        (datetime(2026, 7, 7, 8, 59), ("утром", "днём")),
        (datetime(2026, 7, 7, 9, 0), ("днём", "вечером")),
        (datetime(2026, 7, 7, 14, 59), ("днём", "вечером")),
        (datetime(2026, 7, 7, 15, 0), ("вечером", "ночью")),
        (datetime(2026, 7, 7, 20, 59), ("вечером", "ночью")),
        (datetime(2026, 7, 7, 21, 0), ("ночью", "утром")),
    ],
)
def test_get_precipitation_periods_selects_upcoming_periods(
    current_time: datetime,
    expected_names: tuple[str, str],
) -> None:
    periods = weather_service.get_precipitation_periods(current_time)

    assert tuple(period[0] for period in periods) == expected_names


def test_get_precipitation_periods_moves_night_to_next_day_after_21() -> None:
    periods = weather_service.get_precipitation_periods(datetime(2026, 7, 7, 21, 15))

    assert periods == (
        (
            "ночью",
            datetime(2026, 7, 8, 0, 0),
            datetime(2026, 7, 8, 6, 0),
        ),
        (
            "утром",
            datetime(2026, 7, 8, 6, 0),
            datetime(2026, 7, 8, 12, 0),
        ),
    )


def test_format_precipitation_line_uses_maximum_probability_in_each_period() -> None:
    result = weather_service.format_precipitation_line(
        {
            "time": [
                "2026-07-07T15:00",
                "2026-07-07T17:00",
                "2026-07-07T18:00",
                "2026-07-07T19:00",
                "2026-07-07T23:00",
                "2026-07-08T00:00",
                "2026-07-08T02:00",
                "2026-07-08T05:00",
            ],
            "precipitation_probability": [100, 100, 30, 70, 55, 20, 90, 80],
        },
        datetime(2026, 7, 7, 15, 15),
    )

    assert result == "Осадки: вечером — до 70%, ночью — до 90%."


def test_format_precipitation_line_ignores_passed_hours() -> None:
    result = weather_service.format_precipitation_line(
        {
            "time": [
                "2026-07-07T00:00",
                "2026-07-07T01:00",
                "2026-07-07T02:00",
                "2026-07-07T03:00",
                "2026-07-07T04:00",
                "2026-07-07T05:00",
                "2026-07-07T06:00",
                "2026-07-07T07:00",
            ],
            "precipitation_probability": [100, 100, 100, 20, 70, 50, 10, 40],
        },
        datetime(2026, 7, 7, 2, 30),
    )

    assert result == "Осадки: ночью — до 70%, утром — до 40%."


def test_format_location_forecast_includes_two_precipitation_periods() -> None:
    result = weather_service.format_location_forecast(
        {
            "name": "Екатеринбург",
            "admin1": "Свердловская область",
        },
        {
            "current": {
                "temperature_2m": 18.4,
                "time": "2026-07-07T09:30",
            },
            "daily": {
                "temperature_2m_max": [24.2],
                "weather_code": [3],
            },
            "hourly": {
                "time": [
                    "2026-07-07T12:00",
                    "2026-07-07T13:00",
                    "2026-07-07T18:00",
                    "2026-07-07T19:00",
                ],
                "precipitation_probability": [20, 80, 30, 60],
            },
        },
    )

    assert result == (
        "☁️ <b>Екатеринбург · Свердловская область</b>\n"
        "Сейчас 18°, днём до 24°. Пасмурно.\n"
        "Осадки: днём — до 80%, вечером — до 60%."
    )


def test_fetch_forecast_requests_hourly_probability_for_two_days(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_json(
        base_url: str,
        params: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        captured["base_url"] = base_url
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(weather_service, "fetch_json", fake_fetch_json)

    result = weather_service.fetch_forecast(
        {
            "name": "Екатеринбург",
            "latitude": 56.84,
            "longitude": 60.61,
        }
    )

    assert result == {"ok": True}

    params = captured["params"]
    assert isinstance(params, dict)
    assert params["hourly"] == "precipitation_probability"
    assert params["forecast_days"] == 2
    assert params["timezone"] == "auto"


def test_build_weather_report_uses_neutral_header(monkeypatch) -> None:
    monkeypatch.setattr(
        weather_service,
        "find_location",
        lambda location_name, *, request_attempts: {"name": location_name},
    )
    monkeypatch.setattr(
        weather_service,
        "fetch_forecast",
        lambda location, *, request_attempts: {},
    )
    monkeypatch.setattr(
        weather_service,
        "format_location_forecast",
        lambda location, forecast, *, target_time_utc: "Готовый прогноз",
    )

    result = weather_service.build_weather_report("Екатеринбург")

    assert result.startswith("<b>Прогноз погоды</b>\n\nГотовый прогноз")
    assert "на сегодня" not in result


def test_format_location_forecast_uses_target_time_for_periods() -> None:
    result = weather_service.format_location_forecast(
        {
            "name": "Екатеринбург",
            "admin1": "Свердловская область",
        },
        {
            "timezone": "Asia/Yekaterinburg",
            "current": {
                "temperature_2m": 18.4,
                "time": "2026-07-07T08:56",
            },
            "daily": {
                "time": ["2026-07-07"],
                "temperature_2m_max": [24.2],
                "weather_code": [3],
            },
            "hourly": {
                "time": [
                    "2026-07-07T09:00",
                    "2026-07-07T12:00",
                    "2026-07-07T13:00",
                    "2026-07-07T18:00",
                    "2026-07-07T19:00",
                ],
                "precipitation_probability": [15, 20, 80, 30, 60],
            },
        },
        target_time_utc=datetime(2026, 7, 7, 4, 0, tzinfo=timezone.utc),
    )

    assert result.endswith("Осадки: днём — до 80%, вечером — до 60%.")


def test_get_daily_forecast_index_selects_target_date() -> None:
    result = weather_service.get_daily_forecast_index(
        {
            "time": [
                "2026-07-07",
                "2026-07-08",
            ],
        },
        datetime(2026, 7, 8, 0, 0),
    )

    assert result == 1


def test_format_location_forecast_uses_tomorrow_daily_data_after_21() -> None:
    result = weather_service.format_location_forecast(
        {
            "name": "Екатеринбург",
            "admin1": "Свердловская область",
        },
        {
            "timezone": "Asia/Yekaterinburg",
            "current": {
                "temperature_2m": 18.4,
                "time": "2026-07-07T20:56",
            },
            "daily": {
                "time": [
                    "2026-07-07",
                    "2026-07-08",
                ],
                "temperature_2m_max": [24.2, 20.4],
                "weather_code": [3, 0],
            },
            "hourly": {
                "time": [
                    "2026-07-08T00:00",
                    "2026-07-08T02:00",
                    "2026-07-08T05:00",
                    "2026-07-08T06:00",
                    "2026-07-08T07:00",
                    "2026-07-08T11:00",
                ],
                "precipitation_probability": [20, 70, 50, 10, 40, 30],
            },
        },
        target_time_utc=datetime(2026, 7, 7, 16, 0, tzinfo=timezone.utc),
    )

    assert "Сейчас 18°, завтра днём до 20°. Ясно." in result
    assert result.endswith("Осадки: ночью — до 70%, утром — до 40%.")
