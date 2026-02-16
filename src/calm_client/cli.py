"""CLI for Calm Client."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import cyclopts
from platformdirs import user_config_dir
from rich import print as rprint
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from calm_client.client import CalmClient
from calm_client.credentials import Credentials
from calm_client.exceptions import CalmAuthError
from calm_client.logging import configure_logging

if TYPE_CHECKING:
    from .models import Program

console = Console()
app = cyclopts.App(name="calm")

CONFIG_DIR = Path(user_config_dir("calm-client", "dcode"))
CONFIG_FILE = CONFIG_DIR / "config.json"




@app.meta.default
def _meta(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
    debug: Annotated[
        bool,
        cyclopts.Parameter(
            name="--debug",
            help="Enable DEBUG logging (very verbose).",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        cyclopts.Parameter(
            name="--verbose",
            help="Enable INFO logging.",
        ),
    ] = False,
) -> None:
    """Calm CLI — interact with calm.com from the terminal."""
    if debug:
        configure_logging(level=logging.DEBUG)
    elif verbose:
        configure_logging(level=logging.INFO)
    else:
        configure_logging(level=logging.WARNING)

    app(tokens)


def load_credentials() -> Credentials | None:
    """Load credentials from config file."""
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text())
        return Credentials.model_validate(data)
    except Exception:
        return None


def save_credentials(creds: Credentials) -> None:
    """Save credentials to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(creds.model_dump(by_alias=True), indent=2))


async def _check_auth(client: CalmClient) -> bool:
    """Check if current token is valid by making a lightweight API request.

    Uses a raw _request() call instead of model-parsed endpoints to avoid
    false negatives from Pydantic validation errors.
    """
    try:
        # Just check we get a 200 — don't try to parse the response model
        await client._request("GET", "packs/feeds/sleep")
        return True
    except CalmAuthError:
        return False


def _extract_email_from_token(token: str) -> str | None:
    """Extract email from a JWT id_token without verify (for UI defaults only)."""
    try:
        # JWT is header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return None

        payload = parts[1]
        # Add padding if needed
        padding = "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(decoded)
        email = data.get("email")

        return cast("str", email) if email is not None else None
    except Exception:
        return None


@app.command
def login() -> None:
    """Interactive login to store authentication token."""
    console.print("[bold blue]Calm Client Login[/bold blue]")

    default_email = os.environ.get("CALM_EMAIL")

    # If no env var, try to get email from existing id_token
    if not default_email:
        creds = load_credentials()
        if creds and creds.id_token:
            default_email = _extract_email_from_token(creds.id_token)

    email = Prompt.ask("Email", console=console, default=default_email)

    default_password = os.environ.get("CALM_PASSWORD")
    if default_password:
        rprint("[dim]Using password from environment/config[/dim]")
        password = default_password
    else:
        password = Prompt.ask("Password", console=console, password=True)

    if not email or not password:
        console.print("[red]Email and password are required.[/red]")
        return

    async def perform_login() -> None:
        try:
            # Check for existing session token to preserve
            existing_creds = load_credentials()
            session_token = existing_creds.session_token if existing_creds else None

            async with CalmClient(existing_creds) as client:
                with console.status("Logging in via Auth0..."):
                    creds = await client.login(email, password)

            # Restore session token if available and NOT present in new credentials
            if session_token and not creds.session_token:
                creds.session_token = session_token
                console.print("[dim]Preserved existing session token for favorites[/dim]")

            save_credentials(creds)
            console.print(f"[green]Success! Logged in as {email}[/green]")
            console.print(f"[dim]Credentials saved to {CONFIG_FILE}[/dim]")
            if creds.can_refresh:
                console.print("[dim]Auto-refresh enabled ✓[/dim]")
            else:
                console.print("[yellow]Warning: No refresh token received.[/yellow]")
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")

    asyncio.run(perform_login())


