"""Tests for the browse TUI."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Input, Label, ProgressBar, Static

from calm_client.browse import BrowseApp, CatalogCard
from calm_client.client import CalmClient
from calm_client.models import (
    Asset,
    FeedResponse,
    Guide,
    ImageAsset,
    Pack,
    PackItem,
    Program,
    SearchItem,
    SearchResponse,
)


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=CalmClient)
    client.aclose = AsyncMock()
    client.get_category_feed = AsyncMock()
    client.get_favorites = AsyncMock()
    client.search = AsyncMock()
    client.get_program = AsyncMock()
    client.get_pack = AsyncMock(return_value=Pack())
    client.get_playlists = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_player() -> Generator[MagicMock, None, None]:
    with patch("calm_client.player.CalmPlayer") as mock:
        player_instance = mock.return_value
        # real values: the now-playing bar renders these as numbers and booleans
        player_instance.position = 0.0
        player_instance.duration = 0.0
        player_instance.is_paused = False
        player_instance.is_playing = False
        player_instance.stop = MagicMock()
        player_instance.shutdown = MagicMock()
        player_instance.play_track = AsyncMock()
        yield player_instance


@pytest.fixture
def sample_feed() -> FeedResponse:
    item = PackItem(
        title="Test Item",
        content_id="123",
        program_id="p123",
        item_type="audio",
        is_new=True,
        is_unlocked=True,
        image=ImageAsset(url="http://img"),
    )
    pack = Pack(
        title="Test Pack",
        items=[item],
        pack_class="default",
        display_type="list",
        has_more=False,
    )
    return FeedResponse(title="Test Feed", subtitle="Subtitle", packs=[pack])


@pytest.mark.asyncio
async def test_app_mount_and_quit(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test app startup and clean exit."""
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # Check initial layout
        assert app.query_one("#category-list")
        assert app.query_one("#catalog-grid")

        # Verify default category (implicit default selection logic if any)
        # It usually selects nothing or waits for input

        await pilot.press("q")


@pytest.mark.asyncio
async def test_navigation_category_to_grid(
    mock_client: MagicMock, sample_feed: FeedResponse, mock_player: MagicMock
) -> None:
    """Test navigating from category list to catalog grid."""
    mock_client.get_category_feed.return_value = sample_feed

    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # Select first category "Sleep" (usually first in DEFAULT_CATEGORIES)
        # Press enter on the focused list item
        await pilot.press("enter")
        await pilot.pause()  # Wait for feed load

        mock_client.get_category_feed.assert_called()

        # Check grid populated
        cards = app.query(CatalogCard)
        assert len(cards) > 0
        assert cards[0].card_title == "Test Pack"


