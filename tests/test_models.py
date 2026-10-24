import pytest

from calm_client.models import (
    Asset,
    FeedTag,
    Guide,
    ImageAsset,
    MediaType,
    Narrator,
    Pack,
    PackItem,
    PackItemAsset,
    Program,
    is_available,
)


def test_guide_stream_url() -> None:
    assert Guide(id="g", title="t").stream_url is None
    guide = Guide(id="g", title="t", assets=[Asset(url="u", content_type="audio/mp4", duration=1)])
    assert guide.stream_url == "u"


def test_program_first_stream_url() -> None:
    assert Program(id="p", title="t").first_stream_url is None
    guide = Guide(id="g", title="t", assets=[Asset(url="u", content_type="audio/mp4", duration=1)])
    assert Program(id="p", title="t", guides=[guide]).first_stream_url == "u"


def test_pack_item_display_id_fallbacks() -> None:
    assert PackItem(program_id="p", guide_id="g").display_id == "p"
    assert PackItem(guide_id="g", content_id="c").display_id == "g"
    assert PackItem(content_id="c").display_id == "c"
    assert PackItem().display_id == ""


def test_pack_item_duration_str() -> None:
    def item(seconds: float) -> PackItem:
        return PackItem(assets=[PackItemAsset(url="u", duration=seconds)])

    assert PackItem().duration_str == ""
    assert item(0).duration_str == ""
    assert item(59).duration_str == "0m"
    assert item(25 * 60).duration_str == "25m"
    assert item(90 * 60).duration_str == "1h 30m"


def test_lock_flags_accept_either_spelling() -> None:
    assert PackItem.model_validate({"unlocked": True}).is_unlocked
    assert PackItem.model_validate({"free": True}).is_free
    assert PackItem(is_unlocked=True).is_unlocked


def test_is_available() -> None:
    locked = PackItem.model_validate({"is_unlocked": False})
    free = PackItem.model_validate({"is_unlocked": False, "is_free": True})
    no_flags = Program(id="p", title="t")
    assert not locked.is_available
    assert free.is_available
    # program detail responses carry no lock flags: treat as available
    assert no_flags.is_available
    locked_program = Program.model_validate({"id": "p", "title": "t", "unlocked": False})
    assert not is_available(Guide(id="g", title="t"), locked_program)
    assert is_available(Guide.model_validate({"id": "g", "title": "t", "free": True}), locked)


def test_preferred_audio_asset() -> None:
    assets = [
        Asset(url="video", content_type="video/mp4"),
        Asset(url="wav", content_type="audio/wav"),
        Asset(url="m4a", content_type="audio/mp4"),
        Asset(url="", content_type="audio/mpeg"),
    ]
    guide = Guide(id="g", title="t", assets=assets)
    assert guide.audio_asset is not None
    assert guide.stream_url == "m4a"
    # without any audio, fall back to the first asset as before
    assert Guide(id="g", title="t", assets=assets[:1]).stream_url == "video"
    assert PackItem(assets=[PackItemAsset(url="a", content_type="audio/ogg")]).audio_asset is not None
    assert PackItem().audio_asset is None


def test_program_details() -> None:
    program = Program.model_validate(
        {
            "id": "p",
            "title": "t",
            "narrator": {"id": "n1", "name": "Tamara", "headshot": {"url": "h"}},
            "image": {"url": "img"},
            "cell_image": {"url": ""},
            "guides": [{"id": "b", "title": "B", "position": 2}, {"id": "a", "title": "A", "position": 1}],
        }
    )
    assert program.narrator_name == "Tamara"
    assert program.image_url == "img"
    assert [g.id for g in program.sorted_guides] == ["a", "b"]
    assert Program(id="p", title="t", narrator="Jay").narrator_name == "Jay"
    assert Program(id="p", title="t").narrator_name is None
    assert Program(id="p", title="t").image_url is None


@pytest.mark.parametrize(
    ("data", "media_type", "path"),
    [
        ({"type": "guide", "guide_id": "g"}, MediaType.TRACK, None),
        ({"type": "program", "program_id": "p"}, MediaType.ALBUM, None),
        ({"type": "pack", "pack_class": "c"}, MediaType.FOLDER, "pack/c"),
        ({"type": "feed", "feed_id": "f"}, MediaType.FOLDER, "feed/f"),
        ({"type": "guide"}, MediaType.UNKNOWN, None),
        ({"type": "promo", "pack_class": "c"}, MediaType.UNKNOWN, None),
    ],
)
def test_pack_item_media_type_and_path(data: dict[str, str], media_type: MediaType, path: str | None) -> None:
    item = PackItem.model_validate(data)
    assert item.media_type is media_type
    assert item.path == path


