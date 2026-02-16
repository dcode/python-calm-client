# CLI Reference

The `calm-client` package includes a powerful command-line interface (CLI) for
interacting with Calm.com directly from your terminal.

## Installation

The CLI is installed automatically when you install the package.

**Recommended** — install with [pipx](https://pipx.pypa.io/) for an isolated
environment:

```bash
pipx install 'calm-client[player]'
```

Or with pip:

```bash
pip install 'calm-client[player]'
```

## Global Options

All commands support the following global options:

- `--debug`: Enable DEBUG logging (very verbose).
- `--verbose`: Enable INFO logging.
- `--version`: Display application version.
- `--help`: Display help message.

## Environment Variables

The CLI supports the following environment variables to streamline
authentication:

- `CALM_EMAIL`: Default email address for login.
- `CALM_PASSWORD`: Password for login (bypasses interactive prompt).
- `CALM_USER_TOKEN`: Pre-authenticated token (can be used instead of login).

## Commands

### `login`

Authenticate with Calm.com. This command stores your credentials locally for
subsequent commands.

```bash
calm login
```

**Methods:**

1. **Email/Password**: Standard login flow.
1. **Token Paste**: If you have a valid `calm-user-token` cookie from your
    browser, you can paste it directly.

### `browse`

Launch the interactive Terminal User Interface (TUI) to browse the catalog.

```bash
calm browse
```

**Controls:**

- `Arrow Keys`: Navigate
- `Enter`: Select/Play
- `Escape`: Back
- `f`: Toggle Favorite
- `q`: Quit

### `search`

Search the Calm catalog for programs, tracks, or meditations.

```bash
calm search "Sleep Stories"
```

### `play`

Play a specific program or track by ID.

```bash
# Play a program (defaults to first guide/track)
calm play <program_id>

# Play a specific guide index (0-based)
calm play <program_id> --guide 2
```

**Controls:**

- `Space`: Pause/Resume
- `Left/Right`: Seek +/- 10s
- `q`: Quit

### `whoami`

Check your current authentication status and token validity.

```bash
calm whoami
```
