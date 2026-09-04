from __future__ import annotations

from src.publisher.richtext import (
    LINK_FACET_TYPE,
    TAG_FACET_TYPE,
    merge_facets,
    post_langs,
    tag_facets,
)


def _slice(text: str, facet: dict) -> str:
    idx = facet["index"]
    return text.encode("utf-8")[idx["byteStart"] : idx["byteEnd"]].decode("utf-8")


def test_tag_facets_cover_every_hashtag_with_byte_offsets() -> None:
    text = "Ollama ships MLX.\n\n#OpenSource #Ollama #LocalLLM\n\n🔗 https://example.com/x"
    facets = tag_facets(text)
    assert [f["features"][0]["tag"] for f in facets] == ["OpenSource", "Ollama", "LocalLLM"]
    assert all(f["features"][0]["$type"] == TAG_FACET_TYPE for f in facets)
    assert [_slice(text, f) for f in facets] == ["#OpenSource", "#Ollama", "#LocalLLM"]


def test_tag_facets_use_utf8_offsets_after_multibyte_text() -> None:
    text = "Größeres Modell 🚀 läuft lokal #LocalLLM"
    (facet,) = tag_facets(text)
    assert _slice(text, facet) == "#LocalLLM"
    # byte offsets differ from character offsets here — that is the point
    assert facet["index"]["byteStart"] > text.index("#LocalLLM")


def test_tag_facets_strip_trailing_punctuation_and_skip_numeric_or_inline_hashes() -> None:
    text = "Great #AI, really #MCP. issue #123 and a#b or url https://x.y/a#frag #Anthropic"
    facets = tag_facets(text)
    assert [f["features"][0]["tag"] for f in facets] == ["AI", "MCP", "Anthropic"]
    assert [_slice(text, f) for f in facets] == ["#AI", "#MCP", "#Anthropic"]


def test_tag_facets_ignore_overlong_tags_and_bare_hash() -> None:
    assert tag_facets("# nothing") == []
    assert tag_facets("#" + "x" * 65) == []
    assert tag_facets("#" + "x" * 64)[0]["features"][0]["tag"] == "x" * 64


def test_merge_facets_orders_by_start_and_drops_overlaps() -> None:
    link = {"index": {"byteStart": 10, "byteEnd": 30}, "features": [{"$type": LINK_FACET_TYPE, "uri": "https://a"}]}
    tag_before = {"index": {"byteStart": 0, "byteEnd": 3}, "features": [{"$type": TAG_FACET_TYPE, "tag": "AI"}]}
    tag_inside_link = {"index": {"byteStart": 12, "byteEnd": 18}, "features": [{"$type": TAG_FACET_TYPE, "tag": "frag"}]}
    merged = merge_facets([link], [tag_before, tag_inside_link])
    assert merged == [tag_before, link]


def test_post_langs_default_env_and_cap(monkeypatch) -> None:
    monkeypatch.delenv("BOARDWIRE_POST_LANGS", raising=False)
    assert post_langs() == ["en"]
    monkeypatch.setenv("BOARDWIRE_POST_LANGS", " en, de ,,en, fr, it")
    assert post_langs() == ["en", "de", "fr"]
    assert post_langs("") == ["en"]