def test_pack_item_display_id_folders() -> None:
    assert PackItem(pack_class="c").display_id == "c"
    assert PackItem(feed_id="f").display_id == "f"


def test_feed_tag_path() -> None:
    assert FeedTag(feed_id="f").path == "feed/f"
    assert FeedTag(pack_class="c").path == "pack/c"
    assert FeedTag().path is None


def test_pack_has_playable_items() -> None:
    assert Pack(items=[PackItem.model_validate({"type": "guide", "guide_id": "g"})]).has_playable_items
    assert not Pack(items=[PackItem.model_validate({"type": "promo"})]).has_playable_items


def test_narrator_item_is_a_browsable_folder() -> None:
    item = PackItem.model_validate({"type": "narrator", "narrator_id": "VkYG-ZSmX", "title": "Tamara Levitt"})
    assert item.media_type is MediaType.FOLDER
    assert item.path == "feed/narrator-VkYG-ZSmX"


def test_pack_has_content_vs_playable() -> None:
    # a row of only links/breathe/text has nothing to open
    links = Pack(items=[PackItem.model_validate({"type": "url"}), PackItem.model_validate({"type": "breathe_bubble"})])
    assert not links.has_content
    assert not links.has_playable_items
    # a navigation row of sub-feeds is browsable but has nothing directly playable
    nav = Pack(items=[PackItem.model_validate({"type": "feed", "feed_id": "sleep"})])
    assert nav.has_content
    assert not nav.has_playable_items
    # a guide row is both
    guides = Pack(items=[PackItem.model_validate({"type": "guide", "guide_id": "g"})])
    assert guides.has_content
    assert guides.has_playable_items


def test_duration_prefers_the_audio_asset_over_the_first_asset() -> None:
    video = {"url": "v", "content_type": "video/mp4", "duration": 5}
    wav = {"url": "w", "content_type": "audio/wav", "duration": 60}
    m4a = {"url": "m", "content_type": "audio/mp4", "duration": 59}
    guide = Guide.model_validate({"id": "g", "title": "t", "assets": [video, wav, m4a]})
    assert guide.duration == 59
    item = PackItem.model_validate({"assets": [video, wav, m4a]})
    assert item.duration == 59
    assert item.duration_str == "0m"


def test_duration_falls_back_to_the_first_asset_and_to_zero() -> None:
    only_video = [{"url": "v", "content_type": "video/mp4", "duration": 90}]
    assert Guide.model_validate({"id": "g", "title": "t", "assets": only_video}).duration == 90
    assert Guide(id="g", title="t").duration == 0.0
    assert PackItem().duration == 0.0


def test_pack_item_image_url_and_display_subtitle() -> None:
    assert PackItem().image_url is None
    assert PackItem(image=ImageAsset()).image_url is None
    assert PackItem(image=ImageAsset(url="u")).image_url == "u"
    assert PackItem(narrator_name="Jay", subtitle="Sleep").display_subtitle == "Jay"
    assert PackItem(subtitle="Sleep").display_subtitle == "Sleep"
    assert PackItem().display_subtitle == ""


def test_artist_is_the_same_shape_on_every_model() -> None:
    from_item = PackItem(narrator_id="n1", narrator_name="Jay").artist
    from_guide = Guide(id="g", title="t", narrator_id="n1", narrator_name="Jay").artist
    from_string = Program(id="p", title="t", narrator="Jay", narrator_id="n1").artist
    from_object = Program(id="p", title="t", narrator=Narrator(id="n1", name="Jay")).artist
    assert from_item == from_guide == from_string == from_object == Narrator(id="n1", name="Jay")
    assert PackItem().artist is None
    assert Guide(id="g", title="t").artist is None
    assert Program(id="p", title="t").artist is None


def test_artist_without_an_id_and_narrator_image_url() -> None:
    assert PackItem(narrator_name="Jay").artist == Narrator(id=None, name="Jay")
    assert Narrator(name="Jay").image_url is None
    assert Narrator(name="Jay", headshot=ImageAsset()).image_url is None
    assert Narrator(name="Jay", headshot=ImageAsset(url="h")).image_url == "h"
