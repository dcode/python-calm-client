"""Tests for the browse TUI."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Input, Label, ProgressBar, Static

from calm_client.cli.browse import BrowseApp, CatalogCard
from calm_client.client import CalmClient
from calm_client.models import (
    CalmAlbum,
    CalmAsset,
    CalmBaseItem,
    CalmFeed,
    CalmFolder,
    CalmTrack,
    SearchResponse,
)


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=CalmClient)
    client.aclose = AsyncMock()
    client.browse = AsyncMock()
    client.search = AsyncMock()
    client.get_program = AsyncMock()
    return client


@pytest.fixture
def mock_player() -> Generator[MagicMock, None, None]:
    with patch("calm_client.cli.browse.CalmPlayer") as mock:
        player_instance = mock.return_value
        player_instance.stop = MagicMock()
        player_instance.shutdown = MagicMock()
        player_instance.play = MagicMock()
        yield player_instance


@pytest.fixture
def sample_folder() -> CalmFolder:
    item = CalmBaseItem(
        title="Test Item",
        id="123",
        type="guide",
    )
    return CalmFolder(
        title="Test Folder",
        id="f1",
        items=[item],
        type="pack",
    )


@pytest.mark.asyncio
async def test_app_mount_and_quit(mock_client: MagicMock) -> None:
    """Test app startup and clean exit."""
    mock_client.browse.return_value = []
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        assert app.query_one("#catalog-grid")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_navigation_browse(
    mock_client: MagicMock, sample_folder: CalmFolder
) -> None:
    """Test navigating through folders."""
    mock_client.browse.side_effect = [
        [sample_folder],  # Root
        sample_folder.items,  # Inner folder
    ]

    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.pause()
        mock_client.browse.assert_called_with("")

        # Click the folder card
        await pilot.press("enter")
        await pilot.pause()

        mock_client.browse.assert_called_with("f1")

        # Check grid populated with inner items
        cards = app.query(CatalogCard)
        assert len(cards) == 1
        assert cards[0].item.title == "Test Item"


@pytest.mark.asyncio
async def test_search_flow(mock_client: MagicMock) -> None:
    """Test search input and results."""
    item = CalmBaseItem(title="Found It", id="s1", type="guide")
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
        assert cards[0].item.title == "Found It"


@pytest.mark.asyncio
async def test_playback_flow(mock_client: MagicMock, mock_player: MagicMock) -> None:
    """Test playing a track."""
    track = CalmTrack(
        id="t1", title="Track 1", type="guide",
        assets=[CalmAsset(url="url", content_type="audio/mp4", duration=10)]
    )
    mock_client.browse.return_value = [track]

    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Select track card
        await pilot.press("enter")
        await pilot.pause()

        # Check mock (browse calls .play(url))
        mock_player.play.assert_called_with("url")


@pytest.mark.asyncio
async def test_back_navigation(mock_client: MagicMock) -> None:
    """Test back navigation logic."""
    f1 = CalmFolder(id="f1", title="F1", type="pack")
    mock_client.browse.side_effect = [
        [f1],  # Load root
        [],    # Load F1
        [f1],  # Back to root
    ]
    app = BrowseApp(mock_client)
    async with app.run_test() as pilot:
        await pilot.pause()
        
        # Go to F1
        await pilot.press("enter")
        await pilot.pause()
        assert app._history == ["", "f1"]

        # Back
        await pilot.press("escape")
        await pilot.pause()
        assert app._history == [""]
        mock_client.browse.assert_called_with("")
