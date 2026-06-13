from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app import api_auth as api_auth_module
from app.api_auth import (
    TMA_INIT_DATA_HEADER,
    get_tma_chat_id,
    get_tma_init_data,
    require_matching_chat_id,
)
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

    @app.get("/chat-id")
    def chat_id_endpoint(
        chat_id: int = Depends(get_tma_chat_id),
    ) -> dict[str, int]:
        return {"chat_id": chat_id}

    @app.get("/api/chats/{chat_id}/protected")
    def chat_protected_endpoint(
        authorized_chat_id: int = Depends(require_matching_chat_id),
    ) -> dict[str, int]:
        return {"chat_id": authorized_chat_id}

    return TestClient(app)


def make_init_data(
    *,
    chat: dict[str, object] | None,
) -> TelegramInitData:
    return TelegramInitData(
        fields={"auth_date": "1700000000"},
        auth_date=1_700_000_000,
        chat=chat,
    )


def patch_validated_init_data(
    monkeypatch: pytest.MonkeyPatch,
    validated_init_data: TelegramInitData,
) -> list[dict[str, str]]:
    captured_calls: list[dict[str, str]] = []

    def fake_validate_telegram_init_data(
        raw_init_data: str,
        *,
        bot_token: str,
    ) -> TelegramInitData:
        captured_calls.append(
            {
                "init_data": raw_init_data,
                "bot_token": bot_token,
            }
        )
        return validated_init_data

    monkeypatch.setattr(api_auth_module, "BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(
        api_auth_module,
        "validate_telegram_init_data",
        fake_validate_telegram_init_data,
    )

    return captured_calls


def test_tma_auth_dependency_returns_validated_init_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_data = TelegramInitData(
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
    captured_calls = patch_validated_init_data(monkeypatch, init_data)

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


def test_tma_chat_id_dependency_returns_chat_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(chat={"id": -100, "type": "supergroup"}),
    )

    response = client.get(
        "/chat-id",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 200
    assert response.json() == {"chat_id": -100}


def test_tma_chat_id_dependency_rejects_missing_chat(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(monkeypatch, make_init_data(chat=None))

    response = client.get(
        "/chat-id",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data chat is required.",
    }


def test_tma_chat_id_dependency_rejects_non_int_chat_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(chat={"id": "-100", "type": "supergroup"}),
    )

    response = client.get(
        "/chat-id",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data chat.id must be an integer.",
    }


def test_matching_chat_id_dependency_returns_authorized_chat_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(chat={"id": 100, "type": "group"}),
    )

    response = client.get(
        "/api/chats/100/protected",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 200
    assert response.json() == {"chat_id": 100}


def test_matching_chat_id_dependency_rejects_different_chat_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(chat={"id": 200, "type": "group"}),
    )

    response = client.get(
        "/api/chats/100/protected",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Telegram init data chat_id does not match requested chat_id.",
    }
