from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp
import pytest

from calm_client import (
    DEFAULT_USER_AGENT,
    CalmAPIError,
    CalmAuthError,
    CalmClient,
    CalmConnectionError,
    CalmNotFoundError,
    CalmRateLimitError,
    Credentials,
    MediaType,
    is_available,
)

if TYPE_CHECKING:
    from tests.conftest import HttpMock


@pytest.mark.asyncio
async def test_login_success(http_mock: HttpMock) -> None:
    http_mock.post(
        "https://oneid.calm.com/oauth/token",
        status=200,
        payload={
            "access_token": "new_token",
            "refresh_token": "refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )

    async with CalmClient() as client:
        creds = await client.login("user@example.com", "password")
        assert creds.token == "new_token"
        assert creds.refresh_token == "refresh_token"


@pytest.mark.asyncio
async def test_login_session_handshake(http_mock: HttpMock) -> None:
    """Test that login performs session handshake and retrieves session_token."""
    # Mock Auth0 token endpoint
    http_mock.post(
        "https://oneid.calm.com/oauth/token",
        status=200,
        payload={
            "access_token": "access_token",
            "refresh_token": "refresh_token",
            "id_token": "id_token",
            "expires_in": 86400,
            "scope": "openid profile email",
        },
    )

    # Mock device registration
    http_mock.post("https://www.calm.com/webapi/authproxy/device", status=200, payload={})

    # Mock v2/me to return session token
    http_mock.get("https://www.calm.com/webapi/authproxy/v2/me", status=200, payload={"token": "new_session_token"})

    async with CalmClient() as client:
        creds = await client.login("user@example.com", "password")

        assert creds.token == "access_token"
        assert creds.session_token == "new_session_token"

        # Verify requests were made
        assert [str(call.url) for call in http_mock.calls] == [
            "https://oneid.calm.com/oauth/token",
            "https://www.calm.com/webapi/authproxy/device",
            "https://www.calm.com/webapi/authproxy/v2/me",
        ]
        assert http_mock.calls[2].headers["Authorization"] == "Bearer access_token"


@pytest.mark.asyncio
async def test_login_failure(http_mock: HttpMock) -> None:
    http_mock.post(
        "https://oneid.calm.com/oauth/token",
        status=401,
        payload={"error": "invalid_grant", "error_description": "Wrong password"},
    )

    async with CalmClient() as client:
        with pytest.raises(CalmAuthError, match="Wrong password"):
            await client.login("user@example.com", "wrong")


@pytest.mark.asyncio
async def test_search(http_mock: HttpMock) -> None:
    http_mock.get(
        "https://www.calm.com/webapi/authproxy/search/v2",
        status=200,
        payload={
            "items": [{"title": "Search Result 1", "type": "program", "program_id": "p1"}],
            "total_item_number": 1,
        },
    )

    async with CalmClient("token") as client:
        results = await client.search("query")
        assert len(results.items) == 1
        assert results.items[0].title == "Search Result 1"


@pytest.mark.asyncio
async def test_ensure_valid_token_refresh(http_mock: HttpMock) -> None:
    # Mock refresh endpoint
    http_mock.post(
        "https://oneid.calm.com/oauth/token",
        status=200,
        payload={"access_token": "refreshed_token", "expires_in": 3600},
    )

    # Mock API endpoint that would be called
    route = http_mock.get(
        "https://www.calm.com/webapi/authproxy/packs/feeds/sleep", status=200, payload={"feed": {"items": []}}
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
async def test_api_401_raises_auth_error(http_mock: HttpMock) -> None:
    http_mock.get("https://www.calm.com/webapi/authproxy/packs/feeds/sleep", status=401, body="Unauthorized")

    async with CalmClient("token") as client:
        with pytest.raises(CalmAuthError):
            await client.get_feed("sleep")


@pytest.mark.asyncio
async def test_get_favorites(http_mock: HttpMock) -> None:
    http_mock.get(
        "https://www.calm.com/webapi/authproxy/packs/class/faves-hydrated",
        status=200,
        payload={
            "pack": {
                "items": [
                    {"title": "Fav 1", "type": "program", "program_id": "p1"},
                    {"title": "Fav 2", "type": "scene", "id": "s1"},
                ]
            }
        },
    )

    async with CalmClient("token") as client:
        favorites = await client.get_favorites()
        assert len(favorites) == 2
        assert favorites[0].title == "Fav 1"
        assert favorites[1].title == "Fav 2"


@pytest.mark.asyncio
async def test_get_feed_with_packs(http_mock: HttpMock) -> None:
    http_mock.get(
        "https://www.calm.com/webapi/authproxy/packs/feeds/sleep",
        status=200,
        payload={"feed": {"id": "sleep", "packs": [{"title": "Featured", "pack_class": "featured", "items": []}]}},
    )

    async with CalmClient("token") as client:
        feed = await client.get_feed("sleep")

    assert feed.items == []
    assert [p.title for p in feed.packs] == ["Featured"]


BASE = "https://www.calm.com/webapi/authproxy"


def test_resolve_image_url() -> None:
    assert CalmClient.resolve_image_url(None) == ""
    assert CalmClient.resolve_image_url("https://assets.calm.com/a.jpeg", 100) == "https://assets.calm.com/a.jpeg"
    ctf = "https://images.ctfassets.net/x/a.jpg"
    assert CalmClient.resolve_image_url(ctf) == ctf
    assert CalmClient.resolve_image_url(ctf, width=100) == f"{ctf}?w=100"
    assert CalmClient.resolve_image_url(ctf, height=50) == f"{ctf}?h=50"
    assert CalmClient.resolve_image_url(f"{ctf}?fm=webp", 100, 50) == f"{ctf}?fm=webp&w=100&h=50"


@pytest.mark.asyncio
async def test_login_network_error(http_mock: HttpMock) -> None:
    http_mock.post("https://oneid.calm.com/oauth/token", exception=aiohttp.ClientConnectionError("down"))
    async with CalmClient() as client:
        with pytest.raises(CalmConnectionError, match="Network error"):
            await client.login("user@example.com", "password")


@pytest.mark.asyncio
async def test_login_failure_non_json(http_mock: HttpMock) -> None:
    http_mock.post("https://oneid.calm.com/oauth/token", status=503, body="maintenance")
    async with CalmClient() as client:
        with pytest.raises(CalmAuthError, match="maintenance"):
            await client.login("user@example.com", "password")


@pytest.mark.asyncio
async def test_login_response_without_access_token(http_mock: HttpMock) -> None:
    http_mock.post("https://oneid.calm.com/oauth/token", status=200, payload={"scope": "x"})
    async with CalmClient() as client:
        with pytest.raises(CalmAuthError, match="did not contain an access_token"):
            await client.login("user@example.com", "password")


@pytest.mark.asyncio
async def test_login_keeps_device_id_and_survives_failed_handshake(http_mock: HttpMock) -> None:
    http_mock.post("https://oneid.calm.com/oauth/token", status=200, payload={"access_token": "a"})
    http_mock.post(f"{BASE}/device", status=500)
    http_mock.get(f"{BASE}/v2/me", status=500)

    async with CalmClient(Credentials(token="", device_id="my-device")) as client:
        creds = await client.login("user@example.com", "password")

    assert creds.token == "a"
    assert creds.device_id == "my-device"
    assert creds.session_token is None


@pytest.mark.asyncio
async def test_login_handshake_without_session_token(http_mock: HttpMock) -> None:
    http_mock.post("https://oneid.calm.com/oauth/token", status=200, payload={"access_token": "a"})
    http_mock.post(f"{BASE}/device", status=200, payload={})
    http_mock.get(f"{BASE}/v2/me", status=200, payload={"user": {}})

    async with CalmClient() as client:
        creds = await client.login("user@example.com", "password")

    assert creds.session_token is None


@pytest.mark.asyncio
async def test_request_passes_explicit_cookies(http_mock: HttpMock) -> None:
    route = http_mock.get(f"{BASE}/v2/me", status=200, payload={})
    async with CalmClient("token") as client:
        await client._request("GET", "v2/me", cookies={"extra": "1"})
    assert route.last.headers["Cookie"] == "calm-user-token=token"


@pytest.mark.asyncio
async def test_api_error_other_than_401(http_mock: HttpMock) -> None:
    http_mock.get(f"{BASE}/packs/feeds/sleep", status=500, body="boom")
    async with CalmClient("token") as client:
        with pytest.raises(CalmAPIError, match="API Error"):
            await client.get_feed("sleep")


@pytest.mark.asyncio
async def test_get_feed_without_feed_wrapper(http_mock: HttpMock) -> None:
    http_mock.get(
        f"{BASE}/packs/feeds/sleep", status=200, payload={"items": [{"id": "1", "title": "T", "type": "program"}]}
    )
    async with CalmClient("token") as client:
        feed = await client.get_feed("sleep")
    assert [i.title for i in feed.items] == ["T"]


@pytest.mark.asyncio
async def test_get_program(http_mock: HttpMock) -> None:
    http_mock.get(
        f"{BASE}/content/programs/p1",
        status=200,
        payload={
            "program": {
                "id": "p1",
                "title": "Rain",
                "guides": [
                    {
                        "id": "g1",
                        "title": "One",
                        "assets": [{"url": "u", "content_type": "audio/mp4", "duration": 5}],
                    }
                ],
            }
        },
    )
    async with CalmClient("token") as client:
        program = await client.get_program("p1")
    assert program.title == "Rain"
    assert program.first_stream_url == "u"


@pytest.mark.asyncio
async def test_search_without_pack_wrapper(http_mock: HttpMock) -> None:
    http_mock.get(f"{BASE}/search/v2", status=200, payload={"items": [{"title": "Rain"}]})
    async with CalmClient("token") as client:
        results = await client.search("rain")
    assert [i.title for i in results.items] == ["Rain"]


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [True, False])
async def test_get_category_feed(http_mock: HttpMock, wrapped: bool) -> None:
    feed = {"id": "sleep", "title": "Sleep", "packs": [{"title": "Featured", "pack_class": "f", "items": []}]}
    http_mock.get(f"{BASE}/packs/feeds/sleep", status=200, payload={"feed": feed} if wrapped else feed)
    async with CalmClient("token") as client:
        result = await client.get_category_feed("sleep")
    assert result.title == "Sleep"
    assert [p.title for p in result.packs] == ["Featured"]


@pytest.mark.asyncio
async def test_get_favorites_without_pack(http_mock: HttpMock) -> None:
    http_mock.get(f"{BASE}/packs/class/faves-hydrated", status=200, payload={})
    async with CalmClient("token") as client:
        assert await client.get_favorites() == []


@pytest.mark.asyncio
async def test_aclose_closes_http_client() -> None:
    client = CalmClient("token")
    await client.aclose()
    assert client._session is None


API = "https://www.calm.com/webapi/authproxy"


@pytest.mark.asyncio
async def test_get_pack(http_mock: HttpMock) -> None:
    http_mock.get(
        f"{API}/packs/class/sleep-stories",
        status=200,
        payload={"pack": {"title": "Sleep Stories", "items": [{"type": "guide", "guide_id": "g"}]}},
    )
    async with CalmClient("token") as client:
        pack = await client.get_pack("sleep-stories")
    assert pack.title == "Sleep Stories"
    assert pack.items[0].guide_id == "g"


def _mock_guide(http_mock: HttpMock, summary: dict[str, Any]) -> None:
    http_mock.get(f"{API}/programs/guides/g2", status=200, payload=summary)
    http_mock.get(
        f"{API}/content/programs/p1",
        status=200,
        payload={
            "program": {
                "id": "p1",
                "title": "Program",
                "guides": [
                    {"id": "g1", "title": "One", "assets": []},
                    {"id": "g2", "title": "Two", "assets": [{"url": "u", "content_type": "audio/mp4"}]},
                ],
            }
        },
    )


@pytest.mark.asyncio
async def test_get_guide_copies_lock_flags(http_mock: HttpMock) -> None:
    _mock_guide(http_mock, {"id": "g2", "program_id": "p1", "unlocked": False, "free": True})
    async with CalmClient("token") as client:
        guide, program = await client.get_guide("g2")
    assert guide.title == "Two"
    assert guide.stream_url == "u"
    assert program.is_free
    assert not program.is_unlocked
    assert is_available(guide, program)


@pytest.mark.asyncio
async def test_get_guide_locked(http_mock: HttpMock) -> None:
    _mock_guide(http_mock, {"id": "g2", "program_id": "p1", "unlocked": False})
    async with CalmClient("token") as client:
        guide, program = await client.get_guide("g2")
    assert not is_available(guide, program)


@pytest.mark.asyncio
async def test_get_guide_not_in_program(http_mock: HttpMock) -> None:
    _mock_guide(http_mock, {"id": "g2", "program_id": "p1"})
    http_mock.get(f"{API}/programs/guides/g9", status=200, payload={"id": "g9", "program_id": "p1"})
    async with CalmClient("token") as client:
        with pytest.raises(CalmNotFoundError, match="g9"):
            await client.get_guide("g9")


@pytest.mark.asyncio
async def test_browse_root() -> None:
    async with CalmClient("token") as client:
        entries = await client.browse()
    assert entries[0].path == "feed/home"
    assert all(entry.media_type is MediaType.FOLDER for entry in entries)


@pytest.mark.asyncio
async def test_browse_feed(http_mock: HttpMock) -> None:
    http_mock.get(
        f"{API}/packs/feeds/sleep",
        status=200,
        payload={
            "feed": {
                "packs": [
                    {"title": "Stories", "pack_class": "stories", "items": [{"type": "guide", "guide_id": "g"}]},
                    {"title": "Promo", "pack_class": "promo", "items": [{"type": "promo"}]},
                    {"title": "", "pack_class": "untitled", "items": [{"type": "guide", "guide_id": "g"}]},
                ],
                "tags": [
                    {"title": "Kids", "feed_id": "kids-sleep"},
                    {"title": "Rain", "pack_class": "rain"},
                    {"title": "Broken"},
                ],
            }
        },
    )
    async with CalmClient("token") as client:
        entries = await client.browse("feed/sleep")
    assert [(e.title, e.path) for e in entries] == [
        ("Stories", "pack/stories"),
        ("Kids", "feed/kids-sleep"),
        ("Rain", "pack/rain"),
    ]


@pytest.mark.asyncio
async def test_browse_pack(http_mock: HttpMock) -> None:
    http_mock.get(
        f"{API}/packs/class/stories", status=200, payload={"pack": {"items": [{"type": "program", "program_id": "p"}]}}
    )
    async with CalmClient("token") as client:
        entries = await client.browse("pack/stories")
    assert entries[0].media_type is MediaType.ALBUM


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["feed", "pack/", "bogus/x"])
async def test_browse_bad_path(path: str) -> None:
    async with CalmClient("token") as client:
        with pytest.raises(ValueError, match="browse path"):
            await client.browse(path)


@pytest.mark.asyncio
async def test_get_playlists(http_mock: HttpMock) -> None:
    http_mock.get(
        f"{API}/content/playlist",
        status=200,
        payload=[
            {
                "id": "pl1",
                "name": "Ease to Sleep",
                "user_id": "u1",
                "items": [{"type": "guide", "guide_id": "g1", "program_id": "p1"}],
                "image": {"url": "http://img/pl.png", "width": 100, "height": 100},
            },
            {"id": "pl2", "name": "Empty", "items": []},
        ],
    )
    async with CalmClient("token") as client:
        playlists = await client.get_playlists()
    assert [p.name for p in playlists] == ["Ease to Sleep", "Empty"]
    assert playlists[0].items[0].guide_id == "g1"
    assert playlists[0].image_url == "http://img/pl.png"
    assert playlists[1].image_url is None


@pytest.mark.asyncio
async def test_fave_guide_uses_guide_path(http_mock: HttpMock) -> None:
    route = http_mock.post(f"{API}/programs/guides/g1/faves", status=200, payload={"fave": {"guide_id": "g1"}})
    delete = http_mock.delete(f"{API}/programs/guides/g1/faves", status=200, payload={})
    async with CalmClient("token") as client:
        await client.add_fave(guide_id="g1")
        await client.remove_fave(guide_id="g1")
    assert route.called and delete.called


@pytest.mark.asyncio
async def test_fave_program_uses_generic_endpoint(http_mock: HttpMock) -> None:
    route = http_mock.post(f"{API}/faves", status=200, payload={})
    async with CalmClient("token") as client:
        await client.add_fave(program_id="N1ilgb7aV")
    assert route.called
    assert route.last.json == {"program_id": "N1ilgb7aV"}


@pytest.mark.asyncio
async def test_fave_requires_exactly_one_id() -> None:
    async with CalmClient("token") as client:
        with pytest.raises(ValueError, match="exactly one"):
            await client.add_fave()
        with pytest.raises(ValueError, match="exactly one"):
            await client.add_fave(guide_id="g", program_id="p")


@pytest.mark.asyncio
async def test_list_narrators(http_mock: HttpMock) -> None:
    http_mock.get(
        f"{API}/search/v2",
        status=200,
        payload={
            "pack": {
                "items": [
                    {"type": "narrator", "narrator_id": "n1", "title": "Tamara Levitt", "content_type": "Narrator"},
                    {"type": "narrator", "narrator_id": "a1", "title": "Alanis", "content_type": "Artist"},
                    {"type": "program", "program_id": "p1", "title": "A meditation"},
                ]
            }
        },
    )
    async with CalmClient("token") as client:
        narrators = await client.list_narrators()
    assert [n.title for n in narrators] == ["Tamara Levitt", "Alanis"]
    assert all(n.media_type is MediaType.FOLDER for n in narrators)
    assert narrators[0].path == "feed/narrator-n1"
    # scoped to the narrators_artists category; empty query returns the starter catalog
    params = http_mock.calls[-1].url.query
    assert params["category"] == "narrators_artists"
    assert params["query"] == ""


@pytest.mark.asyncio
async def test_search_category_and_duration_params(http_mock: HttpMock) -> None:
    route = http_mock.get(f"{API}/search/v2", status=200, payload={"pack": {"items": []}})
    async with CalmClient("token") as client:
        await client.search("rain", category="soundscapes", duration="ten_min")
        p = route.last.url.query
        assert p["query"] == "rain" and p["category"] == "soundscapes" and p["duration"] == "ten_min"
        # omitted filters aren't sent
        await client.search("rain")
        p2 = route.last.url.query
        assert "category" not in p2 and "duration" not in p2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "expected"),
    [({"Retry-After": "7"}, 7.0), ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None), ({}, None)],
)
async def test_429_raises_rate_limit_error(
    http_mock: HttpMock, headers: dict[str, str], expected: float | None
) -> None:
    http_mock.get("https://www.calm.com/webapi/authproxy/packs/feeds/sleep", status=429, headers=headers)
    async with CalmClient(Credentials(token="t")) as client:
        with pytest.raises(CalmRateLimitError) as excinfo:
            await client.get_feed("sleep")
    assert excinfo.value.retry_after == expected
    # still an API error for callers that do not care about the difference
    assert isinstance(excinfo.value, CalmAPIError)


