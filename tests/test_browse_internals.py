"""Tests for browse TUI behaviour not reached by the key-driven tests in test_browse.py.

Each test drives one app session through several related code paths, since starting a
Textual app is the expensive part.
"""

import io
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Response
from PIL import Image
from textual.widgets import Input, Label, ListView, ProgressBar, Static

from calm_client import browse
from calm_client.browse import BrowseApp, CatalogCard, NowPlayingBar, TrackItem, _resize_image, run_browse
from calm_client.client import CalmClient
from calm_client.models import Asset, FeedResponse, Guide, ImageAsset, Pack, PackItem, Program


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def _program(*guides: Guide) -> Program:
    return Program(id="p1", title="Rain", guides=list(guides))


def _guide(guide_id: str, url: str | None = "u", duration: float = 125) -> Guide:
    assets = [Asset(url=url, content_type="audio/mp4", duration=duration)] if url else []
    return Guide(id=guide_id, title=f"Track {guide_id}", assets=assets)


ITEM = PackItem(
    title="Rain Story",
    program_id="p1",
    item_type="program",
    narrator_name="Narrator",
    image=ImageAsset(url="http://img/item.png"),
)


@pytest.fixture
def client() -> MagicMock:
    mock = MagicMock(spec=CalmClient)
    mock.aclose = AsyncMock()
    mock.get_category_feed = AsyncMock()
    mock.get_favorites = AsyncMock(return_value=[])
    mock.search = AsyncMock()
    mock.get_program = AsyncMock()
    mock.get_pack = AsyncMock(return_value=Pack())
    mock.get_playlists = AsyncMock(return_value=[])
    mock.list_narrators = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def player() -> Generator[MagicMock, None, None]:
    with patch("calm_client.player.CalmPlayer") as cls:
        instance = cls.return_value
        instance.position = 30.0
        instance.duration = 120.0
        instance.is_paused = False
        instance.is_playing = True
        yield instance


# ---------------------------------------------------------------------------
# Helpers that need no running app
# ---------------------------------------------------------------------------


def test_resize_image() -> None:
    assert _resize_image(_png(), 2, 2) is not None
    assert _resize_image(b"not an image") is None
    with patch.object(browse, "_ART_AVAILABLE", False):
        assert _resize_image(_png()) is None


def test_now_playing_bar_format() -> None:
    assert NowPlayingBar._fmt(0) == "0:00"
    assert NowPlayingBar._fmt(-3) == "0:00"
    assert NowPlayingBar._fmt(125.9) == "2:05"


