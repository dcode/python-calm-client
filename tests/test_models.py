from calm_client.models import Asset, Guide, PackItem, PackItemAsset, Program


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