FEED_URL = f"{API}/packs/feeds/sleep"


@pytest.mark.asyncio
async def test_404_raises_not_found(http_mock: HttpMock) -> None:
    http_mock.get(f"{API}/content/programs/gone", status=404, body="Not Found")
    async with CalmClient("token") as client:
        with pytest.raises(CalmNotFoundError, match="HTTP 404") as excinfo:
            await client.get_program("gone")
    assert excinfo.value.status == 404
    # still an API error for callers that do not care about the difference
    assert isinstance(excinfo.value, CalmAPIError)


@pytest.mark.asyncio
async def test_other_http_errors_keep_their_status(http_mock: HttpMock) -> None:
    http_mock.get(FEED_URL, status=503, body="maintenance")
    async with CalmClient("token") as client:
        with pytest.raises(CalmAPIError) as excinfo:
            await client.get_feed("sleep")
    assert excinfo.value.status == 503
    assert not isinstance(excinfo.value, CalmNotFoundError | CalmConnectionError)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        aiohttp.ClientConnectionError("refused"),
        aiohttp.ServerDisconnectedError(),
        aiohttp.ClientPayloadError("truncated"),
        TimeoutError(),
    ],
)
async def test_transport_errors_become_connection_errors(http_mock: HttpMock, error: Exception) -> None:
    http_mock.get(FEED_URL, exception=error)
    async with CalmClient("token") as client:
        with pytest.raises(CalmConnectionError, match="Network error on GET packs/feeds/sleep") as excinfo:
            await client.get_feed("sleep")
    assert excinfo.value.__cause__ is error
    assert excinfo.value.status is None
    assert isinstance(excinfo.value, CalmAPIError)