def test_run_browse_runs_app(client: MagicMock) -> None:
    with patch("calm_client.browse.BrowseApp") as app_cls:
        run_browse(client)
    app_cls.assert_called_once_with(client)
    app_cls.return_value.run.assert_called_once_with()


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_widgets_render(client: MagicMock) -> None:
    app = BrowseApp(client)
    async with app.run_test() as pilot:
        bar = app.query_one("#now-playing-bar", NowPlayingBar)
        bar.track_title, bar.program_title, bar.narrator = "Track", "Program", "Narrator"
        bar.position, bar.duration, bar.paused = 30.0, 120.0, True
        rendered = bar.render()
        assert "⏸" in rendered
        assert "Program" in rendered and "Narrator" in rendered
        assert "0:30 / 2:00" in rendered

        # cards: art replaces the emoji, enter and click select, other keys don't
        card = CatalogCard(title="A card title that is long", subtitle="sub", emoji="🌙", item=ITEM)
        await app.query_one("#catalog-grid").mount(card)
        await pilot.pause()
        card.set_art("ART")
        assert card._art_renderable == "ART"
        with patch.object(card, "post_message") as post:
            card.on_key(MagicMock(key="x"))
            post.assert_not_called()
            card.on_key(MagicMock(key="enter"))
            card.on_click()
            assert post.call_count == 2

        # art arriving after the card left the DOM is ignored
        await card.remove()
        card._render_card()

        # set_art on a card that isn't mounted only stores the renderable
        detached = CatalogCard(title="t", subtitle="", emoji="x")
        detached.set_art("ART")
        assert detached._art_renderable == "ART"

        # track entries show duration when known
        with_duration = TrackItem(_guide("g1", duration=125), 0, is_current=True)
        without_assets = TrackItem(_guide("g2", url=None), 1)
        await app.query_one("#track-list", ListView).extend([with_duration, without_assets])
        await pilot.pause()
        assert "2:05" in str(with_duration.query_one(Label).render())
        assert "▶" in str(with_duration.query_one(Label).render())


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_play_track_paths(client: MagicMock, player: MagicMock) -> None:
    app = BrowseApp(client)
    async with app.run_test() as pilot:
        # nothing loaded: track actions are no-ops
        app._play_track(0)
        app.action_next_track()
        app.action_prev_track()
        app.action_toggle_pause()
        app._on_track_end()
        assert app._player is None

        app._current_program = _program(_guide("g1"), _guide("g2", url=None))
        app._current_item = ITEM
        with patch.object(app, "notify") as notify:
            app._play_track(5)  # out of range
            assert app._player is None

            app._play_track(1)  # no stream URL
            notify.assert_called_with("No stream URL available", severity="error")

            with patch("calm_client.player.CalmPlayer", side_effect=RuntimeError("no mpv")):
                app._play_track(0)
            notify.assert_called_with("no mpv", severity="error")

            app._play_track(0)
        await pilot.pause()
        player.play.assert_called_with("u")
        bar = app.query_one("#now-playing-bar", NowPlayingBar)
        assert bar.narrator == "Narrator"
        assert app._player_mode == "bar"

        # pause updates the bar
        player.is_paused = True
        app.action_toggle_pause()
        assert bar.paused is True

        # progress updates reach the bar and the visible views
        app._update_player_ui()
        assert bar.position == 30.0
        app._show_player_expanded()
        app._update_player_ui()
        assert app.query_one("#expanded-progress", ProgressBar).total == 120.0
        assert "0:30 / 2:00" in str(app.query_one("#expanded-timer", Label).render())
        app._show_player_maximized()
        player.duration = 0.0
        app._update_player_ui()
        assert app.query_one("#max-progress", ProgressBar).total == 100

        # last track ended: playback stops
        app._current_track_index = 1
        with patch.object(app, "call_from_thread", side_effect=lambda f, *a: f(*a)):
            app._on_track_end()
        assert app._player is None
        assert app._player_mode == "hidden"

        # stopping again without a player is harmless; so are UI updates
        app._stop_playback()
        app._update_player_ui()
        app._update_expanded_content()
        app._update_maximized_content()
        app._refresh_track_lists()


