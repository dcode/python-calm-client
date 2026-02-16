# Contributing to calm-client

Thanks for your interest! This guide covers local development setup.

## Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [mpv](https://mpv.io/) — required for audio playback features

## Setup

```bash
# Clone the repository
git clone https://github.com/dcode/python-calm-client.git
cd python-calm-client

# Install dependencies (creates a virtualenv automatically)
uv sync --all-extras --all-groups
```

## Development Workflow

```bash
# Run tests
uv run hatch test

# Lint & format
uv run hatch fmt        # auto-fix
uv run hatch fmt --check  # check only

# Type check
uv run hatch run typing:check

# Build package
uv run hatch build
```

## Code Style

- **Formatter/Linter**: [Ruff](https://docs.astral.sh/ruff/) — configured in `pyproject.toml`
- **Type Checker**: [mypy](https://mypy-lang.org/) — strict mode enabled
- **Docstrings**: Google style

## Running a Subset of Tests

```bash
# Run a specific test file
uv run pytest tests/test_client.py -v

# Run tests matching a pattern
uv run pytest -k "test_login" -v
```
