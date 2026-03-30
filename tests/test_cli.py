from collections.abc import Generator
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from calm_client.cli.cli import app
from calm_client.client import CalmClient
from calm_client.models import (
    CalmAsset,
    CalmTrack,
    CalmAlbum,
    CalmBaseItem,
    SearchResponse,
)


@pytest.fixture
def mock_console() -> Generator[MagicMock, None, None]:
    with patch("calm_client.cli.cli.console") as mock:
        yield mock


@pytest.fixture
def mock_client() -> Generator[MagicMock, None, None]:
    with patch("calm_client.cli.cli.CalmClient") as mock:
        yield mock


@patch("calm_client.cli.cli.Prompt.ask")
@patch.dict("os.environ", {"CALM_EMAIL": "env_user@example.com", "CALM_PASSWORD": "env_password"})
def test_login_env_vars(mock_ask: MagicMock, mock_console: MagicMock, mock_client: MagicMock) -> None:
    # Mock the client context manager
    mock_instance = mock_client.return_value.__aenter__.return_value
    mock_instance.login.return_value = MagicMock()
    mock_ask.return_value = "env_user@example.com"

    # Run the login command
    with suppress(SystemExit):
        app(["login"])

    # Verify that prompts were called with default values from env vars
    # The email prompt should use the env var as default
    mock_ask.assert_any_call("Email", console=mock_console, default="env_user@example.com")

    # Verify login was called with correct credentials from env vars
    # Note: password prompt is skipped because env var is present
    mock_instance.login.assert_called_with("env_user@example.com", "env_password")


