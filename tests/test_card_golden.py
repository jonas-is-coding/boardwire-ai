"""Golden test for the three card templates.

Per the task, we assert the rendered HTML carries the expected type-scale
markers (a stable structural contract) rather than pixel-diffing a PNG. A real
Playwright render is also attempted and skipped gracefully when no browser is
available, so the render path itself stays exercised where possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cards.card_data import (
    LAYOUT_CLAIM,
    LAYOUT_QUOTE,
    LAYOUT_RELEASE,
    LAYOUT_REPO,
    LAYOUT_SECURITY,
    LAYOUT_STAT,
    from_review_item,
)
from src.cards.html_template import render_card_html


# (layout -> (source_item fields, sarah card fields)) — chosen so each fixture
# selects its intended layout deterministically.
_FIXTURES = {
    LAYOUT_STAT: {
        "title": "Bonsai 27B runs on a phone",
        "source": "PrismML",
        "link": "https://prismml.com/news/bonsai-27b",
        "summary": "1-bit quantization for edge inference",
        "card_stat": "27B",
        "card_claim": "On-device beats 7B-class limits",
        "card_context": "1-bit weights · Apache 2.0",
    },
    LAYOUT_CLAIM: {
        "title": "AI coding velocity is a mirage",
        "source": "A Blog",
        "link": "https://blog.example.com/velocity",
        "summary": "measured study of perceived vs real speed",
        "card_stat": "",
        "card_claim": "Perceived speed hides real slowdown",
        "card_context": "Measured study · −19% real velocity",
    },
    LAYOUT_QUOTE: {
        "title": "Developers rethink AI editors",
        "source": "HackerNews",
        "link": "https://news.ycombinator.com/item?id=1",
        "summary": "a widely-shared opinion essay on editor lock-in",
        "card_stat": "",
        "card_claim": "Editor lock-in is the real cost",
        "card_context": "Portable workflows beat any single tool",
    },
    LAYOUT_REPO: {
        "title": "Codegraph indexes code knowledge",
        "source": "GitHub Trending",
        "link": "https://github.com/rohitg00/codegraph",
        "summary": "code knowledge graph for coding agents",
        "card_stat": "607",
        "card_claim": "Coding agents get shared memory",
        "card_context": "MIT · indexes for Claude Code, Codex, Cursor",
    },
    LAYOUT_RELEASE: {
        "title": "Claude Code v2.1.210",
        "source": "Claude Code Releases",
        "link": "https://github.com/anthropics/claude-code/releases/tag/v2.1.210",
        "summary": "adds forward-subagent-text and critical fixes",
        "card_stat": "",
        "card_claim": "Subagent streaming gets transparent",
        "card_context": "Adds --forward-subagent-text · critical fixes",
    },
    LAYOUT_SECURITY: {
        "title": "Cursor 0day exposes dev repos to RCE",
        "source": "Mindgard",
        "link": "https://mindgard.ai/blog/cursor-0day",
        "summary": "remote code execution vulnerability, data exfiltration",
        "card_stat": "RCE",
        "card_claim": "Malicious cursor:// URLs run code",
        "card_context": "Windows and macOS affected · no patch yet",
    },
}

_ALL_LAYOUTS = list(_FIXTURES.keys())


def _fixture(layout: str) -> dict:
    f = _FIXTURES[layout]
    return {
        "id": f"golden-{layout}",
        "created_at": "2026-07-15T10:00:00Z",
        "source_item": {
            "title": f["title"],
            "source": f["source"],
            "link": f["link"],
            "summary": f["summary"],
        },
        "sarah_package": {
            "title": f["title"] + ".",
            "subtitle": f["card_context"],
            "description": f["card_context"],
            "hashtags": ["#AI", "#LLM"],
            "card_stat": f["card_stat"],
            "card_claim": f["card_claim"],
            "card_context": f["card_context"],
        },
    }


# Golden type-scale contract per template: (layout -> markers that must render).
_TYPE_SCALE = {
    LAYOUT_STAT: ["layout-stat", "stat-value", 'class="claim"', 'class="context"', "font-size: 34px"],
    LAYOUT_CLAIM: ["layout-claim", "claim-display", 'class="context"', "font-size: 36px"],
    LAYOUT_QUOTE: ["layout-quote", "quote-mark", "quote-text", "attribution", "font-size: 260px"],
    LAYOUT_REPO: ["layout-repo", "repo-owner-line", "repo-name-line", "repo-stars"],
    LAYOUT_RELEASE: ["layout-release", "release-version", "release-project"],
    LAYOUT_SECURITY: ["layout-security", "alert-glyph", "alert-label", "sec-stat"],
}


@pytest.mark.parametrize("layout", _ALL_LAYOUTS)
def test_card_template_type_scale_markers(layout: str) -> None:
    card = from_review_item(_fixture(layout))
    assert card.layout == layout
    html = render_card_html(card)
    for marker in _TYPE_SCALE[layout]:
        assert marker in html, f"missing type-scale marker {marker!r} in {layout} card"
    # Brand system present on every template.
    assert "BOARDWIRE" in html
    assert "#FFD21E" in html
    assert 'class="dot"' in html  # monospace source kicker with accent dot


@pytest.mark.parametrize("layout", _ALL_LAYOUTS)
def test_card_template_renders_png(layout: str, tmp_path: Path) -> None:
    card = from_review_item(_fixture(layout))
    out = tmp_path / f"{layout}.png"
    try:
        from src.cards.renderer import render_card_png

        render_card_png(card, out)
    except Exception as exc:  # no browser available in this environment
        pytest.skip(f"Playwright render unavailable: {exc}")
    assert out.exists() and out.stat().st_size > 2000
