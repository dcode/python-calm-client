# Python Library Reference

`calm-client` provides an async Python client for the Calm.com API.

## Installation

```bash
pip install calm-client
```

## Quick Start

```python
import asyncio
from calm_client import CalmClient

async def main():
    # 1. Initialize client
    # Login with credentials
    async with CalmClient() as client:
        creds = await client.login("email@example.com", "password")
        print(f"Logged in with token: {creds.token}")

    # OR use an existing token
    async with CalmClient("your_token_here") as client:
        # 2. Fetch Data
        feed = await client.get_feed("sleep")
        for item in feed.items:
            print(f"{item.title} ({item.id})")

if __name__ == "__main__":
    asyncio.run(main())
```

## Core Classes

### `CalmClient`

The main entry point for the API.

**Constructor:**
```python
CalmClient(credentials: Credentials | str | None = None)
```

**Methods:**

- `login(email, password) -> Credentials`: Authenticate and return credentials.
- `search(query: str) -> SearchResponse`: Search the catalog.
- `get_feed(category_id: str) -> FeedResponse`: Get a category feed (e.g., "sleep", "meditate").
- `get_program(program_id: str) -> Program`: Get details for a program.
- `get_favorites() -> list[PackItem]`: Get user's favorite items.

### Models

The library uses Pydantic models for type safety:

- `Program`: Represents a collection (album/playlist).
- `Guide`: Represents a single track/episode within a program.
- `Feed`: A list of catalog items.
- `SearchItem`: A result from a search query.

## Error Handling

```python
from calm_client import CalmAuthError, CalmAPIError

try:
    await client.get_feed("invalid")
except CalmAuthError:
    print("Authentication failed")
except CalmAPIError as e:
    print(f"API Error: {e}")
```
