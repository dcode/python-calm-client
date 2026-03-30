"""Tests for the Calm API data models."""

import json
from pathlib import Path

import pytest
from calm_client.models import CalmAlbum, CalmFeed, CalmFolder, CalmTrack, MediaType

DATA_DIR = Path(__file__).parent.parent / "data"

@pytest.mark.parametrize("filename", [
    "00_res_home.json",
    "05_res_meditate.json",
    "11_res_feed-music.json",
    "14_res_sleep.json",
])
def test_parse_feed(filename: str) -> None:
    """Test parsing a feed response."""
    path = DATA_DIR / filename
    if not path.exists():
        pytest.skip(f"Data file {filename} not found")
    
    with open(path) as f:
        data = json.load(f)
    
    feed_data = data.get("feed", data)
    feed = CalmFeed.model_validate(feed_data)
    
    assert feed.packs
    for pack in feed.packs:
        assert pack.id
        assert pack.media_type == MediaType.FOLDER
        # Items in packs should be parsed
        for item in pack.items:
            assert item.id
            assert item.title

@pytest.mark.parametrize("filename", [
    "13_res_programs-mWQTNfEI3T.json",
    "18_res_content_programs_4y-Py0EzS.json",
    "19_res_content_programs_QDsu5h6LOO.json",
])
def test_parse_program(filename: str) -> None:
    """Test parsing a program response."""
    path = DATA_DIR / filename
    if not path.exists():
        pytest.skip(f"Data file {filename} not found")
    
    with open(path) as f:
        data = json.load(f)
    
    program = CalmAlbum.model_validate(data["program"])
    assert program.id
    assert program.title
    assert program.guides
    for guide in program.guides:
        assert guide.id
        assert guide.title

def test_parse_search_results() -> None:
    """Test parsing search results."""
    path = DATA_DIR / "08_res_search-binaural.json"
    if not path.exists():
        pytest.skip("Data file 08_res_search-binaural.json not found")
    
    with open(path) as f:
        data = json.load(f)
    
    pack = CalmFolder.model_validate(data["pack"])
    assert pack.items
    for item in pack.items:
        assert item.id
        assert item.title

def test_wonky_program_is_track() -> None:
    """Test the heuristic that a single-track program is a TRACK media type."""
    guide = CalmTrack(
        id="g1",
        title="Single Track",
        type="guide",
        assets=[]
    )
    album = CalmAlbum(
        id="p1",
        title="Single CalmAlbum",
        type="program",
        guides=[guide]
    )
    
    assert album.media_type == MediaType.TRACK

def test_course_is_album() -> None:
    """Test that a course is an ALBUM even if it has one guide loaded."""
    guide = CalmTrack(
        id="g1",
        title="Lesson 1",
        type="guide",
        assets=[]
    )
    album = CalmAlbum(
        id="p1",
        title="7 Days of Focus",
        type="program",
        content_type="Course",
        guides=[guide]
    )
    
    assert album.media_type == MediaType.ALBUM
