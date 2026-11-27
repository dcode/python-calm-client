from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import aiohttp
import pytest

from calm_client import CalmAPIError, CalmAuthError, CalmConnectionError
from calm_client.credentials import Credentials

if TYPE_CHECKING:
    from tests.conftest import HttpMock


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
    async with aiohttp.ClientSession() as session:
        with pytest.raises(CalmAuthError, match="no refresh_token"):
            await Credentials(token="t").refresh(session)


@pytest.mark.asyncio
async def test_refresh_updates_tokens_and_rotates_refresh_token(http_mock: HttpMock) -> None:
    route = http_mock.post(
        TOKEN_URL,
        status=200,
        payload={"access_token": "new", "refresh_token": "rotated", "id_token": "id", "expires_in": 60, "scope": "s"},
    )
    creds = Credentials(token="old", refresh_token="ref")
    async with aiohttp.ClientSession() as session:
        await creds.refresh(session)
    assert creds.token == "new"
    assert creds.refresh_token == "rotated"
    assert creds.id_token == "id"
    assert creds.scope == "s"
    assert creds.expires_at is not None
    assert route.last.json == {
        "grant_type": "refresh_token",
        "client_id": route.last.json["client_id"],
        "refresh_token": "ref",
    }
    # without a user agent of its own, the request keeps the session's
    assert "User-Agent" not in route.last.headers


@pytest.mark.asyncio
async def test_refresh_sends_user_agent_when_given(http_mock: HttpMock) -> None:
    route = http_mock.post(TOKEN_URL, status=200, payload={"access_token": "new"})
    async with aiohttp.ClientSession() as session:
        await Credentials(token="old", refresh_token="ref").refresh(session, user_agent="MyApp/1.0")
    assert route.last.headers["User-Agent"] == "MyApp/1.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [aiohttp.ClientConnectionError("down"), TimeoutError()])
async def test_refresh_network_error(http_mock: HttpMock, error: Exception) -> None:
    http_mock.post(TOKEN_URL, exception=error)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(CalmConnectionError, match="Network error") as excinfo:
            await Credentials(token="t", refresh_token="r").refresh(session)
    # a network failure is not a rejected token, so callers should not log in again
    assert not isinstance(excinfo.value, CalmAuthError)
    assert isinstance(excinfo.value, CalmAPIError)
    assert excinfo.value.status is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            {"status": 400, "payload": {"error_description": "Unknown or invalid refresh token."}},
            "invalid refresh token",
        ),
        ({"status": 400, "payload": {"error": "invalid_grant"}}, "invalid_grant"),
        ({"status": 502, "body": "Bad gateway"}, "Bad gateway"),
    ],
)
async def test_refresh_failure_messages(http_mock: HttpMock, response: dict[str, Any], message: str) -> None:
    http_mock.post(TOKEN_URL, **response)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(CalmAuthError, match=message):
            await Credentials(token="t", refresh_token="r").refresh(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"payload": {}}, {"body": "not json"}, {"payload": ["a list"]}])
async def test_refresh_response_without_access_token(http_mock: HttpMock, response: dict[str, Any]) -> None:
    http_mock.post(TOKEN_URL, status=200, **response)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(CalmAuthError, match="missing access_token"):
            await Credentials(token="t", refresh_token="r").refresh(session)