@pytest.mark.asyncio
async def test_non_json_body_raises_connection_error(http_mock: HttpMock) -> None:
    http_mock.get(FEED_URL, status=200, body="<html>captive portal</html>")
    async with CalmClient("token") as client:
        with pytest.raises(CalmConnectionError, match="Invalid JSON") as excinfo:
            await client.get_feed("sleep")
    assert excinfo.value.status == 200


@pytest.mark.asyncio
async def test_guide_lookup_404_is_not_found(http_mock: HttpMock) -> None:
    http_mock.get(f"{API}/programs/guides/gone", status=404)
    async with CalmClient("token") as client:
        with pytest.raises(CalmNotFoundError):
            await client.get_guide("gone")


@pytest.mark.asyncio
async def test_own_session_sends_default_user_agent(http_mock: HttpMock) -> None:
    route = http_mock.get(FEED_URL, status=200, payload={"feed": {}})
    async with CalmClient("token") as client:
        await client.get_feed("sleep")
        assert client.session.headers["User-Agent"] == DEFAULT_USER_AGENT
    assert route.last.headers["User-Agent"] == DEFAULT_USER_AGENT


@pytest.mark.asyncio
async def test_own_session_uses_callers_user_agent(http_mock: HttpMock) -> None:
    route = http_mock.get(FEED_URL, status=200, payload={"feed": {}})
    async with CalmClient("token", user_agent="MyApp/1.0") as client:
        await client.get_feed("sleep")
        assert client.session.headers["User-Agent"] == "MyApp/1.0"
    assert route.last.headers["User-Agent"] == "MyApp/1.0"