@app.command
def whoami() -> None:
    """Check current authentication status."""
    creds = load_credentials()
    if not creds or not creds.token:
        console.print("[yellow]Not logged in. Run 'calm login' first.[/yellow]")
        return

    console.print(f"[dim]{creds!r}[/dim]")

    async def check() -> None:
        try:
            async with CalmClient(creds) as client:
                if await _check_auth(client):
                    console.print("[green]Logged in and authenticated.[/green]")
                    # Persist refreshed credentials if auto-refresh occurred
                    if client.credentials.token != creds.token:
                        save_credentials(client.credentials)
                        console.print("[dim]Token was refreshed and saved.[/dim]")
                else:
                    console.print("[red]Token is invalid or expired. Please run 'calm login' again.[/red]")
        except Exception as e:
            console.print(f"[red]Error checking status: {e}[/red]")

    asyncio.run(check())


@app.command
def logout() -> None:
    """Log out by clearing stored credentials."""
    save_credentials(None)
    console.print("Logged out successfully.")


@app.command
def search(query: Annotated[str, cyclopts.Parameter(name="query")]) -> None:
    """Search the Calm catalog."""
    creds = load_credentials()
    if not creds or not creds.token:
        console.print("[yellow]Not logged in. Run 'calm login' first.[/yellow]")
        return

    async def perform_search() -> None:
        try:
            async with CalmClient(creds) as client:
                with console.status(f"Searching for '{query}'..."):
                    results = await client.search(query)

                if not results.items:
                    console.print("[yellow]No results found.[/yellow]")
                    return

                table = Table(title=f"Search Results: {query} ({results.total_item_number} total)")
                table.add_column("ID", style="cyan")
                table.add_column("Category", style="magenta")
                table.add_column("Type", style="blue")
                table.add_column("Title", style="bold white")
                table.add_column("Subtitle", style="dim")

                for item in results.items:
                    table.add_row(
                        item.program_id or item.content_id or "",
                        item.search_category or "",
                        item.item_type,
                        item.title,
                        item.subtitle or "",
                    )

                console.print(table)

                # Persist refreshed credentials if auto-refresh occurred
                if client.credentials.token != creds.token:
                    save_credentials(client.credentials)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    asyncio.run(perform_search())


@app.command
def play(program_id: str, *, guide: int = 0) -> None:
    """Play audio from a Calm program.

    Args:
        program_id: The program ID (e.g. from search or browse).
        guide: Which guide/track index to play (0-indexed). Default: first.
    """
    from .play import run_play

    creds = load_credentials()
    if not creds or not creds.token:
        console.print("[yellow]Not logged in. Run 'calm login' first.[/yellow]")
        return

    async def fetch_program() -> Program:
        client = CalmClient(creds)
        try:
            if client.credentials.token != creds.token:
                save_credentials(client.credentials)
            return await client.get_program(program_id)
        finally:
            await client.close()

    console.print(f"[dim]Fetching program {program_id}...[/dim]")
    try:
        program = asyncio.run(fetch_program())
    except Exception as e:
        console.print(f"[red]Error fetching program: {e}[/red]")
        return

    if not program.guides:
        console.print("[red]No guides/tracks found in this program.[/red]")
        return

    if guide >= len(program.guides):
        console.print(f"[red]Guide index {guide} out of range (0-{len(program.guides) - 1}).[/red]")
        return

    track = program.guides[guide]
    stream_url = track.stream_url
    if not stream_url:
        console.print("[red]No streamable audio found for this track.[/red]")
        return

    console.print(f"\n[bold]{program.title}[/bold]")
    console.print(f"[dim]Track:[/dim] {track.title}")
    console.print(f"[dim]URL:[/dim]   {stream_url[:60]}...")
    console.print()

    # Launch the play TUI
    run_play(program, guide)


@app.command
def browse() -> None:
    """Browse the Calm catalog interactively."""
    from .browse import run_browse

    creds = load_credentials()
    if not creds or not creds.token:
        console.print("[yellow]Not logged in. Run 'calm login' first.[/yellow]")
        return

    client = CalmClient(creds)
    run_browse(client)


if __name__ == "__main__":
    app.meta()
