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
- `get_feed(category_id: str) -> Feed`: Get a category feed
    (e.g., "sleep", "meditate").
- `get_category_feed(category_id: str) -> FeedResponse`: Get a category feed with
    all of its packs and tags.
- `get_program(program_id: str) -> Program`: Get details for a program.
- `get_pack(pack_class: str) -> Pack`: Get a pack (a row of a feed) with all of its items.
    Packs embedded in a feed only hold a preview (about 10 items); use this for the rest.
- `get_guide(guide_id: str) -> tuple[Guide, Program]`: Get a guide with its audio
    assets, plus its program carrying the account's lock flags.
- `get_guide_summary(guide_id: str) -> GuideSummary`: Get a guide's program id and
    lock flags without the program details.
- `get_favorites() -> list[PackItem]`: Get user's favorite items.
- `get_playlists() -> list[Playlist]`: Get the user's playlists ("My Collections").
- `list_narrators() -> list[SearchItem]`: List narrators and artists (each a `FOLDER`
    item whose `path` opens the narrator's feed).
- `add_fave(*, guide_id=.. | program_id=.. | feed_id=.. | pack_class=.. | content_id=..)`
    and `remove_fave(...)`: favorite or unfavorite one item. Guides use the
    `programs/guides/<id>/faves` endpoint; everything else uses `/faves`.
- `browse(path: str = "") -> list[PackItem]`: Walk the catalog as a tree (see below).

### Browsing

`browse()` gives integrations (media servers, voice assistants, …) one tree to walk
instead of interpreting feeds themselves:

| Path | Entries |
|------|---------|
| `""` | the categories in `DEFAULT_CATEGORIES`, as feeds |
| `"feed/<feed_id>"` | the feed's packs that hold guides or programs, then its tags |
| `"pack/<pack_class>"` | the pack's items |

Each entry has a `media_type`: `TRACK` (a guide), `ALBUM` (a program), `FOLDER` (a
sub-feed or sub-pack; browse its `path` next) or `UNKNOWN` (promos and other entries
without audio, which you will usually skip).

```python
from calm_client import MediaType, is_available

for entry in await client.browse("feed/sleep"):
    print(entry.title, entry.path)

for entry in await client.browse("pack/sleep-stories"):
    if entry.media_type is MediaType.TRACK and entry.guide_id:
        guide, program = await client.get_guide(entry.guide_id)
        if is_available(guide, program):
            print(guide.title, guide.stream_url)
```

### Models

The library uses Pydantic models for type safety:

- `Program`: Represents a collection (album/playlist), with its narrator, cover
    image (`image_url`) and guides (`sorted_guides` in play order).
- `Guide`: Represents a single track/episode within a program. `audio_asset` and
    `stream_url` prefer compressed audio (m4a, then mp3, ogg, wav) and skip video.
- `Feed` / `FeedResponse`: A category feed: its packs and its tags (links to sub-feeds
    and packs).
- `Pack` / `PackItem`: A row of a feed and its entries.
- `SearchItem`: A result from a search query (the same shape as a `PackItem`).
- `PackItem.media_type` is `FOLDER` for sub-feeds, sub-packs and narrators/artists, and
    `PackItem.path` is the `browse()` path to open next (a narrator resolves to
    `feed/narrator-<id>`). `Pack.has_content` tells whether a row has anything to open.
- `Playlist` / `PlaylistItem`: A user playlist and its entries. Items hold only
    `guide_id`/`program_id`; resolve them with `get_guide`. `image_url` gives the cover.

Programs, guides and items carry Calm's lock flags as `is_unlocked` and `is_free`,
whichever spelling the response used. Use `is_available(guide, program)` to decide
whether the account can play something. Program details have no lock flags of their
own, so content with no flags at all counts as available.

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
