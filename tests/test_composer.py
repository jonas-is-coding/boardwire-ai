from __future__ import annotations

from src.composer import (
    BLUESKY_MAX_BYTES,
    byte_len,
    compose_post_body,
    select_format_variant,
    shorten_at_word_boundary,
    validate_question,
)
from src.main import _compose_sarah_post
from src.publisher.bluesky_publisher import _compose_text_with_link

LONG_TITLE = "Coding agents are getting persistent memory as a first-class infrastructure primitive."
LONG_SUBTITLE = (
    "Agentmemory turns recall into persistent state for coding-agent workflows, "
    "with a 4-tier progressive pipeline and zero external API dependencies today."
)
LINK = "https://github.com/example/agentmemory-project/releases/tag/v1.2.3"
TAGS = ["#AI", "#AIAgents", "#MCP"]


def test_shorten_noop_when_within_budget() -> None:
    assert shorten_at_word_boundary("short text.", 100) == "short text."


def test_shorten_never_cuts_mid_word() -> None:
    text = "Supercalifragilistic expialidocious extraordinary announcement"
    shortened = shorten_at_word_boundary(text, 40)
    assert byte_len(shortened) <= 40
    # Every word in the output must be a complete word of the input.
    for word in shortened.rstrip("…").split():
        assert word in text.split()
    assert shortened.endswith("…")


def test_shorten_keeps_clean_sentence_without_ellipsis() -> None:
    text = "First sentence ends here. Second sentence is much longer and will not fit at all."
    shortened = shorten_at_word_boundary(text, 30)
    assert shortened == "First sentence ends here."


def test_shorten_multibyte_returns_valid_utf8() -> None:
    text = "Über 🔥 emoji ständig größer währenddessen München Köln Düsseldorf"
    for budget in range(6, 60):
        shortened = shorten_at_word_boundary(text, budget)
        assert byte_len(shortened) <= budget
        shortened.encode("utf-8")  # must not raise


def test_compose_reserves_link_and_hashtags_first() -> None:
    body = compose_post_body(LONG_TITLE, LONG_SUBTITLE, TAGS, source_link=LINK)
    # All hashtags survive.
    for tag in TAGS:
        assert tag in body
    # Body + publisher suffix stays within the byte budget.
    suffix = f"\n\n🔗 {LINK}"
    assert byte_len(body) + byte_len(suffix) <= BLUESKY_MAX_BYTES
    # Hashtag line is the last line.
    assert body.splitlines()[-1] == " ".join(TAGS)


def test_compose_full_pipeline_keeps_link_and_tags_intact() -> None:
    body = compose_post_body(LONG_TITLE, LONG_SUBTITLE, TAGS, source_link=LINK)
    text, facets = _compose_text_with_link(body, LINK)
    assert byte_len(text) <= BLUESKY_MAX_BYTES
    assert text.endswith(LINK)
    for tag in TAGS:
        assert tag in text
    # No mid-word cuts: every prose fragment still matches source words.
    assert "…" in text or LONG_SUBTITLE in text or LONG_SUBTITLE.split()[-1] in text
    # Facet byte offsets cover exactly the URL.
    facet = facets[0]["index"]
    assert text.encode("utf-8")[facet["byteStart"] : facet["byteEnd"]].decode("utf-8") == LINK


def test_compose_question_included_between_fact_and_tags() -> None:
    body = compose_post_body(
        "Hook line.",
        "Fact line.",
        ["#AI", "#MCP"],
        source_link="https://example.com/x",
        question="Anyone running this in prod?",
    )
    blocks = body.split("\n\n")
    assert blocks == ["Hook line.", "Fact line.", "Anyone running this in prod?", "#AI #MCP"]


def test_compose_drops_fact_before_question_and_tags_when_tight() -> None:
    long_link = "https://example.com/" + "p" * 120
    body = compose_post_body(
        "A hook that states the builder angle clearly today.",
        LONG_SUBTITLE,
        ["#AI", "#MCP"],
        source_link=long_link,
        question="Does this replace Ollama for you?",
    )
    suffix_bytes = byte_len(f"\n\n🔗 {long_link}")
    assert byte_len(body) + suffix_bytes <= BLUESKY_MAX_BYTES
    assert "#AI #MCP" in body
    # Priority: hashtags and hook always survive; the fact line shrinks/drops.
    assert body.startswith("A hook")


def test_compose_emoji_umlaut_budget() -> None:
    hook = "Größere LLMs 🚀 laufen jetzt lokal überall."
    fact = "Die Gewichte sind offen, Apache 2.0, für Ollama & llama.cpp verfügbar — überall."
    body = compose_post_body(hook, fact, ["#LocalLLM", "#OpenWeights"], source_link=LINK)
    text, facets = _compose_text_with_link(body, LINK)
    raw = text.encode("utf-8")
    assert len(raw) <= BLUESKY_MAX_BYTES
    facet = facets[0]["index"]
    assert raw[facet["byteStart"] : facet["byteEnd"]].decode("utf-8") == LINK


def test_compose_sarah_post_uses_package_fields_without_description() -> None:
    package = {
        "title": "Agent memory becomes infrastructure.",
        "subtitle": "Agentmemory ships a 4-tier pipeline with zero external APIs.",
        "description": "THIS MUST STAY ON THE CARD ONLY",
        "hashtags": ["#AI", "#AIAgents"],
    }
    post = _compose_sarah_post(package, source_link="https://example.com/item")
    assert "THIS MUST STAY ON THE CARD ONLY" not in post
    assert post.startswith("Agent memory becomes infrastructure.")
    assert "#AI #AIAgents" in post


def test_compose_sarah_post_dedupes_subtitle_repeating_title() -> None:
    package = {
        "title": "Agent memory becomes infrastructure.",
        "subtitle": "Agent memory becomes infrastructure",
        "description": "x",
        "hashtags": ["#AI", "#MCP"],
    }
    post = _compose_sarah_post(package)
    assert post.count("Agent memory becomes infrastructure") == 1


def test_select_format_variant_deterministic_and_split() -> None:
    keys = [f"https://example.com/item-{i}" for i in range(400)]
    variants = [select_format_variant(k) for k in keys]
    assert variants == [select_format_variant(k) for k in keys]  # reproducible
    question_share = variants.count("question") / len(variants)
    assert 0.3 < question_share < 0.5  # ~40%


def test_validate_question_rules() -> None:
    assert validate_question("Anyone running this in prod?") == "Anyone running this in prod?"
    assert validate_question("Does this replace Ollama for you?") is not None
    assert validate_question("") is None
    assert validate_question(None) is None
    assert validate_question("No question mark here") is None
    assert validate_question("What do you think?") is None  # engagement bait
    assert validate_question("Thoughts?") is None
    assert validate_question("x" * 80 + "?") is None  # too long
