from __future__ import annotations

import os
from html import escape

from src.cards.card_data import CardData


DEFAULT_ACCENT = "#F97316"  # sunrise orange


def _accent_for(source: str) -> str:
    _ = source
    return DEFAULT_ACCENT


def _card_theme(card: CardData) -> str:
    """Resolve the card theme.

    Env BOARDWIRE_CARD_THEME wins (dark | light | daybreak); otherwise default
    to the warm 'daybreak' look. Only 'dark' opts out of the light palette.
    """
    env = (os.getenv("BOARDWIRE_CARD_THEME") or "").strip().lower()
    if env in {"dark", "light", "daybreak"}:
        return env
    return "daybreak"


def _split_headline(headline: str) -> tuple[str, str]:
    """Split off a trailing period so we can color it as an accent.

    Returns (body, period) where period is '' or '.'.
    """
    stripped = headline.rstrip()
    if stripped.endswith("."):
        return stripped[:-1], "."
    return stripped, ""


def render_card_html(card: CardData) -> str:
    # Defensive attribute access — works whether CardData uses
    # headline/title and summary/subtitle/description naming.
    headline = (
        getattr(card, "card_headline", None)
        or getattr(card, "headline", None)
        or getattr(card, "title", None)
        or ""
    )
    summary = (
        getattr(card, "card_summary", None)
        or getattr(card, "summary", None)
        or getattr(card, "subtitle", None)
        or getattr(card, "description", None)
        or ""
    )
    source = (
        getattr(card, "source_label", None)
        or getattr(card, "source", None)
        or ""
    )
    brand = getattr(card, "footer", None) or "DAYBREAK"

    accent = _accent_for(source)
    theme = _card_theme(card)

    body, period = _split_headline(headline)

    # Theme tokens
    if theme == "dark":
        bg = "#000000"
        fg = "#ffffff"
        subtle = "#a1a1a1"
        grid_rgb = "255,255,255"
        grid_alpha = "0.015"
        bloom = (
            f"radial-gradient(900px 600px at 100% 100%, {accent}10, transparent 60%),"
            "radial-gradient(700px 500px at 0% 0%, rgba(255,255,255,0.025), transparent 55%)"
        )
    elif theme == "light":
        bg = "#fafafa"
        fg = "#0a0a0a"
        subtle = "#525252"
        grid_rgb = "0,0,0"
        grid_alpha = "0.025"
        bloom = (
            f"radial-gradient(900px 600px at 100% 100%, {accent}14, transparent 60%),"
            "radial-gradient(700px 500px at 0% 0%, rgba(0,0,0,0.03), transparent 55%)"
        )
    else:  # daybreak — warm sunrise on warm paper
        bg = "#FFF7ED"
        fg = "#1C1917"
        subtle = "#78716C"
        grid_rgb = "120,53,15"
        grid_alpha = "0.04"
        bloom = (
            "radial-gradient(1100px 760px at 100% 100%, rgba(249,115,22,0.20), transparent 62%),"
            "radial-gradient(900px 640px at 0% 100%, rgba(251,191,36,0.16), transparent 58%),"
            "radial-gradient(700px 520px at 0% 0%, rgba(244,114,182,0.08), transparent 55%)"
        )

    # Pre-escape user content
    headline_html = (
        f'{escape(body)}<span class="period">{escape(period)}</span>'
        if period
        else escape(body)
    )
    summary_html = escape(summary)
    source_html = escape(source)
    brand_html = escape(brand)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daybreak</title>
  <style>
    :root {{
      --bg: {bg};
      --fg: {fg};
      --subtle: {subtle};
      --accent: {accent};
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      background: var(--bg);
      width: 1200px;
      height: 1200px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    .card {{
      width: 1200px;
      height: 1200px;
      background: var(--bg);
      color: var(--fg);
      position: relative;
      overflow: hidden;
      padding: 96px 100px;
      display: grid;
      grid-template-rows: auto 1fr auto;
    }}
    .card::before {{
      content: "";
      position: absolute;
      inset: 0;
      background: {bloom};
      pointer-events: none;
    }}
    .card::after {{
      content: "";
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba({grid_rgb},{grid_alpha}) 1px, transparent 1px),
        linear-gradient(90deg, rgba({grid_rgb},{grid_alpha}) 1px, transparent 1px);
      background-size: 80px 80px;
      pointer-events: none;
      -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
              mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
    }}
    .brand {{
      margin-left: auto;
      flex-shrink: 0;
      font-weight: 700;
      letter-spacing: 0.18em;
      color: var(--accent);
    }}
    .source {{
      display: flex;
      align-items: center;
      gap: 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 22px;
      font-weight: 500;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--subtle);
      position: relative;
      z-index: 1;
      max-width: 100%;
      min-width: 0;
    }}
    .source .source-text {{
      min-width: 0;
      flex: 1 1 auto;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .dot {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 24px var(--accent);
      flex-shrink: 0;
    }}
    .headline-block {{
      align-self: end;
      position: relative;
      z-index: 1;
    }}
    .headline {{
      font-size: 124px;
      line-height: 0.94;
      font-weight: 600;
      letter-spacing: -0.045em;
      color: var(--fg);
      text-wrap: balance;
    }}
    .headline .period {{ color: var(--accent); }}
    .summary {{
      margin-top: 56px;
      font-size: 32px;
      line-height: 1.35;
      font-weight: 400;
      letter-spacing: -0.015em;
      color: var(--subtle);
      max-width: 88%;
      text-wrap: pretty;
      position: relative;
      z-index: 1;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="source">
      <span class="dot"></span>
      <span class="source-text">{source_html}</span>
      <span class="brand">{brand_html}</span>
    </div>
    <div class="headline-block">
      <h1 class="headline">{headline_html}</h1>
    </div>
    <p class="summary">{summary_html}</p>
  </div>
</body>
</html>
"""