@pytest.mark.asyncio
async def test_shared_session_keeps_its_user_agent_and_stays_open(http_mock: HttpMock) -> None:
    route = http_mock.get(FEED_URL, status=200, payload={"feed": {}})
    async with aiohttp.ClientSession(headers={"User-Agent": "App/2.0"}) as shared:
        async with CalmClient("token", session=shared) as client:
            assert client.session is shared
            await client.get_feed("sleep")
        assert not shared.closed
        assert shared.headers["User-Agent"] == "App/2.0"
    # calm-client adds no User-Agent of its own, so the shared session's is sent
    assert route.last.headers["User-Agent"] == "App/2.0"
    assert route.last.headers["x-calm-platform"] == "web"


@pytest.mark.asyncio
async def test_shared_session_with_explicit_user_agent(http_mock: HttpMock) -> None:
    feed = http_mock.get(FEED_URL, status=200, payload={"feed": {}})
    login = http_mock.post("https://oneid.calm.com/oauth/token", status=200, payload={"access_token": "a"})
    http_mock.post(f"{API}/device", status=200, payload={})
    http_mock.get(f"{API}/v2/me", status=200, payload={"token": "s"})
    async with aiohttp.ClientSession() as shared:
        client = CalmClient(session=shared, user_agent="MusicAssistant/2.0")
        await client.login("user@example.com", "password")
        await client.get_feed("sleep")
        await client.close()
        assert not shared.closed
    assert login.last.headers["User-Agent"] == "MusicAssistant/2.0"
    assert feed.last.headers["User-Agent"] == "MusicAssistant/2.0"
    assert all(call.headers["User-Agent"] == "MusicAssistant/2.0" for call in http_mock.calls)


