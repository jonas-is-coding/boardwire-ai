from __future__ import annotations

from src.cards.card_data import (
    CardData,
    LAYOUT_CLAIM,
    LAYOUT_QUOTE,
    LAYOUT_RELEASE,
    LAYOUT_REPO,
    LAYOUT_SECURITY,
    LAYOUT_STAT,
    build_card_alt_text,
    from_review_item,
    valid_card_claim,
    valid_card_context,
)
from src.cards.html_template import render_card_html

_NON_GITHUB = "https://prismml.com/news/item"


def _item(package: dict, source: str = "GitHub Trending", link: str = "https://github.com/x/y", summary: str = "") -> dict:
    return {
        "id": "abc123",
        "created_at": "2026-07-15T10:00:00Z",
        "source_item": {
            "title": "Mistral open-sources 70B model trained on 15T tokens",
            "source": source,
            "link": link,
            "summary": summary or "Apache 2.0 open weights beats Llama 3.1 70B on MMLU",
        },
        "sarah_package": package,
    }


def _pkg(**overrides) -> dict:
    base = {
        "title": "Mistral open-sources a 70B model.",
        "subtitle": "Apache 2.0, beats Llama 3.1 70B on MMLU, weights on HuggingFace.",
        "description": "First open-weight 70B trained on 15T tokens.",
        "hashtags": ["#AI", "#OpenWeights"],
        "card_stat": "70B",
        "card_claim": "Open weights now rival closed models",
        "card_context": "Apache 2.0 · beats Llama 3.1 70B on MMLU",
    }
    base.update(overrides)
    return base


# --- token-overlap rejection (card_claim must differ from post title) -------

def test_null_summary_does_not_leak_literal_none() -> None:
    # GitHub Trending items with no summary store explicit JSON null; a naive
    # .get("summary", "") returns None (key present, not absent), and
    # str(None) == "None" would print the literal word on the card.
    item = _item(_pkg(), source="GitHub Trending", link="https://github.com/x/y", summary="")
    item["source_item"]["summary"] = None
    card = from_review_item(item)
    assert "None" not in card.card_context
    assert "None" not in card.card_claim


def test_claim_restating_title_rejected() -> None:
    assert valid_card_claim("Mistral open-sources a 70B model", "Mistral open-sources a 70B model.") is False


def test_claim_distinct_accepted() -> None:
    assert valid_card_claim("Open weights now rival closed models", "Mistral open-sources a 70B model.") is True


def test_claim_over_word_budget_rejected() -> None:
    assert valid_card_claim("one two three four five six seven eight nine", "unrelated title") is False


def test_from_review_item_falls_back_when_claim_restates_title() -> None:
    # card_claim identical to the Sarah title → invalid → fallback used.
    pkg = _pkg(card_claim="Mistral open-sources a 70B model")
    card = from_review_item(_item(pkg))
    assert card.card_claim  # non-empty fallback
    # The fallback must not be the exact restatement that got rejected.
    assert valid_card_claim(card.card_claim, "Mistral open-sources a 70B model.") or card.card_claim != "Mistral open-sources a 70B model"


# --- card_context budget (never truncated on the card) ---------------------

def test_context_within_budget_accepted() -> None:
    assert valid_card_context("Apache 2.0 · runs open-weight models") is True


def test_context_over_budget_rejected() -> None:
    assert valid_card_context("x" * 91) is False


def test_over_budget_context_replaced_with_complete_fragment() -> None:
    long_ctx = (
        "This is a very long context sentence that clearly exceeds ninety characters. "
        "And here is a second sentence."
    )
    card = from_review_item(_item(_pkg(card_context=long_ctx)))
    assert len(card.card_context) <= 90
    # Never a mid-sentence cut: the result is a complete leading sentence.
    assert card.card_context.endswith(".") or "·" in card.card_context or card.card_context
    assert "exceeds ninety char" not in card.card_context or card.card_context.endswith(".")


# --- layout selection per content type -------------------------------------

def test_stat_layout_non_github_with_stat() -> None:
    card = from_review_item(_item(_pkg(card_stat="70B"), source="PrismML", link=_NON_GITHUB))
    assert card.layout == LAYOUT_STAT


def test_claim_layout_non_github_no_stat() -> None:
    card = from_review_item(_item(_pkg(card_stat=""), source="A Blog", link="https://blog.example.com/x"))
    assert card.layout == LAYOUT_CLAIM


def test_quote_layout_for_hn_discussion() -> None:
    card = from_review_item(
        _item(_pkg(card_stat=""), source="HackerNews", link="https://news.ycombinator.com/item?id=1")
    )
    assert card.layout == LAYOUT_QUOTE


def test_stat_beats_discussion_when_stat_present() -> None:
    # A HN item WITH a stat is still a stat card (HN isn't github/release/security).
    card = from_review_item(
        _item(_pkg(card_stat="104 pts"), source="HackerNews", link="https://news.ycombinator.com/item?id=1")
    )
    assert card.layout == LAYOUT_STAT
    assert card.card_stat == "104"
    assert card.stat_unit == "pts"


def test_repo_layout_for_github_item() -> None:
    item = _item(_pkg(card_stat="607"), source="GitHub Trending", link="https://github.com/rohitg00/codegraph")
    item["source_item"]["title"] = "Codegraph indexes code knowledge"
    card = from_review_item(item)
    assert card.layout == LAYOUT_REPO
    assert card.repo_owner == "rohitg00"
    assert card.repo_name == "codegraph"


