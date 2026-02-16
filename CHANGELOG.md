# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