@pytest.mark.asyncio
async def test_player_modes_and_back(client: MagicMock, player: MagicMock) -> None:
    app = BrowseApp(client)
    async with app.run_test() as pilot:
        app._current_program = _program(_guide("g1"), _guide("g2"))
        app._current_item = ITEM
        app._play_track(0)
        await pilot.pause()

        app.on_now_playing_bar_click()
        assert app._player_mode == "expanded"
        assert "Narrator" in str(app.query_one("#expanded-narrator", Label).render())
        app.on_now_playing_bar_click()  # only expands from the bar
        assert app._player_mode == "expanded"

        app.action_maximize_player()
        assert app._player_mode == "maximized"
        assert "Narrator" in str(app.query_one("#max-narrator", Label).render())
        app.action_maximize_player()
        assert app._player_mode == "expanded"
        app.action_maximize_player()

        await app.action_back()
        assert app._player_mode == "expanded"
        await app.action_back()
        assert app._player_mode == "bar"

        # quitting stops and shuts the player down, then closes the client
        await app.action_quit()
    player.shutdown.assert_called()
    client.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_play_selected_item_paths(client: MagicMock, player: MagicMock) -> None:
    app = BrowseApp(client)
    async with app.run_test():
        with patch.object(app, "notify") as notify, patch.object(app, "_fetch_player_art") as fetch_art:

            async def play(item: PackItem | None) -> None:
                app._current_item = item
                app._play_selected_item()
                await app.workers.wait_for_complete()

            await play(None)
            notify.assert_called_with("No item selected", severity="warning")

            await play(PackItem(title="No id"))
            notify.assert_called_with("'No id' has no audio to play", severity="warning")

            client.get_program.side_effect = RuntimeError("offline")
            await play(ITEM)
            notify.assert_called_with("Failed: offline", severity="error")

            client.get_program.side_effect = None
            client.get_program.return_value = _program()
            await play(ITEM)
            notify.assert_called_with("No audio tracks found", severity="warning")

            client.get_program.return_value = _program(_guide("g1"))
            await play(ITEM)
            fetch_art.assert_called_once_with("http://img/item.png")
            assert app._current_track_index == 0
            player.play.assert_called_with("u")


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigation_paths(client: MagicMock, player: MagicMock) -> None:
    pack = Pack(
        title="Sleep Stories",
        pack_class="stories",
        items=[PackItem(title="No art"), ITEM],
    )
    client.get_category_feed.return_value = FeedResponse(title="Sleep", packs=[pack])
    client.get_favorites.return_value = [ITEM]

    app = BrowseApp(client)
    async with app.run_test() as pilot:
        with (
            patch.object(app, "_fetch_card_art") as card_art,
            patch.object(app, "_fetch_header_art") as header_art,
            patch.object(app, "_play_selected_item") as play_item,
        ):
            # a category loads once, then comes from the cache
            app._load_category("sleep", "Sleep")
            await app.workers.wait_for_complete()
            app._load_category("sleep", "Sleep")
            await app.workers.wait_for_complete()
            client.get_category_feed.assert_awaited_once_with("sleep")
            card_art.assert_called_with(app.query(CatalogCard).first(), "http://img/item.png")

            # favorites fetch art for items that have it
            app._load_all_favorites()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert any(call.args[1] == "http://img/item.png" for call in card_art.call_args_list)

            # play on a focused pack card drills in; on an item card it plays
            pack_card = CatalogCard(title="p", subtitle="", emoji="x", pack=pack)
            item_card = CatalogCard(title="i", subtitle="", emoji="x", item=ITEM)
            await app.query_one("#catalog-grid").mount(pack_card, item_card)
            await pilot.pause()
            item_card.focus()
            await pilot.pause()
            app.action_play_item()
            play_item.assert_called_once()

            pack_card.focus()
            await pilot.pause()
            app.action_play_item()
            assert app._view == "tracks"
            assert "Narrator" in str(app.query_one("#track-narrator", Label).render())
            header_art.assert_called_once()

            # in the track list, play the highlighted entry
            await pilot.pause()
            track_list = app.query_one("#track-list", ListView)
            track_list.focus()
            track_list.index = 1
            await pilot.pause()
            app.action_play_item()
            assert app._current_item == ITEM
            assert play_item.call_count == 2

            # back from the track list returns to the grid
            await app.action_back()
            assert app._view == "grid"

            # selecting a track entry in a list plays it
            app._current_program = _program(_guide("g1"))
            with patch.object(app, "_play_track") as play_track:
                event = MagicMock(spec=ListView.Selected)
                event.item = TrackItem(_guide("g1"), 0)
                await app.on_list_view_selected(event)
                play_track.assert_called_once_with(0)

            # empty searches do nothing; the legacy search entry shows the input
            app._perform_search("   ")
            await app.workers.wait_for_complete()
            client.search.assert_not_awaited()
            app._show_search()
            assert app.query_one("#search-input").display


@pytest.mark.asyncio
async def test_category_load_error(client: MagicMock) -> None:
    client.get_category_feed.side_effect = RuntimeError("offline")
    app = BrowseApp(client)
    async with app.run_test():
        app._load_category("music", "Music")
        await app.workers.wait_for_complete()
        assert "Error: offline" in str(app.query_one("#catalog-title", Static).render())


# ---------------------------------------------------------------------------
# Album art
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_album_art(client: MagicMock, respx_mock: Any) -> None:
    route = respx_mock.get("http://img/ok.png").mock(return_value=Response(200, content=_png()))
    respx_mock.get("http://img/missing.png").mock(return_value=Response(404))

    app = BrowseApp(client)
    async with app.run_test() as pilot:
        # fetched once, then served from the cache
        assert await app._get_art("http://img/ok.png", 4, 4) is not None
        assert await app._get_art("http://img/ok.png", 4, 4) is not None
        assert route.call_count == 1
        assert await app._get_art("http://img/missing.png") is None

        card = CatalogCard(title="t", subtitle="", emoji="x")
        await app.query_one("#catalog-grid").mount(card)
        header = app.query_one("#track-art", Static)
        with patch.object(app, "_get_art", AsyncMock(return_value="PIXELS")):
            app._fetch_card_art(card, "http://img/ok.png")
            app._fetch_header_art(header, "http://img/ok.png")
            app._fetch_player_art("http://img/ok.png")
            await app.workers.wait_for_complete()
        await pilot.pause()
        assert card._art_renderable == "PIXELS"

        # no art: nothing is updated
        with patch.object(app, "_get_art", AsyncMock(return_value=None)):
            other = CatalogCard(title="t", subtitle="", emoji="x")
            app._fetch_card_art(other, "http://img/missing.png")
            app._fetch_header_art(header, "http://img/missing.png")
            app._fetch_player_art("http://img/missing.png")
            await app.workers.wait_for_complete()
        assert other._art_renderable is None


