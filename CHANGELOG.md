# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] — Unreleased

### Added

- `CalmClient.get_playlists()` returns the user's playlists ("My Collections");
  `add_fave()` / `remove_fave()` favorite or unfavorite a guide, program, feed, pack
  or content item. The browse TUI's My Collections card now opens your playlists
  (contents hydrated with titles), alongside Favorites on the Home screen.
- `CalmClient.browse()` walks the catalog as a tree of feeds, packs, programs and
  guides, so integrations don't have to interpret feeds themselves.
- `CalmClient.get_pack()`, `get_guide()` (a guide with its program and lock flags) and
  `get_guide_summary()`.
- `MediaType` and `PackItem.media_type` / `PackItem.path` classify catalog entries;
  `is_available()` tells whether the account can play them.
- `Guide.audio_asset` / `PackItem.audio_asset` pick the preferred audio format.
- Models keep more of Calm's data: lock flags in both spellings (`is_unlocked`/`unlocked`,
  `is_free`/`free`), program narrators and cover images, guide positions and narrators,
  and feed tags.

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

- `calm browse` Home: the Favorites card opens your favorites (it was always empty);
  Recently Played and My Collections, which Calm's apps fill in through endpoints the
  client doesn't have, are hidden instead of showing empty; untitled rows get their
  names ("Navigation", "Today's Daily Calm"); entries that link to a feed or pack open
  it; and a guide entry such as today's Daily Calm plays that guide instead of the first
  one in its program.
- The `calm browse` sidebar icons are all double-width, so the category names line up.
- `calm browse` showed at most about 10 items per collection: feeds only embed a
  preview of each pack. Opening a pack now loads all of its items (e.g. 263 Sleep
  Stories in Fiction instead of 10), and cards show "10+ items" until then.
- `Guide.stream_url` prefers compressed audio over wav and no longer picks a video
  asset when audio is available.

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