@pytest.mark.asyncio
async def test_search_flow(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test search input and results."""
    item = SearchItem(title="Found It", content_id="s1", item_type="audio")
    search_res = SearchResponse(items=[item], total_item_number=1)
    mock_client.search.return_value = search_res

    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # Open search
        await pilot.press("slash")

        inp = app.query_one("#search-input", Input)
        assert inp.display
        assert inp.has_focus

        # Type query
        await pilot.press("h", "e", "l", "l", "o", "enter")
        await pilot.pause()

        mock_client.search.assert_called_with("hello")

        # Verify results
        cards = app.query(CatalogCard)
        assert len(cards) == 1
        assert cards[0].card_title == "Found It"


@pytest.mark.asyncio
async def test_favorites_flow(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test loading favorites."""
    item = PackItem(title="Fav One", content_id="f1", item_type="audio")
    mock_client.get_favorites.return_value = [item]

    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        mock_client.get_favorites.assert_called()

        cards = app.query(CatalogCard)
        assert len(cards) == 1
        assert cards[0].card_title == "Fav One"


@pytest.mark.asyncio
async def test_drill_down_pack(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test drilling down into a pack."""
    item = PackItem(title="Inner Item", content_id="i1", item_type="audio")
    outer_pack = Pack(title="Outer Pack", items=[item])

    feed = FeedResponse(title="F", packs=[outer_pack])
    mock_client.get_category_feed.return_value = feed

    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        # Grid now has "Outer Pack" card.
        app.query_one(CatalogCard)
        # Force drill directly to be sure
        app._drill_into_pack(outer_pack)
        await pilot.pause()

        # Should be in track view
        assert app.query_one("#track-panel").display
        label = app.query_one("#track-program-title", Label)
        assert "Outer Pack" in str(getattr(label, "renderable", label.render()))

        # Back should go back to browse view
        await pilot.press("escape")
        await pilot.pause()
        assert not app.query_one("#track-panel").display


@pytest.mark.asyncio
async def test_playback_flow(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test clicking a card to play it."""
    item = PackItem(title="Play Me", content_id="c1", program_id="p1", item_type="program", subtitle="Sub")

    guide = Guide(id="g1", title="Track 1", assets=[Asset(url="url", content_type="a", duration=10)])
    prog = Program(title="Prog", id="p1", guides=[guide])
    mock_client.get_program.return_value = prog

    feed = FeedResponse(title="F", packs=[Pack(title="P", items=[item])])
    mock_client.get_category_feed.return_value = feed

    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # Load category
        await pilot.press("enter")
        await pilot.pause()

        # Grid selection
        await pilot.press("enter")
        await pilot.pause()

        # Should be in track view
        assert app.query_one("#track-panel").display

        # Ensure current program is set for playback
        app._current_program = prog
        app._player = mock_player

        # Select first track
        # Direct call to trigger playback logic
        app._play_track(0)

        # Wait for calls
        for _ in range(3):
            await pilot.pause()

        # Check mock (browse calls .play(url))
        mock_player.play.assert_called_with("url")


@pytest.mark.asyncio
async def test_search_failure(mock_client: MagicMock) -> None:
    """Test search with API failure."""
    mock_client.search.side_effect = Exception("Search Failed")
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.press("slash")
        await pilot.press("a", "n", "y", "enter")
        await pilot.pause()
        # Should show error in title (browse.py:710)
        title = app.query_one("#catalog-title", Static)
        assert "Error: Search Failed" in str(getattr(title, "renderable", title.render()))


@pytest.mark.asyncio
async def test_favorites_empty(mock_client: MagicMock) -> None:
    """Test showing favorites when empty."""
    mock_client.get_favorites.return_value = []  # Correct return type: list
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()
        title = app.query_one("#catalog-title", Static)
        assert "Favorites" in str(getattr(title, "renderable", title.render()))
        assert not app.query("#catalog-grid CatalogCard")


@pytest.mark.asyncio
async def test_maximize_player(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test maximizing player view."""
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # Simulate player being active (bar mode)
        app._player_mode = "bar"
        app._player = mock_player  # Ensure player is set (it is by init but let's be safe if logic changed)

        # Trigger 'm'
        await pilot.press("m")
        await pilot.pause()

        # Should show maximized
        # Check style display property since that's what logic toggles
        assert app.query_one("#maximized-player").styles.display == "block"

        # Escape should go back
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#maximized-player").styles.display == "none"


@pytest.mark.asyncio
async def test_back_navigation(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test back navigation logic."""
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # 1. Maximized -> Expanded
        app._player = mock_player
        app._show_player_maximized()
        assert app.query_one("#maximized-player").styles.display == "block"

        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#maximized-player").styles.display == "none"
        assert app.query_one("#now-playing-expanded").styles.display == "block"

        # 2. Expanded -> Bar
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one("#now-playing-expanded").styles.display == "none"
        assert app.query_one("#now-playing-bar").styles.display == "block"


@pytest.mark.asyncio
async def test_player_controls(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test player controls (pause, stop, skip)."""
    prog = Program(
        title="P",
        id="p1",
        guides=[
            Guide(id="g1", title="T1", assets=[Asset(url="u1", content_type="a", duration=10)]),
            Guide(id="g2", title="T2", assets=[Asset(url="u2", content_type="a", duration=10)]),
        ],
    )
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        app._current_program = prog
        app._player = mock_player
        app._current_track_index = 0
        app._player.is_paused = False

        # Toggle pause
        await pilot.press("space")
        await pilot.pause()
        mock_player.pause.assert_called()

        # Skip next
        await pilot.press("n")
        assert app._current_track_index == 1

        # Stop
        app.action_stop_playback()
        mock_player.stop.assert_called()
        assert app.query_one("#now-playing-bar").styles.display == "none"


@pytest.mark.asyncio
async def test_player_progress_update(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test the progress timer update logic."""
    app = BrowseApp(mock_client)
    async with app.run_test():
        mock_player.position = 10.0
        mock_player.duration = 100.0
        mock_player.is_paused = False
        app._player = mock_player

        # Trigger internal UI update
        app._update_player_ui()

        # Cast to ProgressBar or similar if needed, but NowPlayingBar is a custom widget
        # Let's inspect NowPlayingBar definition if errors persist.
        # It's a container.
        # But here we access .position and .duration on it.
        # If NowPlayingBar has these properties, we just need to type check the query.
        # For now, let's ignore or cast.
        bar: MagicMock = app.query_one("#now-playing-bar")  # type: ignore[assignment]
        assert bar.position == 10.0
        assert bar.duration == 100.0


@pytest.mark.asyncio
async def test_category_caching(mock_client: MagicMock) -> None:
    """Test that categories are cached after first load."""
    app = BrowseApp(mock_client)
    feed = FeedResponse(title="Cached", packs=[])
    mock_client.get_category_feed.return_value = feed

    async with app.run_test() as pilot:
        # First load
        app._load_category("meditate", "Meditate")
        await pilot.pause()
        assert mock_client.get_category_feed.call_count == 1

        # Second load (should use cache)
        app._load_category("meditate", "Meditate")
        await pilot.pause()
        assert mock_client.get_category_feed.call_count == 1


@pytest.mark.asyncio
async def test_player_bar_expand(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test expanding the player bar."""
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        app._player = mock_player
        app._show_player_bar()
        await pilot.pause()
        assert app._player_mode == "bar"

        # Trigger the expand action directly to avoid click issues in headless CI
        app.on_now_playing_bar_click()
        await pilot.pause()
        assert app._player_mode == "expanded"


@pytest.mark.asyncio
async def test_maximize_toggle(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test toggling maximized player mode."""
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        app._player = mock_player
        app._show_player_expanded()
        assert app._player_mode == "expanded"

        # Toggle to maximized
        await pilot.press("m")
        assert app._player_mode == "maximized"

        # Toggle back (should go to expanded)
        await pilot.press("m")
        assert app._player_mode == "expanded"


@pytest.mark.asyncio
async def test_player_auto_advance(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test auto-advancing to the next track."""
    prog = Program(
        title="P",
        id="p1",
        guides=[
            Guide(id="g1", title="T1", assets=[Asset(url="u1", content_type="a", duration=10)]),
            Guide(id="g2", title="T2", assets=[Asset(url="u2", content_type="a", duration=10)]),
        ],
    )
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.pause()  # let the app finish mounting (#now-playing-bar) before acting
        app._current_program = prog
        app._current_track_index = 0
        app._player = mock_player

        # Mock call_from_thread to run directly in test
        with patch.object(app, "call_from_thread", side_effect=lambda f, *a, **k: f(*a, **k)):
            app._on_track_end()
            await pilot.pause()

        assert app._current_track_index == 1


@pytest.mark.asyncio
async def test_prev_track(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test skipping to the previous track."""
    prog = Program(
        title="P",
        id="p1",
        guides=[
            Guide(id="g1", title="T1", assets=[Asset(url="u1", content_type="a", duration=10)]),
            Guide(id="g2", title="T2", assets=[Asset(url="u2", content_type="a", duration=10)]),
        ],
    )
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        app._current_program = prog
        app._current_track_index = 1
        app._player = mock_player

        # Press Shift+N (mapped to prev_track)
        await pilot.press("shift+n")
        await pilot.pause()

        assert app._current_track_index == 0


@pytest.mark.asyncio
async def test_favorites_error(mock_client: MagicMock) -> None:
    """Test handling error when loading favorites."""
    mock_client.get_favorites.side_effect = Exception("API Error")
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        title = app.query_one("#catalog-title", Static)
        assert "Error" in str(getattr(title, "renderable", title.render()))


@pytest.mark.asyncio
async def test_prev_track_out_of_range(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test skipping to prev track when already at first track."""
    prog = Program(
        title="P", id="p1", guides=[Guide(id="g1", title="T1", assets=[Asset(url="u1", content_type="a", duration=10)])]
    )
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        app._current_program = prog
        app._current_track_index = 0
        app._player = mock_player

        await pilot.press("shift+n")
        await pilot.pause()

        # Should remain at 0
        assert app._current_track_index == 0


@pytest.mark.asyncio
async def test_search_input_focus(mock_client: MagicMock) -> None:
    """Test focusing search input."""
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.press("slash")
        await pilot.pause()
        assert app.query_one("#search-input").has_focus


@pytest.mark.asyncio
async def test_search_submission(mock_client: MagicMock) -> None:
    """Test submitting a search query."""
    res = SearchResponse(items=[SearchItem(title="Res", content_id="c1", item_type="audio")], total_item_number=1)
    mock_client.search.return_value = res
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # Show search
        await pilot.press("slash")

        # Type and enter
        for char in "calm":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause()

        # Check if search was called
        mock_client.search.assert_called_with("calm")
        # Check if results are displayed
        title = app.query_one("#catalog-title")
        assert "Results: calm" in str(getattr(title, "renderable", title.render()))


@pytest.mark.asyncio
async def test_stop_playback_action(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test stopping playback."""
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        app._player = mock_player
        app._player_mode = "bar"

        await pilot.press("s")
        await pilot.pause()

        mock_player.stop.assert_called()
        assert app._player_mode == "hidden"


@pytest.mark.asyncio
async def test_search_no_results(mock_client: MagicMock) -> None:
    """Test search with no results."""
    res = SearchResponse(items=[], total_item_number=0)
    mock_client.search.return_value = res
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.press("slash")
        for char in "nothing":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause()

        title = app.query_one("#catalog-title")
        assert "No results for 'nothing'" in str(getattr(title, "renderable", title.render()))


@pytest.mark.asyncio
async def test_category_selection(mock_client: MagicMock) -> None:
    """Test selecting a different category from the sidebar."""
    from unittest.mock import AsyncMock

    mock_client.get_category_feed = AsyncMock(return_value=FeedResponse(title="M", packs=[]))
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        # Move down in category list
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()

        # Should have loaded the next category
        mock_client.get_category_feed.assert_called()


@pytest.mark.asyncio
async def test_unmount_cleanup(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test cleanup on unmount."""
    app = BrowseApp(mock_client)
    app._player = mock_player
    app.on_unmount()
    mock_player.stop.assert_called()
    mock_player.shutdown.assert_called()


@pytest.mark.asyncio
async def test_catalog_card_render_direct(mock_client: MagicMock) -> None:
    """Test CatalogCard render logic."""
    card = CatalogCard("T", "S", "E")
    # This hits _render_card and other internal bits
    assert card.card_title == "T"
    assert card.card_emoji == "E"


@pytest.mark.asyncio
async def test_player_progress_updates(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test separate progress update methods."""
    app = BrowseApp(mock_client)
    async with app.run_test():
        app._player = mock_player
        # Test expanded
        app._show_player_expanded()
        app._update_expanded_progress(10, 100)
        assert app.query_one("#expanded-progress", ProgressBar).progress == 10.0

        # Test maximized
        app._show_player_maximized()
        app._update_maximized_progress(20, 100)
        assert app.query_one("#max-progress", ProgressBar).progress == 20.0


@pytest.mark.asyncio
async def test_player_ui_extended_updates(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test UI updates in expanded and maximized modes."""
    app = BrowseApp(mock_client)
    async with app.run_test():
        mock_player.position = 50.0
        mock_player.duration = 200.0
        app._player = mock_player

        # Expanded
        app._show_player_expanded()
        app._update_player_ui()
        assert app.query_one("#expanded-progress", ProgressBar).progress == 50.0

        # Maximized
        app._show_player_maximized()
        app._update_player_ui()
        assert app.query_one("#max-progress", ProgressBar).progress == 50.0
