from typing import Any

import httpx
import pytest
from httpx import Response

from calm_client import CalmAPIError, CalmAuthError, CalmClient, Credentials, MediaType, is_available


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
                    "items": [
                        {"title": "Fav 1", "type": "program", "program_id": "p1"},
                        {"title": "Fav 2", "type": "scene", "id": "s1"},
                    ]
                }
            },
        )
    )

    async with CalmClient("token") as client:
        favorites = await client.get_favorites()
        assert len(favorites) == 2
        assert favorites[0].title == "Fav 1"
        assert favorites[1].title == "Fav 2"


@pytest.mark.asyncio
async def test_get_feed_with_packs(respx_mock: Any) -> None:
    respx_mock.get("https://www.calm.com/webapi/authproxy/packs/feeds/sleep").mock(
        return_value=Response(
            200,
            json={"feed": {"id": "sleep", "packs": [{"title": "Featured", "pack_class": "featured", "items": []}]}},
        )
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
async def test_login_network_error(respx_mock: Any) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(side_effect=httpx.ConnectError("down"))
    async with CalmClient() as client:
        with pytest.raises(CalmAuthError, match="Network error"):
            await client.login("user@example.com", "password")


@pytest.mark.asyncio
async def test_login_failure_non_json(respx_mock: Any) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(return_value=Response(503, text="maintenance"))
    async with CalmClient() as client:
        with pytest.raises(CalmAuthError, match="maintenance"):
            await client.login("user@example.com", "password")


@pytest.mark.asyncio
async def test_login_response_without_access_token(respx_mock: Any) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(return_value=Response(200, json={"scope": "x"}))
    async with CalmClient() as client:
        with pytest.raises(CalmAuthError, match="did not contain an access_token"):
            await client.login("user@example.com", "password")


@pytest.mark.asyncio
async def test_login_keeps_device_id_and_survives_failed_handshake(respx_mock: Any) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(return_value=Response(200, json={"access_token": "a"}))
    respx_mock.post(f"{BASE}/device").mock(return_value=Response(500))
    respx_mock.get(f"{BASE}/v2/me").mock(return_value=Response(500))

    async with CalmClient(Credentials(token="", device_id="my-device")) as client:
        creds = await client.login("user@example.com", "password")

    assert creds.token == "a"
    assert creds.device_id == "my-device"
    assert creds.session_token is None


@pytest.mark.asyncio
async def test_login_handshake_without_session_token(respx_mock: Any) -> None:
    respx_mock.post("https://oneid.calm.com/oauth/token").mock(return_value=Response(200, json={"access_token": "a"}))
    respx_mock.post(f"{BASE}/device").mock(return_value=Response(200, json={}))
    respx_mock.get(f"{BASE}/v2/me").mock(return_value=Response(200, json={"user": {}}))

    async with CalmClient() as client:
        creds = await client.login("user@example.com", "password")

    assert creds.session_token is None


@pytest.mark.asyncio
async def test_request_passes_explicit_cookies(respx_mock: Any) -> None:
    route = respx_mock.get(f"{BASE}/v2/me").mock(return_value=Response(200, json={}))
    async with CalmClient("token") as client:
        # httpx deprecates per-request cookies; the auth Cookie header is still sent
        with pytest.warns(DeprecationWarning):
            await client._request("GET", "v2/me", cookies={"extra": "1"})
    assert route.calls.last.request.headers["cookie"] == "calm-user-token=token"


@pytest.mark.asyncio
async def test_api_error_other_than_401(respx_mock: Any) -> None:
    respx_mock.get(f"{BASE}/packs/feeds/sleep").mock(return_value=Response(500, text="boom"))
    async with CalmClient("token") as client:
        with pytest.raises(CalmAPIError, match="API Error"):
            await client.get_feed("sleep")


@pytest.mark.asyncio
async def test_get_feed_without_feed_wrapper(respx_mock: Any) -> None:
    respx_mock.get(f"{BASE}/packs/feeds/sleep").mock(
        return_value=Response(200, json={"items": [{"id": "1", "title": "T", "type": "program"}]})
    )
    async with CalmClient("token") as client:
        feed = await client.get_feed("sleep")
    assert [i.title for i in feed.items] == ["T"]


@pytest.mark.asyncio
async def test_get_program(respx_mock: Any) -> None:
    respx_mock.get(f"{BASE}/content/programs/p1").mock(
        return_value=Response(
            200,
            json={
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
    )
    async with CalmClient("token") as client:
        program = await client.get_program("p1")
    assert program.title == "Rain"
    assert program.first_stream_url == "u"


@pytest.mark.asyncio
async def test_search_without_pack_wrapper(respx_mock: Any) -> None:
    respx_mock.get(f"{BASE}/search/v2").mock(return_value=Response(200, json={"items": [{"title": "Rain"}]}))
    async with CalmClient("token") as client:
        results = await client.search("rain")
    assert [i.title for i in results.items] == ["Rain"]


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [True, False])
async def test_get_category_feed(respx_mock: Any, wrapped: bool) -> None:
    feed = {"id": "sleep", "title": "Sleep", "packs": [{"title": "Featured", "pack_class": "f", "items": []}]}
    respx_mock.get(f"{BASE}/packs/feeds/sleep").mock(
        return_value=Response(200, json={"feed": feed} if wrapped else feed)
    )
    async with CalmClient("token") as client:
        result = await client.get_category_feed("sleep")
    assert result.title == "Sleep"
    assert [p.title for p in result.packs] == ["Featured"]


@pytest.mark.asyncio
async def test_get_favorites_without_pack(respx_mock: Any) -> None:
    respx_mock.get(f"{BASE}/packs/class/faves-hydrated").mock(return_value=Response(200, json={}))
    async with CalmClient("token") as client:
        assert await client.get_favorites() == []


@pytest.mark.asyncio
async def test_aclose_closes_http_client() -> None:
    client = CalmClient("token")
    await client.aclose()
    assert client._client.is_closed


API = "https://www.calm.com/webapi/authproxy"


@pytest.mark.asyncio
async def test_get_pack(respx_mock: Any) -> None:
    respx_mock.get(f"{API}/packs/class/sleep-stories").mock(
        return_value=Response(
            200, json={"pack": {"title": "Sleep Stories", "items": [{"type": "guide", "guide_id": "g"}]}}
        )
    )
    async with CalmClient("token") as client:
        pack = await client.get_pack("sleep-stories")
    assert pack.title == "Sleep Stories"
    assert pack.items[0].guide_id == "g"


def _mock_guide(respx_mock: Any, summary: dict[str, Any]) -> None:
    respx_mock.get(f"{API}/programs/guides/g2").mock(return_value=Response(200, json=summary))
    respx_mock.get(f"{API}/content/programs/p1").mock(
        return_value=Response(
            200,
            json={
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
    )


@pytest.mark.asyncio
async def test_get_guide_copies_lock_flags(respx_mock: Any) -> None:
    _mock_guide(respx_mock, {"id": "g2", "program_id": "p1", "unlocked": False, "free": True})
    async with CalmClient("token") as client:
        guide, program = await client.get_guide("g2")
    assert guide.title == "Two"
    assert guide.stream_url == "u"
    assert program.is_free
    assert not program.is_unlocked
    assert is_available(guide, program)


@pytest.mark.asyncio
async def test_get_guide_locked(respx_mock: Any) -> None:
    _mock_guide(respx_mock, {"id": "g2", "program_id": "p1", "unlocked": False})
    async with CalmClient("token") as client:
        guide, program = await client.get_guide("g2")
    assert not is_available(guide, program)


@pytest.mark.asyncio
async def test_get_guide_not_in_program(respx_mock: Any) -> None:
    _mock_guide(respx_mock, {"id": "g2", "program_id": "p1"})
    respx_mock.get(f"{API}/programs/guides/g9").mock(return_value=Response(200, json={"id": "g9", "program_id": "p1"}))
    async with CalmClient("token") as client:
        with pytest.raises(CalmAPIError, match="g9"):
            await client.get_guide("g9")


@pytest.mark.asyncio
async def test_browse_root() -> None:
    async with CalmClient("token") as client:
        entries = await client.browse()
    assert entries[0].path == "feed/home"
    assert all(entry.media_type is MediaType.FOLDER for entry in entries)


@pytest.mark.asyncio
async def test_browse_feed(respx_mock: Any) -> None:
    respx_mock.get(f"{API}/packs/feeds/sleep").mock(
        return_value=Response(
            200,
            json={
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
    )
    async with CalmClient("token") as client:
        entries = await client.browse("feed/sleep")
    assert [(e.title, e.path) for e in entries] == [
        ("Stories", "pack/stories"),
        ("Kids", "feed/kids-sleep"),
        ("Rain", "pack/rain"),
    ]


@pytest.mark.asyncio
async def test_browse_pack(respx_mock: Any) -> None:
    respx_mock.get(f"{API}/packs/class/stories").mock(
        return_value=Response(200, json={"pack": {"items": [{"type": "program", "program_id": "p"}]}})
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
async def test_get_playlists(respx_mock: Any) -> None:
    respx_mock.get(f"{API}/content/playlist").mock(
        return_value=Response(
            200,
            json=[
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
    )
    async with CalmClient("token") as client:
        playlists = await client.get_playlists()
    assert [p.name for p in playlists] == ["Ease to Sleep", "Empty"]
    assert playlists[0].items[0].guide_id == "g1"
    assert playlists[0].image_url == "http://img/pl.png"
    assert playlists[1].image_url is None


@pytest.mark.asyncio
async def test_fave_guide_uses_guide_path(respx_mock: Any) -> None:
    route = respx_mock.post(f"{API}/programs/guides/g1/faves").mock(
        return_value=Response(200, json={"fave": {"guide_id": "g1"}})
    )
    delete = respx_mock.delete(f"{API}/programs/guides/g1/faves").mock(return_value=Response(200, json={}))
    async with CalmClient("token") as client:
        await client.add_fave(guide_id="g1")
        await client.remove_fave(guide_id="g1")
    assert route.called and delete.called


@pytest.mark.asyncio
async def test_fave_program_uses_generic_endpoint(respx_mock: Any) -> None:
    route = respx_mock.post(f"{API}/faves").mock(return_value=Response(200, json={}))
    async with CalmClient("token") as client:
        await client.add_fave(program_id="N1ilgb7aV")
    assert route.called
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {"program_id": "N1ilgb7aV"}


@pytest.mark.asyncio
async def test_fave_requires_exactly_one_id() -> None:
    async with CalmClient("token") as client:
        with pytest.raises(ValueError, match="exactly one"):
            await client.add_fave()
        with pytest.raises(ValueError, match="exactly one"):
            await client.add_fave(guide_id="g", program_id="p")


@pytest.mark.asyncio
async def test_list_narrators(respx_mock: Any) -> None:
    respx_mock.get(f"{API}/search/v2").mock(
        return_value=Response(
            200,
            json={
                "pack": {
                    "items": [
                        {"type": "narrator", "narrator_id": "n1", "title": "Tamara Levitt", "content_type": "Narrator"},
                        {"type": "narrator", "narrator_id": "a1", "title": "Alanis", "content_type": "Artist"},
                        {"type": "program", "program_id": "p1", "title": "A meditation"},
                    ]
                }
            },
        )
    )
    async with CalmClient("token") as client:
        narrators = await client.list_narrators()
    assert [n.title for n in narrators] == ["Tamara Levitt", "Alanis"]
    assert all(n.media_type is MediaType.FOLDER for n in narrators)
    assert narrators[0].path == "feed/narrator-n1"
    # scoped to the narrators_artists category; empty query returns the starter catalog
    params = respx_mock.calls.last.request.url.params
    assert params["category"] == "narrators_artists"
    assert params["query"] == ""


@pytest.mark.asyncio
async def test_search_category_and_duration_params(respx_mock: Any) -> None:
    route = respx_mock.get(f"{API}/search/v2").mock(return_value=Response(200, json={"pack": {"items": []}}))
    async with CalmClient("token") as client:
        await client.search("rain", category="soundscapes", duration="ten_min")
        p = route.calls.last.request.url.params
        assert p["query"] == "rain" and p["category"] == "soundscapes" and p["duration"] == "ten_min"
        # omitted filters aren't sent
        await client.search("rain")
        p2 = route.calls.last.request.url.params
        assert "category" not in p2 and "duration" not in p2
