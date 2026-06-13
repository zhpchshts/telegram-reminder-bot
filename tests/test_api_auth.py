from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app import api_auth as api_auth_module
from app.api_auth import TMA_INIT_DATA_HEADER, get_tma_init_data
from app.tma_auth import TelegramInitData, TelegramInitDataError


BOT_TOKEN = "123456789:test-token"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/protected")
    def protected_endpoint(
        init_data: TelegramInitData = Depends(get_tma_init_data),
    ) -> dict[str, object]:
        return {
            "auth_date": init_data.auth_date,
            "user": init_data.user,
            "chat": init_data.chat,
            "chat_type": init_data.chat_type,
            "start_param": init_data.start_param,
        }

    return TestClient(app)


def test_tma_auth_dependency_returns_validated_init_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls = []

    def fake_validate_telegram_init_data(
        init_data: str,
        *,
        bot_token: str,
    ) -> TelegramInitData:
        captured_calls.append(
            {
                "init_data": init_data,
                "bot_token": bot_token,
            }
        )
        return TelegramInitData(
            fields={
                "auth_date": "1700000000",
                "user": '{"id":123,"first_name":"Eugene"}',
                "chat": '{"id":-100,"type":"supergroup","title":"Home"}',
                "chat_type": "supergroup",
                "start_param": "chat_-100",
            },
            auth_date=1_700_000_000,
            user={
                "id": 123,
                "first_name": "Eugene",
            },
            chat={
                "id": -100,
                "type": "supergroup",
                "title": "Home",
            },
            chat_type="supergroup",
            start_param="chat_-100",
        )

    monkeypatch.setattr(api_auth_module, "BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(
        api_auth_module,
        "validate_telegram_init_data",
        fake_validate_telegram_init_data,
    )

    response = client.get(
        "/protected",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 200
    assert captured_calls == [
        {
            "init_data": "test-init-data",
            "bot_token": BOT_TOKEN,
        }
    ]
    assert response.json() == {
        "auth_date": 1_700_000_000,
        "user": {
            "id": 123,
            "first_name": "Eugene",
        },
        "chat": {
            "id": -100,
            "type": "supergroup",
            "title": "Home",
        },
        "chat_type": "supergroup",
        "start_param": "chat_-100",
    }


def test_tma_auth_dependency_requires_header(client: TestClient) -> None:
    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data is required.",
    }


def test_tma_auth_dependency_rejects_invalid_init_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_validate_telegram_init_data(
        init_data: str,
        *,
        bot_token: str,
    ) -> TelegramInitData:
        raise TelegramInitDataError("init_data hash is invalid.")

    monkeypatch.setattr(api_auth_module, "BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(
        api_auth_module,
        "validate_telegram_init_data",
        fake_validate_telegram_init_data,
    )

    response = client.get(
        "/protected",
        headers={TMA_INIT_DATA_HEADER: "invalid-init-data"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "init_data hash is invalid.",
    }