def _track_titles(app: BrowseApp) -> list[str]:
    return [str(item.query_one(Label).render()) for item in app.query_one("#track-list", ListView).query("ListItem")]


@pytest.mark.asyncio
async def test_pack_loads_beyond_feed_preview(client: MagicMock, player: MagicMock) -> None:
    def _story(n: int) -> PackItem:
        return PackItem(title=f"Story {n}", item_type="guide", guide_id=f"g{n}", program_id="p")

    preview = Pack(title="Fiction", pack_class="fiction", has_more=True, items=[_story(1)])
    full = Pack(pack_class="fiction", items=[_story(i) for i in range(1, 13)])
    complete = Pack(title="Naps", pack_class="naps", items=[PackItem(title="Nap", item_type="guide", guide_id="n1")])
    client.get_category_feed.return_value = FeedResponse(title="Sleep", packs=[preview, complete])
    client.get_pack.return_value = full

    app = BrowseApp(client)
    async with app.run_test() as pilot:
        with patch.object(app, "_fetch_header_art"), patch.object(app, "_fetch_card_art"):
            app._load_category("sleep", "Sleep")
            await app.workers.wait_for_complete()
            subtitles = [card.card_subtitle for card in app.query(CatalogCard)]
            assert subtitles == ["1+ items", "1 items"]

            # the preview shows at once, then the full pack replaces it
            app._drill_into_pack(preview)
            await app.workers.wait_for_complete()
            await pilot.pause()
            client.get_pack.assert_awaited_once_with("fiction")
            assert len(_track_titles(app)) == 12
            assert app._current_pack is full
            assert full.title == "Fiction"

            # reopening uses the cached full pack; a complete pack is never fetched
            await pilot.press("escape")
            app._drill_into_pack(preview)
            app._drill_into_pack(complete)
            await app.workers.wait_for_complete()
            client.get_pack.assert_awaited_once()


@pytest.mark.asyncio
async def test_pack_full_load_failures(client: MagicMock, player: MagicMock) -> None:
    preview = Pack(
        title="Fiction",
        pack_class="fiction",
        has_more=True,
        items=[PackItem(title="Story 1", item_type="guide", guide_id="g1", program_id="p")],
    )
    app = BrowseApp(client)
    async with app.run_test() as pilot:
        with patch.object(app, "_fetch_header_art"), patch.object(app, "notify") as notify:
            # an error keeps the preview and says so
            client.get_pack.side_effect = RuntimeError("offline")
            app._drill_into_pack(preview)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "offline" in notify.call_args.args[0]
            assert app._current_pack is preview

            # an empty response keeps the preview too
            client.get_pack.side_effect = None
            client.get_pack.return_value = Pack()
            app._drill_into_pack(preview)
            await app.workers.wait_for_complete()
            assert app._current_pack is preview
            assert "fiction" not in app._pack_cache

            # a pack that's no longer open is cached but not shown
            client.get_pack.return_value = Pack(items=[PackItem(title="A"), PackItem(title="B")])
            app._drill_into_pack(preview)
            app._current_pack = None
            await app.workers.wait_for_complete()
            assert "fiction" in app._pack_cache
            assert app._current_pack is None


def test_category_icons_line_up() -> None:
    from rich.cells import cell_len

    from calm_client.browse import CategoryItem

    for slug, emoji, name in browse.CATEGORIES:
        label = next(iter(CategoryItem(slug, emoji, name).compose()))
        assert isinstance(label, Label)
        text = str(label.render())
        assert cell_len(text) - cell_len(name) == 5, slug
    narrow = next(iter(CategoryItem("x", "◎", "X").compose()))
    assert str(narrow.render()) == " ◎   X"


