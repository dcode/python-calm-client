from typing import Any

import pytest
from httpx import Response

from calm_client import CalmAuthError, CalmClient


@pytest.mark.asyncio
async def test_login_success(respx_mock: Any) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "new_token",
                "refresh_token": "refresh_token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )

    async with CalmClient() as client:
        creds = await client.login("user@example.com", "password")
        assert creds.token == "new_token"
        assert creds.refresh_token == "refresh_token"


@pytest.mark.asyncio
async def test_login_session_handshake(respx_mock: Any) -> None:
    """Test that login performs session handshake and retrieves session_token."""
    # Mock Auth0 token endpoint
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "access_token",
                "refresh_token": "refresh_token",
                "id_token": "id_token",
                "expires_in": 86400,
                "scope": "openid profile email",
            },
        )
    )

    # Mock device registration
    respx_mock.post("https://www.calm.com/webapi/authproxy/device").mock(return_value=Response(200, json={}))

    # Mock v2/me to return session token
    respx_mock.get("https://www.calm.com/webapi/authproxy/v2/me").mock(
        return_value=Response(
            200,
            json={"token": "new_session_token"},
        )
    )

    async with CalmClient() as client:
        creds = await client.login("user@example.com", "password")

        assert creds.token == "access_token"
        assert creds.session_token == "new_session_token"

        # Verify requests were made
        assert respx_mock.calls.call_count == 3
        # calls[0] is oauth/token
        # calls[1] is device
        # calls[2] is v2/me
        assert respx_mock.calls[0].request.url == "https://oneid.calm.com/oauth/token"
        assert respx_mock.calls[1].request.url == "https://www.calm.com/webapi/authproxy/device"
        assert respx_mock.calls[2].request.url == "https://www.calm.com/webapi/authproxy/v2/me"
        assert respx_mock.calls[2].request.headers["Authorization"] == "Bearer access_token"


@pytest.mark.asyncio
async def test_login_failure(respx_mock: Any) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(
        return_value=Response(401, json={"error": "invalid_grant", "error_description": "Wrong password"})
    )

    async with CalmClient() as client:
        with pytest.raises(CalmAuthError, match="Wrong password"):
            await client.login("user@example.com", "wrong")


@pytest.mark.asyncio
async def test_search(respx_mock: Any) -> None:
    respx_mock.get("https://www.calm.com/webapi/authproxy/search/v2").mock(
        return_value=Response(
            200,
            json={
                "items": [{"title": "Search Result 1", "type": "program", "program_id": "p1"}],
                "total_item_number": 1,
            },
        )
    )

    async with CalmClient("token") as client:
        results = await client.search("query")
        assert len(results.items) == 1
        assert results.items[0].title == "Search Result 1"


@pytest.mark.asyncio
async def test_ensure_valid_token_refresh(respx_mock: Any) -> None:
    # Mock refresh endpoint
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(
        return_value=Response(200, json={"access_token": "refreshed_token", "expires_in": 3600})
    )

    # Mock API endpoint that would be called
    route = respx_mock.get("https://www.calm.com/webapi/authproxy/packs/feeds/sleep").mock(
        return_value=Response(200, json={"feed": {"items": []}})
    )

    # Create expired creds
    import time

    from calm_client.credentials import Credentials

    creds = Credentials(token="expired", refresh_token="ref", expires_at=time.time() - 10)

    async with CalmClient(creds) as client:
        # This should trigger refresh
        await client.get_feed("sleep")

        assert client.credentials.token == "refreshed_token"
        assert route.called


@pytest.mark.asyncio
async def test_api_401_raises_auth_error(respx_mock: Any) -> None:
    respx_mock.get("https://www.calm.com/webapi/authproxy/packs/feeds/sleep").mock(
        return_value=Response(401, text="Unauthorized")
    )

    async with CalmClient("token") as client:
        with pytest.raises(CalmAuthError):
            await client.get_feed("sleep")


@pytest.mark.asyncio
async def test_get_favorites(respx_mock: Any) -> None:
    respx_mock.get("https://www.calm.com/webapi/authproxy/packs/class/faves-hydrated").mock(
        return_value=Response(
            200,
            json={
                "pack": {
                    "content_id": "faves",
                    "items": [
                        {"title": "Fav 1", "type": "program", "program_id": "p1", "content_id": "p1"},
                        {"title": "Fav 2", "type": "scene", "id": "s1", "content_id": "s1"},
                    ]
                }
            },
        )
    )

    async with CalmClient("token") as client:
        favorites = await client.get_favorites()
        assert len(favorites) == 1
        assert favorites[0].title == "Fav 1"

