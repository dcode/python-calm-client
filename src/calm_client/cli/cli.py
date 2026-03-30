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
    from calm_client.models import CalmAlbum

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
    """Check if current token is valid."""
    try:
        await client._request("GET", "packs/feeds/sleep")
        return True
    except CalmAuthError:
        return False


def _extract_email_from_token(token: str) -> str | None:
    """Extract email from a JWT id_token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(decoded)
        email = data.get("email")
        return cast("str", email) if email is not None else None
    except Exception:
        return None


@app.command
def login() -> None:
    """Interactive login."""
    console.print("[bold blue]Calm Client Login[/bold blue]")
    default_email = os.environ.get("CALM_EMAIL")
    if not default_email:
        creds = load_credentials()
        if creds and creds.id_token:
            default_email = _extract_email_from_token(creds.id_token)
    email = Prompt.ask("Email", console=console, default=default_email)
    password = os.environ.get("CALM_PASSWORD") or Prompt.ask("Password", console=console, password=True)
    if not email or not password:
        console.print("[red]Email and password are required.[/red]")
        return

    async def perform_login() -> None:
        try:
            existing_creds = load_credentials()
            session_token = existing_creds.session_token if existing_creds else None
            async with CalmClient(existing_creds) as client:
                with console.status("Logging in..."):
                    creds = await client.login(email, password)
            if session_token and not creds.session_token:
                creds.session_token = session_token
            save_credentials(creds)
            console.print(f"[green]Success! Logged in as {email}[/green]")
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")

    asyncio.run(perform_login())


@app.command
def whoami() -> None:
    """Check status."""
    creds = load_credentials()
    if not creds or not creds.token:
        console.print("[yellow]Not logged in.[/yellow]")
        return
    async def check() -> None:
        try:
            async with CalmClient(creds) as client:
                if await _check_auth(client):
                    console.print("[green]Authenticated.[/green]")
                    if client.credentials.token != creds.token:
                        save_credentials(client.credentials)
                else:
                    console.print("[red]Expired. Login again.[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    asyncio.run(check())


@app.command
def logout() -> None:
    """Log out."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    console.print("Logged out.")


@app.command
def search(query: Annotated[str, cyclopts.Parameter(name="query")]) -> None:
    """Search catalog."""
    creds = load_credentials()
    if not creds:
        return
    async def perform_search() -> None:
        try:
            async with CalmClient(creds) as client:
                results = await client.search(query)
                if not results.items:
                    console.print("[yellow]No results.[/yellow]")
                    return
                table = Table(title=f"Search Results: {query}")
                table.add_column("ID", style="cyan")
                table.add_column("Category", style="magenta")
                table.add_column("Type", style="blue")
                table.add_column("Title", style="bold white")
                table.add_column("Subtitle", style="dim")
                for item in results.items:
                    table.add_row(
                        item.id,
                        item.search_category or "",
                        item.item_type,
                        item.title,
                        item.subtitle or "",
                    )
                console.print(table)
                if client.credentials.token != creds.token:
                    save_credentials(client.credentials)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    asyncio.run(perform_search())


@app.command
def play(program_id: str, *, guide: int = 0) -> None:
    """Play audio."""
    from .play import run_play
    creds = load_credentials()
    if not creds:
        return
    async def fetch_program() -> CalmAlbum:
        async with CalmClient(creds) as client:
            prog = await client.get_program(program_id)
            if client.credentials.token != creds.token:
                save_credentials(client.credentials)
            return prog
    try:
        program = asyncio.run(fetch_program())
        if not program.guides:
            console.print("[red]No tracks.[/red]")
            return
        track = program.guides[guide]
        console.print(f"\n[bold]{program.title}[/bold]")
        console.print(f"[dim]Track:[/dim] {track.title}")
        run_play(program, guide)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@app.command
def browse() -> None:
    """Browse catalog."""
    from .browse import run_browse
    creds = load_credentials()
    if not creds:
        return
    run_browse(CalmClient(creds))


if __name__ == "__main__":
    app.meta()