@pytest.mark.asyncio
async def test_home_feed_special_packs(client: MagicMock, player: MagicMock) -> None:
    nav = Pack(
        pack_class="quick-nav",
        content_description="Navigation",
        items=[
            PackItem.model_validate({"type": "feed", "feed_id": "soundscape", "title": "Soundscapes"}),
            PackItem.model_validate({"type": "pack", "pack_class": "rain", "title": "Rain"}),
        ],
    )
    daily = Pack(
        pack_class="todays-daily-calm",
        content_description="Today's Daily Calm",
        items=[PackItem.model_validate({"type": "guide", "guide_id": "g2", "program_id": "p1", "title": "Daily Calm"})],
    )
    client.get_category_feed.return_value = FeedResponse(
        title="Home",
        packs=[
            nav,
            Pack(title="Favorites", pack_class="faves", evaluation_type="client"),
            Pack(title="My Collections", pack_class="faves-collections", evaluation_type="client"),
            Pack(title="Recently Played", pack_class="recently-completed", evaluation_type="client"),
            daily,
        ],
    )
    client.get_program.return_value = _program(_guide("g1"), _guide("g2"))

    app = BrowseApp(client)
    async with app.run_test() as pilot:
        with (
            patch.object(app, "_fetch_card_art"),
            patch.object(app, "_fetch_header_art"),
            patch.object(app, "_load_all_favorites") as favorites,
            patch.object(app, "_play_track") as play_track,
        ):
            app._load_category("home", "Home")
            await app.workers.wait_for_complete()
            cards = {card.card_title: card for card in app.query(CatalogCard)}
            # untitled packs take their description; recently-played (no endpoint) stays hidden.
            # favorites first, then collections, as in the apps
            assert list(cards) == ["Favorites", "My Collections", "Navigation", "Today's Daily Calm"]
            assert cards["Favorites"].card_subtitle == "Your favorites"
            assert cards["My Collections"].card_subtitle == "Your playlists"

            # the favorites card loads favorites, like the `f` key
            faves_pack = cards["Favorites"].card_pack
            assert faves_pack is not None
            app._drill_into_pack(faves_pack)
            favorites.assert_called_once()

            # the collections card loads playlists
            with patch.object(app, "_load_collections") as collections:
                collections_pack = cards["My Collections"].card_pack
                assert collections_pack is not None
                app._drill_into_pack(collections_pack)
                collections.assert_called_once()

            # a guide entry plays that guide, not the program's first
            app._open_item(daily.items[0])
            await app.workers.wait_for_complete()
            play_track.assert_called_once_with(1)

            with patch.object(app, "_load_category") as load_category, patch.object(app, "_drill_into_pack") as drill:
                # navigation entries open their feed or pack, from the list or the play key
                app._show_pack(nav)
                await pilot.pause()
                track_list = app.query_one("#track-list", ListView)
                track_list.focus()
                track_list.index = 0
                await pilot.press("enter")
                load_category.assert_called_once_with("soundscape", "Soundscapes")
                track_list.index = 1
                app.action_play_item()
                assert drill.call_args.args[0].pack_class == "rain"
                assert drill.call_args.args[0].has_more


@pytest.mark.asyncio
async def test_collections_load_and_hydrate(client: MagicMock, player: MagicMock) -> None:
    from calm_client.models import Playlist, PlaylistItem

    client.get_playlists.return_value = [
        Playlist(
            id="pl1",
            name="Ease to Sleep",
            image=ImageAsset(url="http://img/pl.png"),
            items=[PlaylistItem(guide_id="g1", program_id="p1"), PlaylistItem(guide_id="g2", program_id="p1")],
        ),
        Playlist(id="pl2", name="Empty", items=[]),
    ]
    client.get_guide.side_effect = lambda gid: (_guide(gid), _program(_guide("g1"), _guide("g2")))

    app = BrowseApp(client)
    async with app.run_test() as pilot:
        with patch.object(app, "_fetch_card_art"), patch.object(app, "_fetch_header_art"):
            # the My Collections card lists the playlists
            app._load_collections()
            await app.workers.wait_for_complete()
            titles = [c.card_title for c in app.query(CatalogCard)]
            assert titles == ["Ease to Sleep", "Empty"]

            # opening a playlist shows its items, hydrated with real titles
            pack = next(c for c in app.query(CatalogCard) if c.card_title == "Ease to Sleep").card_pack
            assert pack is not None and pack.pack_class.startswith("playlist:")
            app._drill_into_pack(pack)
            await app.workers.wait_for_complete()
            await pilot.pause()
            rows = [str(i.query_one(Label).render()) for i in app.query_one("#track-list", ListView).query("ListItem")]
            assert any("Track g1" in r for r in rows)
            assert client.get_guide.await_count == 2

            # reopening uses the guide cache (no refetch)
            app._drill_into_pack(pack)
            await app.workers.wait_for_complete()
            assert client.get_guide.await_count == 2


