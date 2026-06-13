import pytest

from app.tma_launch import (
    TmaLaunchContext,
    TmaLaunchTokenError,
    create_tma_launch_token,
    validate_tma_launch_token,
)

SECRET = "test-secret"


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
    token = create_tma_launch_token(
        chat_id=-100,
        chat_type="supergroup",
        secret=SECRET,
        now=1_700_000_000,
        max_age_seconds=60,
    )
    replacement = "A" if token[-1] != "A" else "B"

    with pytest.raises(TmaLaunchTokenError) as error:
        validate_tma_launch_token(
            token[:-1] + replacement,
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
