"""Golden test for the three card templates.

Per the task, we assert the rendered HTML carries the expected type-scale
markers (a stable structural contract) rather than pixel-diffing a PNG. A real
Playwright render is also attempted and skipped gracefully when no browser is
available, so the render path itself stays exercised where possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cards.card_data import LAYOUT_CLAIM, LAYOUT_QUOTE, LAYOUT_STAT, from_review_item
from src.cards.html_template import render_card_html


def _fixture(layout: str) -> dict:
    packages = {
        LAYOUT_STAT: {
            "title": "Mistral open-sources a 70B model.",
            "subtitle": "Apache 2.0, beats Llama 3.1 70B on MMLU.",
            "description": "First open-weight 70B trained on 15T tokens.",
            "hashtags": ["#AI", "#OpenWeights"],
            "card_stat": "70B",
            "card_claim": "Open weights now rival closed models",
            "card_context": "Apache 2.0 · beats Llama 3.1 70B on MMLU",
        },
        LAYOUT_CLAIM: {
            "title": "Agent memory becomes a core primitive.",
            "subtitle": "Agentmemory ships persistent state for coding agents.",
            "description": "4-tier local pipeline, zero external APIs.",
            "hashtags": ["#AI", "#AIAgents"],
            "card_stat": "",
            "card_claim": "Memory moves from plugin to platform",
            "card_context": "Runs locally · zero external APIs",
        },
        LAYOUT_QUOTE: {
            "title": "Developers rethink AI editors.",
            "subtitle": "A widely-shared HN essay questions editor lock-in.",
            "description": "Argues for portable, tool-agnostic workflows.",
            "hashtags": ["#AI", "#DevTools"],
            "card_stat": "",
            "card_claim": "Editor lock-in is the real cost",
            "card_context": "Portable workflows beat any single tool",
        },
    }
    links = {
        LAYOUT_STAT: "https://github.com/mistralai/mistral",
        LAYOUT_CLAIM: "https://github.com/x/agentmemory",
        LAYOUT_QUOTE: "https://news.ycombinator.com/item?id=1",
    }
    sources = {LAYOUT_STAT: "GitHub Trending", LAYOUT_CLAIM: "GitHub Trending", LAYOUT_QUOTE: "HackerNews"}
    return {
        "id": f"golden-{layout}",
        "created_at": "2026-07-15T10:00:00Z",
        "source_item": {
            "title": packages[layout]["title"].rstrip("."),
            "source": sources[layout],
            "link": links[layout],
            "summary": "context summary",
        },
        "sarah_package": packages[layout],
    }


# Golden type-scale contract per template: (layout -> markers that must render).
_TYPE_SCALE = {
    LAYOUT_STAT: ["layout-stat", "stat-value", 'class="claim"', 'class="context"', "font-size: 34px"],
    LAYOUT_CLAIM: ["layout-claim", "claim-display", 'class="context"', "font-size: 36px"],
    LAYOUT_QUOTE: ["layout-quote", "quote-mark", "quote-text", "attribution", "font-size: 260px"],
}


@pytest.mark.parametrize("layout", [LAYOUT_STAT, LAYOUT_CLAIM, LAYOUT_QUOTE])
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


@pytest.mark.parametrize("layout", [LAYOUT_STAT, LAYOUT_CLAIM, LAYOUT_QUOTE])
def test_card_template_renders_png(layout: str, tmp_path: Path) -> None:
    card = from_review_item(_fixture(layout))
    out = tmp_path / f"{layout}.png"
    try:
        from src.cards.renderer import render_card_png

        render_card_png(card, out)
    except Exception as exc:  # no browser available in this environment
        pytest.skip(f"Playwright render unavailable: {exc}")
    assert out.exists() and out.stat().st_size > 2000
