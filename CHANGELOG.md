# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] — Unreleased

### Changed

- **Breaking:** the CLI/TUI dependencies (`cyclopts`, `rich`, `textual`,
  `platformdirs`) moved to a new `cli` extra, so the library installs only `httpx`,
  `pydantic` and `structlog`. Install the CLI with `pipx install 'calm-client[player]'`
  (or `[cli]` without audio). The `player` extra now includes `cli`.
- `calm` (and `python -m calm_client`) explains which extra to install instead of
  failing with an ImportError.
- `uv sync` / `uv run calm` in a checkout now include the `player` extra (via the dev
  dependency group).
- Library logging goes through the stdlib `calm_client` logger, and credentials are
  redacted from all log output.

### Fixed

- A missing libmpv is reported with install instructions instead of an `OSError`
  traceback; the python-mpv hint no longer prints a literal `\n`.
- `get_feed()` accepts the current packs-based feed response.

### Removed

- The unused `orjson` dependency.

## [0.1.0] — 2025-02-15

### Added

- Async Python client (`CalmClient`) for the Calm.com internal API
- CLI with `login`, `search`, `play`, `browse`, and `whoami` commands
- Interactive TUI browser powered by [Textual](https://textual.textualize.io/)
- Audio playback via [mpv](https://mpv.io/) with play/pause/seek controls
- OAuth2 authentication with Auth0 (email/password login + token refresh)
- Credential persistence via platform-appropriate config directory
- Pydantic models for feeds, programs, guides, search results, and more
- GitHub Actions CI (lint, type check, test) and PyPI publishing workflow
