# Calm Client (Python)

[![CI](https://github.com/dcode/python-calm-client/actions/workflows/ci.yml/badge.svg)](https://github.com/dcode/python-calm-client/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/calm-client.svg)](https://pypi.org/project/calm-client/)
[![Python](https://img.shields.io/pypi/pyversions/calm-client.svg)](https://pypi.org/project/calm-client/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Async Python client and CLI for the internal Calm.com API. Browse the catalog,
search for content, and stream audio — all from your terminal.

## Features

- **CLI + TUI** — Browse, search, and play Calm content from the terminal
- **Async API** — Fully async Python client built on `httpx`
- **Type Safe** — Comprehensive Pydantic models with `py.typed` support
- **Audio Playback** — Stream meditation and sleep audio via `mpv`
- **Audio Download** — Download Calm programs/playlists as numbered WAV files plus a generated M3U playlist with metadata
- **Auth** — Email/password login with automatic token refresh

## Installation

### CLI (recommended)

Use [pipx](https://pipx.pypa.io/) to install the CLI in an isolated environment
with zero hassle — no virtualenv management needed:

```bash
# Full CLI with audio playback (play, browse) — needs mpv, see Requirements
pipx install 'calm-client[player]'

# CLI and TUI browser without audio playback (login, search, whoami, browse)
pipx install 'calm-client[cli]'
```

### Library

If you want to use `calm-client` as a Python library in your own project:

```bash
pip install calm-client
```

The plain package installs only the API client and its few dependencies (`httpx`,
`pydantic`, `structlog`). The `cli` and `player` extras add the terminal UI and audio
playback.

| Install | You get |
|---|---|
| `calm-client` | Async API client library |
| `calm-client[cli]` | + `calm` command and TUI browser |
| `calm-client[player]` | + audio playback in `calm play` / `calm browse` |

## Requirements

- **Python 3.12+** - for modern typing, async, and f-strings

- **mpv** — Required for `calm play` and `calm browse` audio features (the `player`
  extra loads mpv's `libmpv` library)

    ```bash
    # Ubuntu/Debian
    sudo apt install mpv libmpv-dev

    # macOS
    brew install mpv

    # Arch
    sudo pacman -S mpv
    ```

## Quick Start (CLI)

```bash
# 1. Login
calm login

# 2. Browse interactively
calm browse

# 3. Or search and play directly
calm search "Sleep Stories"
calm play <program_id>
```

## Download Tracks

Download any Calm program (playlist) as lossless WAV files — all tracks are
numbered automatically and an M3U playlist with metadata (title, artist,
duration) is created next to the downloads:

```bash
# Download every track in a program
calm download Cylx9JvEbQ

# Download a specific track
calm download Cylx9JvEbQ --guide 3

# Download a range of tracks (2 through 5)
calm download Cylx9JvEbQ --start 2 --end 5

# Choose quality: compact (AAC, ~30 MB), balanced (Vorbis, ~50 MB) or highest (lossless WAV, ~500 MB)
calm download Cylx9JvEbQ --quality highest
```

Example output:

```
01 Hawaiian Slack Key Guitar
Downloaded 1/17 — 01 Hawaiian_Slack_Key_Guitar.wav
02 Two Paniolos
Downloaded 2/17 — 02 Two_Paniolos.wav
...
Downloaded all 17 tracks as WAV files.
Created playlist: Hawaiian_Slack_Key_Guitar.m3u
```

`Hawaiian_Slack_Key_Guitar.m3u`:

```m3u
#EXTM3U
#EXTINF:300,Kainalu - Two Paniolos
02 Two_Paniolos.wav
#EXTINF:300,Kainalu - Nani Kaua'i
03 Nani_Kauai.wav
...
```

## Documentation

## Quick Start (Python)

```python
import asyncio
from calm_client import CalmClient


async def main():
    async with CalmClient() as client:
        # Authenticate
        await client.login("email@example.com", "password")

        # Get the Sleep feed
        feed = await client.get_feed("sleep")
        print(f"Found {len(feed.items)} items")

        # Search
        results = await client.search("Rain")
        print(f"Found {len(results.items)} results")


if __name__ == "__main__":
    asyncio.run(main())
```

## Documentation

- [**CLI Reference**](docs/cli.md) — Commands, options, and TUI controls
- [**Library Reference**](docs/library.md) — Python API, classes, and models

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development setup.

```bash
# Quick start
uv sync --all-extras --all-groups
uv run hatch test
uv run hatch fmt
```

## License

[MIT](LICENSE)