@patch("calm_client.cli.cli.Prompt.ask")
@patch("calm_client.cli.cli.save_credentials")
@patch("calm_client.cli.cli.load_credentials")
def test_login_from_id_token(
    mock_load_credentials: MagicMock,
    mock_save_credentials: MagicMock,
    mock_ask: MagicMock,
    mock_console: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Test that login uses email from existing id_token as default."""
    from calm_client.credentials import Credentials

    # Mock invalid credentials but with an ID token containing an email
    # A minimal JWT payload for {"email": "stored@example.com"}
    # eyJlbWFpbCI6InN0b3JlZEBleGFtcGxlLmNvbSJ9 is b64 of {"email":"stored@example.com"}
    dummy_id_token = "header.eyJlbWFpbCI6InN0b3JlZEBleGFtcGxlLmNvbSJ9.sig"

    mock_creds = MagicMock(spec=Credentials)
    mock_creds.id_token = dummy_id_token
    mock_creds.session_token = "old_session_token"
    mock_load_credentials.return_value = mock_creds

    # Mock client and prompts
    mock_instance = mock_client.return_value.__aenter__.return_value
    mock_instance.login.return_value = MagicMock()
    mock_ask.side_effect = ["final@example.com", "password"]

    # Run login command (no env vars set for email)
    # Run login command (no env vars set for email)
    with patch.dict("os.environ", {}, clear=True), suppress(SystemExit):
        app(["login"])

    # Verify Prompt.ask was called with the email extracted from token as default
    mock_ask.assert_any_call("Email", console=mock_console, default="stored@example.com")

    # Verify login logic used the input (simulating user accepting or changing default)
    # In this test we simulated user typing "final@example.com"
    mock_instance.login.assert_called_with("final@example.com", "password")


@patch("calm_client.cli.cli.load_credentials")
def test_whoami_unauthenticated(mock_load_credentials: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    with suppress(SystemExit):
        app(["whoami"])
    mock_console.print.assert_called_with("[yellow]Not logged in.[/yellow]")


@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli._check_auth")
@patch("calm_client.cli.cli.load_credentials")
def test_whoami_authenticated(
    mock_load_credentials: MagicMock, mock_check_auth: MagicMock, mock_client: MagicMock, mock_console: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds
    mock_check_auth.return_value = True

    # Setup client context manager
    mock_instance = mock_client.return_value.__aenter__.return_value
    mock_instance.credentials = mock_creds

    with suppress(SystemExit):
        app(["whoami"])

    mock_console.print.assert_any_call("[green]Authenticated.[/green]")


@patch("calm_client.cli.cli.load_credentials")
def test_search_unauthenticated(mock_load_credentials: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    with suppress(SystemExit):
        app(["search", "query"])
    mock_console.print.assert_called_with("[yellow]Not logged in.[/yellow]")


@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_search_no_results(mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    mock_instance = mock_client.return_value.__aenter__.return_value
    mock_instance.search.return_value = MagicMock(items=[], total_item_number=0)

    with suppress(SystemExit):
        app(["search", "test"])

    mock_console.print.assert_called_with("[yellow]No results.[/yellow]")


@patch("calm_client.cli.cli.save_credentials")
@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_search_results(
    mock_load_credentials: MagicMock, mock_client: MagicMock, mock_save_credentials: MagicMock, mock_console: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    item = CalmBaseItem(
        title="Test Item",
        content_id="123",
        item_type="audio",
        search_category="sleep",
        subtitle="Subtitle",
        is_new=False,
        is_unlocked=True,
    )
    # Search returns a SearchResponse, not CalmFeed
    mock_instance = mock_client.return_value.__aenter__.return_value
    mock_instance.search.return_value = SearchResponse(items=[item], total_item_number=1)

    # Mock credentials to differ so save_credentials is called
    mock_instance.credentials.token = "new_token"

    with suppress(SystemExit):
        app(["search", "test"])

    # Verify table prints (rich Table object is printed)
    assert mock_console.print.call_count >= 1
    args, _ = mock_console.print.call_args
    # args[0] is the Table object
    assert "Search Results" in args[0].title


@patch("calm_client.cli.cli.save_credentials")
@patch("calm_client.cli.play.run_play")
@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_play_valid(
    mock_load_credentials: MagicMock,
    mock_client: MagicMock,
    mock_run_play: MagicMock,
    mock_save_credentials: MagicMock,
    mock_console: MagicMock,
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    # CalmTrack needs assets to have a stream_url
    asset = CalmAsset(url="http://url", content_type="audio/mpeg", duration=100)
    program = CalmAlbum(
        title="Test CalmAlbum",
        id="p1",
        description="Desc",
        guides=[CalmTrack(id="g1", title="Track 1", assets=[asset])],
    )

    # client is instantiated normally in play(), not context manager
    mock_instance = mock_client.return_value
    mock_instance.get_program = AsyncMock(return_value=program)
    mock_instance.close = AsyncMock()  # cli.py calls await client.close()

    with suppress(SystemExit):
        app(["play", "p1"])

    mock_run_play.assert_called_with(program, 0)


@patch("calm_client.cli.browse.run_browse")
@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_browse_valid(
    mock_load_credentials: MagicMock, mock_client: MagicMock, mock_run_browse: MagicMock, mock_console: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    with suppress(SystemExit):
        app(["browse"])

    mock_run_browse.assert_called()


@patch("calm_client.cli.cli.Prompt.ask")
@patch("calm_client.cli.cli.load_credentials")
def test_login_no_email(mock_load_credentials: MagicMock, mock_ask: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    mock_ask.return_value = ""  # No email entered
    with suppress(SystemExit):
        app(["login"])
    # Should return early or show error
    pass


@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_search_no_results_cli(
    mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    # client is used as context manager in search
    mock_instance = AsyncMock(spec=CalmClient)
    mock_instance.search = AsyncMock(return_value=SearchResponse(items=[], total_item_number=0))

    mock_client.return_value.__aenter__.return_value = mock_instance

    with suppress(SystemExit):
        app(["search", "nothing"])

    # Message from perform_search: console.print("[yellow]No results.[/yellow]")
    mock_console.print.assert_any_call("[yellow]No results.[/yellow]")


@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_play_not_found(mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    # client is used as context manager AND as direct instance
    mock_instance = AsyncMock(spec=CalmClient)
    mock_instance.get_program = AsyncMock(side_effect=Exception("Not found"))
    mock_instance.close = AsyncMock()

    # Fix JSON serialization by mocking credentials properly
    mock_creds_real = MagicMock()
    mock_creds_real.token = "token"
    mock_creds_real.model_dump.return_value = {"token": "token"}
    mock_instance.credentials = mock_creds_real

    # Mock return value for direct instantiation client = CalmClient(creds)
    mock_client.return_value = mock_instance
    # Mock return value for async with CalmClient(creds) as client
    mock_client.return_value.__aenter__.return_value = mock_instance
    mock_client.return_value.__aexit__ = AsyncMock()

    with suppress(SystemExit):
        app(["play", "invalid"])

    # Should catch exception and print error (line 356)
    mock_console.print.assert_any_call("[red]Not found[/red]")


@patch("calm_client.cli.cli.save_credentials")
def test_logout(mock_save_credentials: MagicMock, mock_console: MagicMock) -> None:
    with suppress(SystemExit):
        app(["logout"])
    # mock_save_credentials.assert_called_with(None) # Removed call in code, now just unlinks file
    mock_console.print.assert_any_call("Logged out.")


@patch("calm_client.cli.cli.load_credentials")
def test_check_auth_fails(mock_load_credentials: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    with suppress(SystemExit):
        app(["search", "foo"])
    # Should say Not logged in
    mock_console.print.assert_any_call("[yellow]Not logged in.[/yellow]")


@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_whoami(mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_creds.email = "test@example.com"
    mock_load_credentials.return_value = mock_creds

    # Instance mock that works as CM
    mock_instance = AsyncMock(spec=CalmClient)
    mock_instance.credentials = mock_creds
    mock_client.return_value.__aenter__.return_value = mock_instance

    with suppress(SystemExit):
        app(["whoami"])

    mock_console.print.assert_any_call("[green]Authenticated.[/green]")


@patch("calm_client.cli.cli.Prompt.ask")
@patch("calm_client.cli.cli.save_credentials")
def test_login_interactive(mock_save_credentials: MagicMock, mock_ask: MagicMock, mock_console: MagicMock) -> None:
    # Mock inputs for email and password
    mock_ask.side_effect = ["user@example.com", "secret"]

    with patch("calm_client.cli.cli.CalmClient") as mock_client:
        mock_instance = AsyncMock(spec=CalmClient)
        # Fix: model_dump must be a real method for json.dumps
        mock_creds = MagicMock()
        mock_creds.email = "user@example.com"
        mock_creds.token = "t1"
        mock_creds.model_dump.return_value = {"token": "t1", "email": "user@example.com"}

        mock_instance.login = AsyncMock(return_value=mock_creds)
        mock_client.return_value.__aenter__.return_value = mock_instance

        with suppress(SystemExit):
            app(["login"])

    mock_save_credentials.assert_called()
    mock_console.print.assert_any_call("[green]Success! Logged in as user@example.com[/green]")


@patch("calm_client.cli.cli.CalmClient")
@patch("calm_client.cli.cli.load_credentials")
def test_search_with_table(mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    mock_instance = AsyncMock(spec=CalmClient)
    item = CalmBaseItem(title="Result", content_id="c1", item_type="audio")
    res = SearchResponse(items=[item], total_item_number=1)
    mock_instance.search = AsyncMock(return_value=res)
    mock_client.return_value.__aenter__.return_value = mock_instance

    with suppress(SystemExit):
        app(["search", "query"])

    # Check if a table was printed (cli uses Table)
    from rich.table import Table

    # Find any Table object passed to console.print
    table_called = any(isinstance(call.args[0], Table) for call in mock_console.print.call_args_list)
    assert table_called