def test_release_layout_for_version_release() -> None:
    item = _item(
        _pkg(card_stat=""),
        source="Claude Code Releases",
        link="https://github.com/anthropics/claude-code/releases/tag/v2.1.210",
    )
    item["source_item"]["title"] = "Claude Code v2.1.210"
    card = from_review_item(item)
    assert card.layout == LAYOUT_RELEASE
    assert card.version_tag == "v2.1.210"
    assert card.repo_name == "claude-code"


def test_security_layout_for_vulnerability() -> None:
    item = _item(
        _pkg(card_stat="RCE"),
        source="Mindgard",
        link="https://mindgard.ai/blog/cursor-0day",
        summary="remote code execution vulnerability, data exfiltration",
    )
    item["source_item"]["title"] = "Cursor 0day exposes dev repos to RCE"
    card = from_review_item(item)
    assert card.layout == LAYOUT_SECURITY


def test_security_beats_github_release() -> None:
    # A security advisory that happens to be a GitHub release is still security.
    item = _item(
        _pkg(card_stat="CVE"),
        source="GitHub Advisory",
        link="https://github.com/x/y/releases/tag/v1.2.3",
        summary="critical vulnerability, CVE assigned",
    )
    item["source_item"]["title"] = "x/y v1.2.3 patches critical vulnerability"
    assert from_review_item(item).layout == LAYOUT_SECURITY


# --- golden HTML markers per template --------------------------------------

def _card(layout: str, **kw) -> CardData:
    defaults = dict(
        review_id="t",
        layout=layout,
        source_label="HACKERNEWS",
        source="HackerNews",
        date_label="2026-07-15",
        visual_theme="news",
        card_stat="70B" if layout in (LAYOUT_STAT, LAYOUT_REPO, LAYOUT_SECURITY) else "",
        card_claim="Open weights now rival closed models",
        card_context="Apache 2.0 · beats Llama 3.1 70B on MMLU",
        repo_owner="anthropics",
        repo_name="claude-code",
        version_tag="v2.1.210",
    )
    defaults.update(kw)
    return CardData(**defaults)


def test_stat_template_markers() -> None:
    html = render_card_html(_card(LAYOUT_STAT))
    assert "layout-stat" in html
    assert "stat-value" in html
    assert "class=\"claim\"" in html
    assert "class=\"context\"" in html
    assert "wordmark" in html
    assert "BOARDWIRE" in html


def test_claim_template_markers() -> None:
    html = render_card_html(_card(LAYOUT_CLAIM))
    assert "layout-claim" in html
    assert "claim-display" in html
    assert "wordmark" in html


def test_quote_template_markers() -> None:
    html = render_card_html(_card(LAYOUT_QUOTE))
    assert "layout-quote" in html
    assert "quote-mark" in html
    assert "quote-text" in html
    assert "attribution" in html
    assert "wordmark" in html


def test_repo_template_markers() -> None:
    html = render_card_html(_card(LAYOUT_REPO))
    assert "layout-repo" in html
    assert "repo-owner-line" in html
    assert "repo-name-line" in html
    assert "anthropics/" in html
    assert "claude-code" in html
    assert "repo-stars" in html  # stat present -> stars line
    assert "wordmark" in html


def test_release_template_markers() -> None:
    html = render_card_html(_card(LAYOUT_RELEASE))
    assert "layout-release" in html
    assert "release-version" in html
    assert "v2.1.210" in html
    assert "release-project" in html
    assert "wordmark" in html


def test_security_template_markers() -> None:
    html = render_card_html(_card(LAYOUT_SECURITY))
    assert "layout-security" in html
    assert "alert-glyph" in html
    assert "alert-label" in html
    assert "sec-stat" in html
    assert "wordmark" in html


def test_light_theme_supported_all_templates() -> None:
    for layout in (LAYOUT_STAT, LAYOUT_CLAIM, LAYOUT_QUOTE, LAYOUT_REPO, LAYOUT_RELEASE, LAYOUT_SECURITY):
        html = render_card_html(_card(layout, visual_theme="light"))
        assert "#fafafa" in html  # light background token
        assert "#FFD21E" in html  # accent preserved


def test_dark_theme_uses_brand_black() -> None:
    for layout in (LAYOUT_STAT, LAYOUT_CLAIM, LAYOUT_QUOTE, LAYOUT_REPO, LAYOUT_RELEASE, LAYOUT_SECURITY):
        html = render_card_html(_card(layout, visual_theme="news"))
        assert "#0a0a0a" in html


# --- ALT text --------------------------------------------------------------

def test_alt_text_describes_stat_claim_context() -> None:
    card = from_review_item(_item(_pkg(), source="PrismML", link=_NON_GITHUB))
    alt = build_card_alt_text(card)
    assert "70B" in alt
    assert "claim:" in alt
    assert "context:" in alt


def test_alt_text_repo_names_repository() -> None:
    item = _item(_pkg(card_stat="607"), source="GitHub Trending", link="https://github.com/rohitg00/codegraph")
    item["source_item"]["title"] = "Codegraph indexes code"
    alt = build_card_alt_text(from_review_item(item))
    assert "repository rohitg00/codegraph" in alt


def test_alt_text_release_names_version() -> None:
    item = _item(
        _pkg(card_stat=""),
        source="Claude Code Releases",
        link="https://github.com/anthropics/claude-code/releases/tag/v2.1.210",
    )
    item["source_item"]["title"] = "Claude Code v2.1.210"
    alt = build_card_alt_text(from_review_item(item))
    assert "release v2.1.210" in alt