@pytest.mark.asyncio
async def test_token_refresh_goes_through_the_shared_session(http_mock: HttpMock) -> None:
    import time

    refresh = http_mock.post("https://oneid.calm.com/oauth/token", status=200, payload={"access_token": "fresh"})
    feed = http_mock.get(FEED_URL, status=200, payload={"feed": {}})
    creds = Credentials(token="stale", refresh_token="r", expires_at=time.time() - 10)
    async with aiohttp.ClientSession() as shared:
        async with CalmClient(creds, session=shared, user_agent="MyApp/1.0") as client:
            await client.get_feed("sleep")
        assert not shared.closed
    assert refresh.last.headers["User-Agent"] == "MyApp/1.0"
    assert feed.last.headers["Cookie"] == "calm-user-token=fresh"


@pytest.mark.asyncio
async def test_refresh_network_error_is_not_an_auth_error(http_mock: HttpMock) -> None:
    import time

    http_mock.post("https://oneid.calm.com/oauth/token", exception=aiohttp.ClientConnectionError("down"))
    creds = Credentials(token="stale", refresh_token="r", expires_at=time.time() - 10)
    async with CalmClient(creds) as client:
        with pytest.raises(CalmConnectionError):
            await client.get_feed("sleep")


def test_client_can_be_built_without_a_running_loop() -> None:
    # the session is opened lazily, on the first request inside the event loop
    client = CalmClient("token")
    assert client._session is None


@pytest.mark.asyncio
async def test_close_is_idempotent_and_reopens_on_next_use(http_mock: HttpMock) -> None:
    http_mock.get(FEED_URL, status=200, payload={"feed": {}})
    client = CalmClient("token")
    first = client.session
    await client.close()
    await client.close()
    assert first.closed
    await client.get_feed("sleep")
    assert client.session is not first
    await client.close()


def test_new_options_are_keyword_only() -> None:
    positional: list[Any] = ["token", object()]
    with pytest.raises(TypeError):
        CalmClient(*positional)
