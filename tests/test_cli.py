import logging
from collections.abc import Generator
from contextlib import suppress
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from calm_client.cli import app
from calm_client.client import CalmClient
from calm_client.credentials import Credentials
from calm_client.exceptions import CalmAuthError
from calm_client.models import (
    Asset,
    AudioQuality,
    Guide,
    Program,
    SearchItem,
    SearchResponse,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at a temporary config dir, so tests never read or delete real credentials."""
    config_dir = tmp_path / "calm-client"
    monkeypatch.setattr("calm_client.cli.CONFIG_DIR", config_dir)
    monkeypatch.setattr("calm_client.cli.CONFIG_FILE", config_dir / "config.json")
    return config_dir / "config.json"


@pytest.fixture
def mock_console() -> Generator[MagicMock, None, None]:
    with patch("calm_client.cli.console") as mock:
        yield mock


@pytest.fixture
def mock_client() -> Generator[MagicMock, None, None]:
    with patch("calm_client.cli.CalmClient") as mock:
        yield mock


@patch("calm_client.cli.Prompt.ask")
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


@patch("calm_client.cli.Prompt.ask")
@patch("calm_client.cli.save_credentials")
@patch("calm_client.cli.load_credentials")
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


@patch("calm_client.cli.load_credentials")
def test_whoami_unauthenticated(mock_load_credentials: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    with suppress(SystemExit):
        app(["whoami"])
    mock_console.print.assert_called_with("[yellow]Not logged in. Run 'calm login' first.[/yellow]")


@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli._check_auth")
@patch("calm_client.cli.load_credentials")
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

    mock_console.print.assert_any_call("[green]Logged in and authenticated.[/green]")


@patch("calm_client.cli.load_credentials")
def test_search_unauthenticated(mock_load_credentials: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    with suppress(SystemExit):
        app(["search", "query"])
    mock_console.print.assert_called_with("[yellow]Not logged in. Run 'calm login' first.[/yellow]")


@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
def test_search_no_results(mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    mock_instance = mock_client.return_value.__aenter__.return_value
    mock_instance.credentials = mock_creds
    mock_instance.search.return_value = MagicMock(items=[], total_item_number=0)

    with suppress(SystemExit):
        app(["search", "test"])

    mock_console.print.assert_called_with("[yellow]No results found.[/yellow]")


@patch("calm_client.cli.save_credentials")
@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
def test_search_results(
    mock_load_credentials: MagicMock, mock_client: MagicMock, mock_save_credentials: MagicMock, mock_console: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    item = SearchItem(
        title="Test Item",
        content_id="123",
        item_type="audio",
        search_category="sleep",
        subtitle="Subtitle",
        is_new=False,
        is_unlocked=True,
    )
    # Search returns a SearchResponse, not FeedResponse
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


@patch("calm_client.cli.save_credentials")
@patch("calm_client.play.run_play")
@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
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

    # Guide needs assets to have a stream_url
    asset = Asset(url="http://url", content_type="audio/mpeg", duration=100)
    program = Program(
        title="Test Program",
        id="p1",
        description="Desc",
        guides=[Guide(id="g1", title="Track 1", assets=[asset])],
    )

    # client is instantiated normally in play(), not context manager
    mock_instance = mock_client.return_value
    mock_instance.credentials = mock_creds
    mock_instance.get_program = AsyncMock(return_value=program)
    mock_instance.close = AsyncMock()  # cli.py calls await client.close()

    with suppress(SystemExit):
        app(["play", "p1"])

    mock_run_play.assert_called_with(program, 0, AudioQuality.COMPACT)


@patch("calm_client.browse.run_browse")
@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
def test_browse_valid(
    mock_load_credentials: MagicMock, mock_client: MagicMock, mock_run_browse: MagicMock, mock_console: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    with suppress(SystemExit):
        app(["browse"])

    mock_run_browse.assert_called()


@patch("calm_client.cli.Prompt.ask")
@patch("calm_client.cli.load_credentials")
def test_login_no_email(mock_load_credentials: MagicMock, mock_ask: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    mock_ask.return_value = ""  # No email entered
    with suppress(SystemExit):
        app(["login"])
    # Should return early or show error
    pass


@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
def test_search_no_results_cli(
    mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    # client is used as context manager in search
    mock_instance = AsyncMock(spec=CalmClient)
    mock_instance.credentials = mock_creds
    mock_instance.search = AsyncMock(return_value=SearchResponse(items=[], total_item_number=0))

    mock_client.return_value.__aenter__.return_value = mock_instance

    with suppress(SystemExit):
        app(["search", "nothing"])

    # Message from perform_search: console.print("[yellow]No results found.[/yellow]")
    mock_console.print.assert_any_call("[yellow]No results found.[/yellow]")


@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
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
    mock_console.print.assert_any_call("[red]Error fetching program: Not found[/red]")


@patch("calm_client.cli.save_credentials")
def test_logout(mock_save_credentials: MagicMock, mock_console: MagicMock) -> None:
    with suppress(SystemExit):
        app(["logout"])
    # mock_save_credentials.assert_called_with(None) # Removed call in code, now just unlinks file
    mock_console.print.assert_any_call("Logged out successfully.")


@patch("calm_client.cli.load_credentials")
def test_check_auth_fails(mock_load_credentials: MagicMock, mock_console: MagicMock) -> None:
    mock_load_credentials.return_value = None
    with suppress(SystemExit):
        app(["search", "foo"])
    # Should say Not logged in
    mock_console.print.assert_any_call("[yellow]Not logged in. Run 'calm login' first.[/yellow]")


@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
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

    mock_console.print.assert_any_call("[green]Logged in and authenticated.[/green]")


@patch("calm_client.cli.Prompt.ask")
@patch("calm_client.cli.save_credentials")
def test_login_interactive(mock_save_credentials: MagicMock, mock_ask: MagicMock, mock_console: MagicMock) -> None:
    # Mock inputs for email and password
    mock_ask.side_effect = ["user@example.com", "secret"]

    with patch("calm_client.cli.CalmClient") as mock_client:
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


@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
def test_search_with_table(mock_load_credentials: MagicMock, mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    mock_instance = AsyncMock(spec=CalmClient)
    item = SearchItem(title="Result", content_id="c1", item_type="audio")
    res = SearchResponse(items=[item], total_item_number=1)
    mock_instance.credentials = mock_creds
    mock_instance.search = AsyncMock(return_value=res)
    mock_client.return_value.__aenter__.return_value = mock_instance

    with suppress(SystemExit):
        app(["search", "query"])

    # Check if a table was printed (cli uses Table)
    from rich.table import Table

    # Find any Table object passed to console.print
    table_called = any(isinstance(call.args[0], Table) for call in mock_console.print.call_args_list)
    assert table_called


# ---------------------------------------------------------------------------
# Global options, credential storage and token refresh persistence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "level"),
    [(["--debug"], logging.DEBUG), (["--verbose"], logging.INFO), ([], logging.WARNING)],
)
def test_global_logging_flags(flags: list[str], level: int, mock_console: MagicMock) -> None:
    with patch("calm_client.cli.configure_logging") as configure, suppress(SystemExit):
        app.meta([*flags, "logout"])
    configure.assert_called_once_with(level=level)


def test_credentials_round_trip(isolated_config: Path) -> None:
    from calm_client.cli import load_credentials, save_credentials

    assert load_credentials() is None
    save_credentials(Credentials(token="t", refresh_token="r", device_id="d"))
    loaded = load_credentials()
    assert loaded is not None
    assert (loaded.token, loaded.refresh_token, loaded.device_id) == ("t", "r", "d")


def test_load_credentials_ignores_corrupt_file(isolated_config: Path) -> None:
    from calm_client.cli import load_credentials

    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text("{not json")
    assert load_credentials() is None


def test_logout_removes_stored_credentials(isolated_config: Path, mock_console: MagicMock) -> None:
    from calm_client.cli import save_credentials

    save_credentials(Credentials(token="t"))
    with suppress(SystemExit):
        app(["logout"])
    assert not isolated_config.exists()


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("header.eyJlbWFpbCI6InN0b3JlZEBleGFtcGxlLmNvbSJ9.sig", "stored@example.com"),
        ("header.eyJzdWIiOiIxIn0.sig", None),  # {"sub":"1"}: no email claim
        ("not-a-jwt", None),
        ("header.!!!.sig", None),
    ],
)
def test_extract_email_from_token(token: str, expected: str | None) -> None:
    from calm_client.cli import _extract_email_from_token

    assert _extract_email_from_token(token) == expected


@pytest.mark.asyncio
async def test_check_auth() -> None:
    from calm_client.cli import _check_auth

    client = MagicMock()
    client._request = AsyncMock(return_value={})
    assert await _check_auth(client) is True
    client._request = AsyncMock(side_effect=CalmAuthError("expired"))
    assert await _check_auth(client) is False


def test_whoami_saves_refreshed_token(isolated_config: Path, mock_client: MagicMock, mock_console: MagicMock) -> None:
    from calm_client.cli import load_credentials, save_credentials

    save_credentials(Credentials(token="old", refresh_token="r"))
    creds = load_credentials()
    assert creds is not None

    async def check_and_refresh(_client: object) -> bool:
        creds.token = "refreshed"  # the real client refreshes the same object in place
        return True

    with (
        patch("calm_client.cli.load_credentials", return_value=creds),
        patch("calm_client.cli._check_auth", side_effect=check_and_refresh),
        suppress(SystemExit),
    ):
        mock_client.return_value.__aenter__.return_value.credentials = creds
        app(["whoami"])

    stored = load_credentials()
    assert stored is not None and stored.token == "refreshed"
    mock_console.print.assert_any_call("[dim]Token was refreshed and saved.[/dim]")


def test_search_saves_refreshed_token_even_without_results(
    isolated_config: Path, mock_client: MagicMock, mock_console: MagicMock
) -> None:
    from calm_client.cli import load_credentials, save_credentials

    save_credentials(Credentials(token="old", refresh_token="r"))
    creds = load_credentials()
    assert creds is not None
    instance = mock_client.return_value.__aenter__.return_value
    instance.credentials = creds

    async def search_and_refresh(_query: str) -> SearchResponse:
        creds.token = "refreshed"
        return SearchResponse(items=[], total_item_number=0)

    instance.search = AsyncMock(side_effect=search_and_refresh)
    with patch("calm_client.cli.load_credentials", return_value=creds), suppress(SystemExit):
        app(["search", "rain"])

    stored = load_credentials()
    assert stored is not None and stored.token == "refreshed"


def test_play_saves_refreshed_token(isolated_config: Path, mock_client: MagicMock, mock_console: MagicMock) -> None:
    from calm_client.cli import load_credentials, save_credentials

    save_credentials(Credentials(token="old", refresh_token="r"))
    creds = load_credentials()
    assert creds is not None
    instance = mock_client.return_value
    instance.credentials = creds
    instance.close = AsyncMock()
    guide = Guide(id="g", title="G", assets=[Asset(url="u", content_type="a", duration=1)])
    program = Program(id="p", title="P", guides=[guide])

    async def get_and_refresh(_program_id: str) -> Program:
        creds.token = "refreshed"
        return program

    instance.get_program = AsyncMock(side_effect=get_and_refresh)
    with (
        patch("calm_client.cli.load_credentials", return_value=creds),
        patch("calm_client.play.run_play"),
        suppress(SystemExit),
    ):
        app(["play", "p"])

    stored = load_credentials()
    assert stored is not None and stored.token == "refreshed"


# ---------------------------------------------------------------------------
# Remaining command branches
# ---------------------------------------------------------------------------


def test_whoami_invalid_token(mock_client: MagicMock, mock_console: MagicMock) -> None:
    with (
        patch("calm_client.cli.load_credentials", return_value=Credentials(token="t")),
        patch("calm_client.cli._check_auth", AsyncMock(return_value=False)),
        suppress(SystemExit),
    ):
        app(["whoami"])
    mock_console.print.assert_any_call("[red]Token is invalid or expired. Please run 'calm login' again.[/red]")


def test_whoami_error(mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_client.return_value.__aenter__.side_effect = RuntimeError("network down")
    with patch("calm_client.cli.load_credentials", return_value=Credentials(token="t")), suppress(SystemExit):
        app(["whoami"])
    mock_console.print.assert_any_call("[red]Error checking status: network down[/red]")


def test_search_error(mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_client.return_value.__aenter__.return_value.search = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("calm_client.cli.load_credentials", return_value=Credentials(token="t")), suppress(SystemExit):
        app(["search", "rain"])
    mock_console.print.assert_any_call("[red]Error: boom[/red]")


@pytest.mark.parametrize(
    ("guides", "args", "message"),
    [
        ([], ["play", "p"], "[red]No guides/tracks found in this program.[/red]"),
        ([Guide(id="g", title="G")], ["play", "p", "--guide", "3"], "[red]Guide index 3 out of range (0-0).[/red]"),
        ([Guide(id="g", title="G")], ["play", "p"], "[red]No streamable audio found for this track.[/red]"),
    ],
)
def test_play_unplayable_programs(
    guides: list[Guide], args: list[str], message: str, mock_client: MagicMock, mock_console: MagicMock
) -> None:
    creds = Credentials(token="t")
    instance = mock_client.return_value
    instance.credentials = creds
    instance.close = AsyncMock()
    instance.get_program = AsyncMock(return_value=Program(id="p", title="P", guides=guides))
    with (
        patch("calm_client.cli.load_credentials", return_value=creds),
        patch("calm_client.play.run_play") as run_play,
        suppress(SystemExit),
    ):
        app(args)
    mock_console.print.assert_any_call(message)
    run_play.assert_not_called()


@pytest.mark.parametrize("command", [["play", "p"], ["browse"], ["whoami"]])
def test_commands_require_login(command: list[str], mock_console: MagicMock) -> None:
    with patch("calm_client.cli.load_credentials", return_value=None), suppress(SystemExit):
        app(command)
    mock_console.print.assert_any_call("[yellow]Not logged in. Run 'calm login' first.[/yellow]")


@patch("calm_client.cli.Prompt.ask")
def test_login_warns_without_refresh_token(
    mock_ask: MagicMock, isolated_config: Path, mock_client: MagicMock, mock_console: MagicMock
) -> None:
    mock_ask.side_effect = ["user@example.com", "pw"]
    instance = mock_client.return_value.__aenter__.return_value
    instance.login = AsyncMock(return_value=Credentials(token="t"))
    with patch.dict("os.environ", {}, clear=True), suppress(SystemExit):
        app(["login"])
    mock_console.print.assert_any_call("[yellow]Warning: No refresh token received.[/yellow]")
    assert isolated_config.exists()


@patch("calm_client.cli.Prompt.ask")
def test_login_failure_is_reported(mock_ask: MagicMock, mock_client: MagicMock, mock_console: MagicMock) -> None:
    mock_ask.side_effect = ["user@example.com", "pw"]
    mock_client.return_value.__aenter__.return_value.login = AsyncMock(side_effect=CalmAuthError("bad password"))
    with patch.dict("os.environ", {}, clear=True), suppress(SystemExit):
        app(["login"])
    mock_console.print.assert_any_call("[red]Login failed: bad password[/red]")


@patch("calm_client.cli.save_credentials")
@patch("calm_client.play.run_play")
@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
def test_play_quality_option(
    mock_load_credentials: MagicMock,
    mock_client: MagicMock,
    mock_run_play: MagicMock,
    mock_save_credentials: MagicMock,
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds
    asset = Asset(url="http://url", content_type="audio/wav", duration=100)
    program = Program(title="T", id="p1", guides=[Guide(id="g1", title="Track 1", assets=[asset])])
    mock_instance = mock_client.return_value
    mock_instance.credentials = mock_creds
    mock_instance.get_program = AsyncMock(return_value=program)
    mock_instance.close = AsyncMock()

    with suppress(SystemExit):
        app(["play", "p1", "--quality", "highest"])

    mock_run_play.assert_called_with(program, 0, AudioQuality.HIGHEST)


@patch("calm_client.browse.run_browse")
@patch("calm_client.cli.CalmClient")
@patch("calm_client.cli.load_credentials")
def test_browse_quality_option(
    mock_load_credentials: MagicMock, mock_client: MagicMock, mock_run_browse: MagicMock
) -> None:
    mock_creds = MagicMock()
    mock_creds.token = "token"
    mock_load_credentials.return_value = mock_creds

    with suppress(SystemExit):
        app(["browse", "--quality", "highest"])

    mock_run_browse.assert_called_with(mock_client.return_value, AudioQuality.HIGHEST)
