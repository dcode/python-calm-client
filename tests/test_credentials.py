import time
from typing import Any

import httpx
import pytest
from httpx import Response

from calm_client import CalmAuthError
from calm_client.credentials import Credentials

TOKEN_URL = "https://oneid.calm.com/oauth/token"


def test_expires_in_becomes_expires_at() -> None:
    creds = Credentials.model_validate({"access_token": "t", "expires_in": 3600})
    assert creds.expires_at is not None
    assert 3500 < creds.expires_at - time.time() <= 3600
    assert creds.valid
    assert not creds.expired


def test_expires_in_none_is_ignored() -> None:
    assert Credentials.model_validate({"access_token": "t", "expires_in": None}).expires_at is None


def test_expiry_buffer() -> None:
    # within the 60 s refresh buffer counts as expired
    creds = Credentials(token="t", expires_at=time.time() + 30)
    assert creds.expired
    assert not creds.valid


def test_from_token_has_no_expiry_or_refresh() -> None:
    creds = Credentials.from_token("raw")
    assert creds.token == "raw"
    assert creds.valid
    assert not creds.can_refresh


def test_repr_does_not_leak_tokens() -> None:
    creds = Credentials(token="secret-token", refresh_token="secret-refresh", expires_at=time.time() - 10)
    text = repr(creds)
    assert "secret" not in text
    assert text == "<Credentials status=expired refresh=yes>"


@pytest.mark.asyncio
async def test_refresh_without_refresh_token() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(CalmAuthError, match="no refresh_token"):
            await Credentials(token="t").refresh(client)


@pytest.mark.asyncio
async def test_refresh_updates_tokens_and_rotates_refresh_token(respx_mock: Any) -> None:
    respx_mock.post(TOKEN_URL).mock(
        return_value=Response(
            200,
            json={"access_token": "new", "refresh_token": "rotated", "id_token": "id", "expires_in": 60, "scope": "s"},
        )
    )
    creds = Credentials(token="old", refresh_token="ref")
    async with httpx.AsyncClient() as client:
        await creds.refresh(client)
    assert creds.token == "new"
    assert creds.refresh_token == "rotated"
    assert creds.id_token == "id"
    assert creds.scope == "s"
    assert creds.expires_at is not None


@pytest.mark.asyncio
async def test_refresh_network_error(respx_mock: Any) -> None:
    respx_mock.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(CalmAuthError, match="Network error"):
            await Credentials(token="t", refresh_token="r").refresh(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (Response(400, json={"error_description": "Unknown or invalid refresh token."}), "invalid refresh token"),
        (Response(400, json={"error": "invalid_grant"}), "invalid_grant"),
        (Response(502, text="Bad gateway"), "Bad gateway"),
    ],
)
async def test_refresh_failure_messages(respx_mock: Any, response: Response, message: str) -> None:
    respx_mock.post(TOKEN_URL).mock(return_value=response)
    async with httpx.AsyncClient() as client:
        with pytest.raises(CalmAuthError, match=message):
            await Credentials(token="t", refresh_token="r").refresh(client)


@pytest.mark.asyncio
async def test_refresh_response_without_access_token(respx_mock: Any) -> None:
    respx_mock.post(TOKEN_URL).mock(return_value=Response(200, json={}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(CalmAuthError, match="missing access_token"):
            await Credentials(token="t", refresh_token="r").refresh(client)
