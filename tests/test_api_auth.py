from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app import api_auth as api_auth_module
from app.api_auth import (
    TMA_INIT_DATA_HEADER,
    get_tma_chat,
    get_tma_chat_id,
    get_tma_init_data,
    require_matching_chat_id,
)
from app.tma_auth import TelegramInitData, TelegramInitDataError
from app.tma_launch import create_tma_launch_token

BOT_TOKEN = "123456789:test-token"


@pytest.fixture(autouse=True)
def patch_api_auth_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_auth_module, "BOT_TOKEN", BOT_TOKEN)


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


def make_launch_token(
    *,
    chat_id: int = -100,
    chat_type: str = "supergroup",
    chat_title: str | None = "Home",
) -> str:
    return create_tma_launch_token(
        chat_id=chat_id,
        chat_type=chat_type,
        chat_title=chat_title,
        secret=BOT_TOKEN,
        now=1_700_000_000,
        max_age_seconds=1_000_000_000,
    )


def make_init_data(
    *,
    chat: dict[str, object] | None = None,
    user: dict[str, object] | None = None,
    chat_type: str | None = None,
    start_param: str | None = None,
) -> TelegramInitData:
    return TelegramInitData(
        fields={"auth_date": "1700000000"},
        auth_date=1_700_000_000,
        user=user,
        chat=chat,
        chat_type=chat_type,
        start_param=start_param,
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
            "chat_type": "supergroup",
            "start_param": "signed-token",
        },
        auth_date=1_700_000_000,
        user={
            "id": 123,
            "first_name": "Eugene",
        },
        chat=None,
        chat_type="supergroup",
        start_param="signed-token",
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
        "chat": None,
        "chat_type": "supergroup",
        "start_param": "signed-token",
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


def test_tma_chat_id_dependency_returns_launch_token_chat_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(
            user={
                "id": 123,
                "first_name": "Eugene",
            },
            chat=None,
            chat_type="supergroup",
            start_param=make_launch_token(chat_id=-100, chat_type="supergroup"),
        ),
    )

    response = client.get(
        "/chat-id",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 200
    assert response.json() == {"chat_id": -100}


def test_tma_chat_id_dependency_rejects_missing_start_param(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(
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
            start_param=None,
        ),
    )

    response = client.get(
        "/chat-id",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Telegram init data start_param is required.",
    }


def test_tma_chat_id_dependency_rejects_invalid_launch_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(
            user={
                "id": 123,
                "first_name": "Eugene",
            },
            chat=None,
            chat_type="private",
            start_param="invalid-token",
        ),
    )

    response = client.get(
        "/chat-id",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "TMA launch token is invalid.",
    }


def test_matching_chat_id_dependency_returns_authorized_chat_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_validated_init_data(
        monkeypatch,
        make_init_data(
            chat=None,
            chat_type="group",
            start_param=make_launch_token(
                chat_id=100,
                chat_type="group",
                chat_title="Home",
            ),
        ),
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
        make_init_data(
            chat=None,
            chat_type="group",
            start_param=make_launch_token(
                chat_id=200,
                chat_type="group",
                chat_title="Home",
            ),
        ),
    )

    response = client.get(
        "/api/chats/100/protected",
        headers={TMA_INIT_DATA_HEADER: "test-init-data"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Telegram init data chat_id does not match requested chat_id.",
    }


def test_get_tma_chat_returns_launch_token_chat() -> None:
    init_data = TelegramInitData(
        fields={},
        auth_date=1_700_000_000,
        user={
            "id": 123,
            "first_name": "Eugene",
        },
        chat=None,
        chat_type="private",
        start_param=make_launch_token(
            chat_id=-100,
            chat_type="supergroup",
            chat_title="Home",
        ),
    )

    chat = get_tma_chat(init_data=init_data)

    assert chat == {
        "id": -100,
        "type": "supergroup",
        "title": "Home",
    }
    assert get_tma_chat_id(chat=chat) == -100


def test_get_tma_chat_rejects_missing_start_param() -> None:
    init_data = TelegramInitData(
        fields={},
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
        start_param=None,
    )

    with pytest.raises(HTTPException) as error:
        get_tma_chat(init_data=init_data)

    assert error.value.status_code == 401
    assert error.value.detail == "Telegram init data start_param is required."


def test_get_tma_chat_rejects_invalid_launch_token() -> None:
    init_data = TelegramInitData(
        fields={},
        auth_date=1_700_000_000,
        user={
            "id": 123,
            "first_name": "Eugene",
        },
        chat=None,
        chat_type="private",
        start_param="invalid-token",
    )

    with pytest.raises(HTTPException) as error:
        get_tma_chat(init_data=init_data)

    assert error.value.status_code == 401
    assert error.value.detail == "TMA launch token is invalid."