def test_card_wraps_long_title_without_stray_newline() -> None:
    from calm_client.browse import CatalogCard

    card = CatalogCard(title="Sound Therapy for Sleep", subtitle="13 items", emoji="≡")
    lines = browse._wrap(card.card_title, 18, max_lines=2)
    assert 1 <= len(lines) <= 2
    assert all(len(line) <= 18 for line in lines)
    # a very long title is ellipsized on the last line
    long = browse._wrap("A" * 80, 18, max_lines=2)
    assert len(long) == 2
    assert long[-1].endswith("…")


@pytest.mark.asyncio
async def test_resources_and_other_non_content_rows_are_hidden(client: MagicMock, player: MagicMock) -> None:
    feed = FeedResponse(
        title="For Work",
        packs=[
            Pack(
                title="Meditations",
                pack_class="m",
                items=[PackItem.model_validate({"type": "guide", "guide_id": "g"})],
            ),
            Pack(title="Resources", pack_class="work-resources", items=[PackItem.model_validate({"type": "url"})]),
        ],
    )
    client.get_category_feed.return_value = feed
    app = BrowseApp(client)
    async with app.run_test():
        with patch.object(app, "_fetch_card_art"):
            app._load_category("collection-calm-for-work", "For Work")
            await app.workers.wait_for_complete()
            titles = [c.card_title for c in app.query(CatalogCard)]
    assert titles == ["Meditations"]


@pytest.mark.asyncio
async def test_open_narrator_item_loads_its_feed(client: MagicMock, player: MagicMock) -> None:
    narrator = PackItem.model_validate({"type": "narrator", "narrator_id": "VkYG-ZSmX", "title": "Tamara Levitt"})
    app = BrowseApp(client)
    async with app.run_test():
        with patch.object(app, "_load_category") as load_category:
            app._open_item(narrator)
    load_category.assert_called_once_with("narrator-VkYG-ZSmX", "Tamara Levitt")


def test_breathe_removed_from_categories() -> None:
    slugs = [slug for slug, _, _ in browse.CATEGORIES]
    assert "breathe" not in slugs
    assert "collection-calm-for-work" in slugs
    assert "collection-calm-for-kids" in slugs


@pytest.mark.asyncio
async def test_narrators_sidebar_list_filter_and_open(client: MagicMock, player: MagicMock) -> None:
    catalog = [
        PackItem.model_validate({"type": "narrator", "narrator_id": "a1", "title": "Alanis Morissette"}),
        PackItem.model_validate({"type": "narrator", "narrator_id": "b1", "title": "Bob Ross"}),
    ]
    tamara = PackItem.model_validate({"type": "narrator", "narrator_id": "n1", "title": "Tamara Levitt"})

    async def _search(query: str = "") -> list[PackItem]:
        # the default (empty) query returns the capped catalog; a name query finds anyone
        return catalog if not query else [tamara] if "tam" in query.lower() else []

    client.list_narrators.side_effect = _search

    app = BrowseApp(client)
    async with app.run_test() as pilot:
        app._load_narrators()
        await app.workers.wait_for_complete()
        await pilot.pause()
        listview = app.query_one("#narrator-list", ListView)
        rows = [str(i.query_one(Label).render()) for i in listview.query("ListItem")]
        assert "— A —" in rows and "— B —" in rows  # letter-section headers
        assert [r for r in rows if not r.startswith("—")] == ["Alanis Morissette", "Bob Ross"]

        # typing searches the server, so a narrator past the capped page is still found
        app.query_one("#narrator-filter", Input).value = "tamara"
        await pilot.pause()  # process Input.Changed so the search worker starts
        await app.workers.wait_for_complete()
        await pilot.pause()
        names = [str(i.query_one(Label).render()) for i in listview.query("ListItem") if not i.disabled]
        assert names == ["Tamara Levitt"]

        # opening a narrator loads its feed
        with patch.object(app, "_load_category") as load_category:
            app._open_item(tamara)
        load_category.assert_called_once_with("narrator-n1", "Tamara Levitt")


def test_narrators_in_sidebar_categories() -> None:
    # the Narrators entry is a TUI-only sidebar item, not a library category
    assert "narrators" not in [slug for slug, _, _ in browse.CATEGORIES]
