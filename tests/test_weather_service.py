from __future__ import annotations

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