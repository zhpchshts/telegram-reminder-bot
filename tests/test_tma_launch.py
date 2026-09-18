import base64
import json
import re
import pytest

from app import tma_launch as tma_launch_module
from app.tma_launch import (
    TmaLaunchContext,
    TmaLaunchTokenError,
    create_tma_launch_token,
    validate_tma_launch_token,
)

SECRET = "test-secret"
# Fixed canonical JSON/HMAC-SHA256/base32 vector, generated without app helpers.
SIGNED_LAUNCH_TOKEN = (
    "PMRHAYLZNRXWCZBCHJ5SEY3IMF2F62LEEI5C2MJQGAWCEY3IMF2F65DJORWGKIR2"
    "EJEG63LFEIWCEY3IMF2F65DZOBSSEORCON2XAZLSM5ZG65LQEIWCEZLYOBUXEZLTL5QX"
    "IIR2GE3TAMBQGAYDANRQPUWCE43JM5XGC5DVOJSSEORCGFGGO3SEONMF6VKOMV3DMMRY"
    "L4ZVA52CHBRU2MTBGZ2WEYKEHF3GIUSNO5NGOYLBLA2GOIT5"
)


def test_tma_launch_token_matches_fixed_signature() -> None:
    assert (
        create_tma_launch_token(
            chat_id=-100,
            chat_type="supergroup",
            chat_title="Home",
            secret=SECRET,
            now=1_700_000_000,
            max_age_seconds=60,
        )
        == SIGNED_LAUNCH_TOKEN
    )
    assert validate_tma_launch_token(
        SIGNED_LAUNCH_TOKEN, secret=SECRET, now=1_700_000_030
    ) == TmaLaunchContext(chat_id=-100, chat_type="supergroup", chat_title="Home")


def test_tma_launch_token_rejects_another_secret() -> None:
    token = create_tma_launch_token(
        chat_id=-100,
        chat_type="supergroup",
        secret=SECRET,
        now=1_700_000_000,
        max_age_seconds=60,
    )

    with pytest.raises(TmaLaunchTokenError, match="TMA launch token is invalid"):
        validate_tma_launch_token(
            token, secret="another-test-secret", now=1_700_000_030
        )


def test_create_and_validate_tma_launch_token() -> None:
    token = create_tma_launch_token(
        chat_id=-100,
        chat_type="supergroup",
        chat_title="Home",
        secret=SECRET,
        now=1_700_000_000,
        max_age_seconds=60,
    )

    context = validate_tma_launch_token(
        token,
        secret=SECRET,
        now=1_700_000_030,
    )

    assert context == TmaLaunchContext(
        chat_id=-100,
        chat_type="supergroup",
        chat_title="Home",
    )


def test_create_tma_launch_token_uses_safe_base32_alphabet() -> None:
    token = create_tma_launch_token(
        chat_id=-100,
        chat_type="supergroup",
        chat_title="Home",
        secret=SECRET,
        now=1_700_000_000,
        max_age_seconds=60,
    )

    assert re.fullmatch(r"[A-Z2-7]+", token) is not None
    assert "_" not in token
    assert "-" not in token


def test_validate_tma_launch_token_rejects_base64url_token() -> None:
    with pytest.raises(TmaLaunchTokenError) as error:
        validate_tma_launch_token(
            "eyJwYXlsb2FkIjp7fQ",
            secret=SECRET,
            now=1_700_000_030,
        )

    assert str(error.value) == "TMA launch token is invalid."


def test_create_tma_launch_token_without_chat_title() -> None:
    token = create_tma_launch_token(
        chat_id=123,
        chat_type="private",
        secret=SECRET,
        now=1_700_000_000,
        max_age_seconds=60,
    )

    context = validate_tma_launch_token(
        token,
        secret=SECRET,
        now=1_700_000_030,
    )

    assert context == TmaLaunchContext(
        chat_id=123,
        chat_type="private",
        chat_title=None,
    )


def test_validate_tma_launch_token_rejects_tampered_token() -> None:
    envelope = json.loads(
        base64.b32decode(SIGNED_LAUNCH_TOKEN + "=" * (-len(SIGNED_LAUNCH_TOKEN) % 8))
    )
    # Keep valid JSON and the original signature, changing only the signed chat.
    envelope["payload"]["chat_id"] = -200
    tampered_token = (
        base64.b32encode(
            json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
        )
        .decode()
        .rstrip("=")
    )

    with pytest.raises(TmaLaunchTokenError) as error:
        validate_tma_launch_token(
            tampered_token,
            secret=SECRET,
            now=1_700_000_030,
        )

    assert str(error.value) == "TMA launch token is invalid."


def test_validate_tma_launch_token_rejects_expired_token() -> None:
    token = create_tma_launch_token(
        chat_id=-100,
        chat_type="supergroup",
        secret=SECRET,
        now=1_700_000_000,
        max_age_seconds=60,
    )

    with pytest.raises(TmaLaunchTokenError) as error:
        validate_tma_launch_token(
            token,
            secret=SECRET,
            now=1_700_000_061,
        )

    assert str(error.value) == "TMA launch token is expired."


def test_create_tma_launch_token_rejects_invalid_chat_id() -> None:
    with pytest.raises(TmaLaunchTokenError) as error:
        create_tma_launch_token(
            chat_id=True,
            chat_type="private",
            secret=SECRET,
        )

    assert str(error.value) == "chat_id must be an integer."


def test_tma_launch_token_default_lifetime_is_30_days() -> None:
    now = 1_700_000_000
    token = create_tma_launch_token(
        chat_id=123,
        chat_type="private",
        secret=SECRET,
        now=now,
    )

    validate_tma_launch_token(token, secret=SECRET, now=now + 30 * 24 * 60 * 60)

    with pytest.raises(TmaLaunchTokenError) as error:
        validate_tma_launch_token(
            token,
            secret=SECRET,
            now=now + 30 * 24 * 60 * 60 + 1,
        )

    assert str(error.value) == "TMA launch token is expired."


@pytest.mark.parametrize("chat_title", ["Я" * 128, "😀" * 128])
def test_create_tma_launch_token_drops_oversized_display_title(
    chat_title: str,
) -> None:
    token = create_tma_launch_token(
        chat_id=-100,
        chat_type="supergroup",
        chat_title=chat_title,
        secret=SECRET,
        now=1_700_000_000,
        max_age_seconds=60,
    )

    context = validate_tma_launch_token(
        token,
        secret=SECRET,
        now=1_700_000_030,
    )

    assert len(token) <= tma_launch_module.MAX_TMA_LAUNCH_TOKEN_LENGTH
    assert context == TmaLaunchContext(
        chat_id=-100,
        chat_type="supergroup",
        chat_title=None,
    )


def test_validate_tma_launch_token_accepts_previous_user_bound_token() -> None:
    payload = {
        "chat_id": -100,
        "chat_type": "supergroup",
        "expires_at": 1_700_000_060,
        "user_id": 123,
    }
    token = tma_launch_module._base32_encode(
        json.dumps(
            {
                "payload": payload,
                "signature": tma_launch_module._sign_payload(
                    payload,
                    secret=SECRET,
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )

    context = validate_tma_launch_token(
        token,
        secret=SECRET,
        now=1_700_000_030,
    )

    assert context == TmaLaunchContext(
        chat_id=-100,
        chat_type="supergroup",
        chat_title=None,
    )
