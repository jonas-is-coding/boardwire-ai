from __future__ import annotations

from html import escape

from src.cards.card_data import (
    CardData,
    LAYOUT_CLAIM,
    LAYOUT_QUOTE,
    LAYOUT_RELEASE,
    LAYOUT_REPO,
    LAYOUT_SECURITY,
    LAYOUT_STAT,
)


DEFAULT_ACCENT = "#FFD21E"


def _accent_for(source: str) -> str:
    _ = source
    return DEFAULT_ACCENT


def _theme_tokens(is_light: bool) -> dict[str, str]:
    if is_light:
        return {
            "bg": "#fafafa",
            "fg": "#0a0a0a",
            "subtle": "#525252",
            "bloom_fg": "rgba(0,0,0,0.03)",
            "grid_alpha": "0.025",
        }
    return {
        "bg": "#0a0a0a",
        "fg": "#ffffff",
        "subtle": "#a1a1a1",
        "bloom_fg": "rgba(255,255,255,0.025)",
        "grid_alpha": "0.015",
    }


def _claim_font_size(claim: str) -> int:
    """Scale the claim type down as it grows so it stays within ~2 lines."""
    words = len((claim or "").split())
    if words <= 4:
        return 84
    if words <= 6:
        return 74
    return 64


def _stat_font_size(value: str) -> int:
    """Keep long hero tokens (e.g. '+607★') from overflowing."""
    n = len(value or "")
    if n <= 3:
        return 300
    if n <= 5:
        return 240
    return 200


def _base_css(tokens: dict[str, str], accent: str) -> str:
    return f"""
    :root {{
      --bg: {tokens['bg']};
      --fg: {tokens['fg']};
      --subtle: {tokens['subtle']};
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
      background:
        radial-gradient(900px 600px at 100% 100%, {accent}10, transparent 60%),
        radial-gradient(700px 500px at 0% 0%, {tokens['bloom_fg']}, transparent 55%);
      pointer-events: none;
    }}
    .card::after {{
      content: "";
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba(255,255,255,{tokens['grid_alpha']}) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,{tokens['grid_alpha']}) 1px, transparent 1px);
      background-size: 80px 80px;
      pointer-events: none;
      -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
              mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
    }}
    .kicker {{
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
    .kicker .kicker-text {{
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
    .body {{
      align-self: center;
      position: relative;
      z-index: 1;
      min-width: 0;
    }}
    .footer {{
      align-self: end;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: relative;
      z-index: 1;
    }}
    .wordmark {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 22px;
      font-weight: 600;
      letter-spacing: 0.28em;
      color: var(--accent);
    }}
    .date {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 20px;
      letter-spacing: 0.05em;
      color: var(--subtle);
    }}
    """


def _stat_layout_css() -> str:
    return """
    .stat-value {
      font-weight: 700;
      line-height: 0.9;
      letter-spacing: -0.04em;
      color: var(--fg);
    }
    .stat-value .stat-symbol { color: var(--accent); }
    .stat-unit {
      margin-top: 8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 30px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--subtle);
    }
    .claim {
      margin-top: 44px;
      font-weight: 600;
      line-height: 1.02;
      letter-spacing: -0.03em;
      color: var(--fg);
      max-width: 92%;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .context {
      margin-top: 34px;
      font-size: 34px;
      line-height: 1.35;
      color: var(--subtle);
      max-width: 90%;
    }
    """


def _claim_layout_css() -> str:
    return """
    .claim-display {
      font-weight: 600;
      line-height: 1.0;
      letter-spacing: -0.04em;
      color: var(--fg);
      max-width: 96%;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .claim-display .period { color: var(--accent); }
    .context {
      margin-top: 48px;
      font-size: 36px;
      line-height: 1.35;
      color: var(--subtle);
      max-width: 88%;
    }
    """


def _quote_layout_css() -> str:
    return """
    .quote-mark {
      font-size: 260px;
      line-height: 0.6;
      font-weight: 700;
      color: var(--accent);
      height: 150px;
      overflow: hidden;
    }
    .quote-text {
      margin-top: 24px;
      font-size: 68px;
      line-height: 1.12;
      font-weight: 500;
      font-style: italic;
      letter-spacing: -0.02em;
      color: var(--fg);
      max-width: 94%;
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .attribution {
      margin-top: 40px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 28px;
      letter-spacing: 0.04em;
      color: var(--subtle);
    }
    """


def _render_stat_body(card: CardData) -> str:
    value = escape(card.card_stat)
    unit = escape(card.stat_unit)
    claim = escape(card.card_claim)
    context = escape(card.card_context)
    stat_px = _stat_font_size(card.card_stat)
    claim_px = _claim_font_size(card.card_claim)
    # Color a trailing symbol (★, %, x) as accent when present.
    value_html = value
    if value and value[-1] in "★%x×":
        value_html = f"{escape(card.card_stat[:-1])}<span class=\"stat-symbol\">{escape(card.card_stat[-1])}</span>"
    unit_html = f'<div class="stat-unit">{unit}</div>' if unit else ""
    return f"""
    <div class="body">
      <div class="stat-value" style="font-size:{stat_px}px">{value_html}</div>
      {unit_html}
      <div class="claim" style="font-size:{claim_px}px">{claim}</div>
      <div class="context">{context}</div>
    </div>
    """


def _render_claim_body(card: CardData) -> str:
    claim = card.card_claim.rstrip()
    period = ""
    if claim.endswith("."):
        claim, period = claim[:-1], "."
    claim_html = escape(claim)
    if period:
        claim_html += f'<span class="period">{escape(period)}</span>'
    context = escape(card.card_context)
    # Bigger display type for claim-only cards (no stat competing for space).
    words = len(card.card_claim.split())
    claim_px = 118 if words <= 4 else (100 if words <= 6 else 84)
    return f"""
    <div class="body">
      <div class="claim-display" style="font-size:{claim_px}px">{claim_html}</div>
      <div class="context">{context}</div>
    </div>
    """


def _render_quote_body(card: CardData) -> str:
    quote = escape(card.card_claim)
    attribution = escape(card.card_context or card.source_label)
    return f"""
    <div class="body">
      <div class="quote-mark">&ldquo;</div>
      <div class="quote-text">{quote}</div>
      <div class="attribution">{attribution}</div>
    </div>
    """


def _repo_layout_css() -> str:
    return """
    .repo-owner-line {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 44px;
      font-weight: 500;
      letter-spacing: -0.01em;
      color: var(--subtle);
    }
    .repo-name-line {
      margin-top: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-weight: 700;
      line-height: 0.98;
      letter-spacing: -0.02em;
      color: var(--accent);
      word-break: break-word;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .repo-stars {
      margin-top: 28px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 34px;
      letter-spacing: 0.02em;
      color: var(--fg);
    }
    .repo-stars .star { color: var(--accent); }
    .claim {
      margin-top: 40px;
      font-weight: 600;
      line-height: 1.05;
      letter-spacing: -0.03em;
      color: var(--fg);
      max-width: 92%;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .context {
      margin-top: 30px;
      font-size: 33px;
      line-height: 1.35;
      color: var(--subtle);
      max-width: 90%;
    }
    """


def _release_layout_css() -> str:
    return """
    .release-label {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 26px;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--subtle);
      margin-bottom: 20px;
    }
    .release-version {
      display: inline-block;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-weight: 700;
      line-height: 1.0;
      letter-spacing: -0.02em;
      color: var(--accent);
      border: 4px solid var(--accent);
      border-radius: 20px;
      padding: 14px 34px;
    }
    .release-project {
      margin-top: 30px;
      font-size: 40px;
      font-weight: 600;
      letter-spacing: -0.02em;
      color: var(--fg);
    }
    .claim {
      margin-top: 34px;
      font-size: 52px;
      font-weight: 600;
      line-height: 1.05;
      letter-spacing: -0.03em;
      color: var(--fg);
      max-width: 92%;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .context {
      margin-top: 28px;
      font-size: 32px;
      line-height: 1.35;
      color: var(--subtle);
      max-width: 90%;
    }
    """


def _security_layout_css() -> str:
    return """
    .alert-bar {
      display: flex;
      align-items: center;
      gap: 20px;
      margin-bottom: 40px;
    }
    .alert-glyph {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 88px;
      height: 88px;
      border-radius: 20px;
      background: var(--accent);
      color: #0a0a0a;
      font-size: 60px;
      font-weight: 800;
      line-height: 1;
      flex-shrink: 0;
    }
    .alert-label {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 30px;
      letter-spacing: 0.24em;
      text-transform: uppercase;
      color: var(--accent);
    }
    .sec-stat {
      font-weight: 700;
      line-height: 0.95;
      letter-spacing: -0.03em;
      color: var(--fg);
    }
    .claim {
      margin-top: 40px;
      font-size: 56px;
      font-weight: 600;
      line-height: 1.05;
      letter-spacing: -0.03em;
      color: var(--fg);
      max-width: 94%;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .context {
      margin-top: 30px;
      font-size: 33px;
      line-height: 1.35;
      color: var(--subtle);
      max-width: 90%;
    }
    """


def _render_repo_body(card: CardData) -> str:
    owner = escape(card.repo_owner)
    name = escape(card.repo_name)
    claim = escape(card.card_claim)
    context = escape(card.card_context)
    # Stacked GitHub-style: "owner/" small on its own line, repo name big below.
    name_len = len(card.repo_name)
    name_px = 128 if name_len <= 11 else (100 if name_len <= 16 else (76 if name_len <= 22 else 56))
    stars_html = ""
    if card.card_stat:
        stat = escape(card.card_stat) + (f" {escape(card.stat_unit)}" if card.stat_unit else "")
        stars_html = f'<div class="repo-stars"><span class="star">★</span> {stat}</div>'
    return f"""
    <div class="body">
      <div class="repo-owner-line">{owner}/</div>
      <div class="repo-name-line" style="font-size:{name_px}px">{name}</div>
      {stars_html}
      <div class="claim">{claim}</div>
      <div class="context">{context}</div>
    </div>
    """


def _render_release_body(card: CardData) -> str:
    version = escape(card.version_tag)
    project = escape(card.repo_name or card.source_label)
    claim = escape(card.card_claim)
    context = escape(card.card_context)
    version_px = 120 if len(card.version_tag) <= 10 else 92
    return f"""
    <div class="body">
      <div class="release-label">Release</div>
      <div class="release-version" style="font-size:{version_px}px">{version}</div>
      <div class="release-project">{project}</div>
      <div class="claim">{claim}</div>
      <div class="context">{context}</div>
    </div>
    """


def _render_security_body(card: CardData) -> str:
    claim = escape(card.card_claim)
    context = escape(card.card_context)
    stat_html = ""
    if card.card_stat:
        stat = escape(card.card_stat) + (f" {escape(card.stat_unit)}" if card.stat_unit else "")
        stat_px = _stat_font_size(card.card_stat)
        stat_html = f'<div class="sec-stat" style="font-size:{stat_px}px">{stat}</div>'
    return f"""
    <div class="body">
      <div class="alert-bar">
        <span class="alert-glyph">!</span>
        <span class="alert-label">Security</span>
      </div>
      {stat_html}
      <div class="claim">{claim}</div>
      <div class="context">{context}</div>
    </div>
    """


def render_card_html(card: CardData) -> str:
    layout = getattr(card, "layout", None) or LAYOUT_CLAIM
    source = getattr(card, "source_label", None) or getattr(card, "source", None) or ""
    visual_theme = getattr(card, "visual_theme", "dark") or "dark"
    wordmark = getattr(card, "wordmark", None) or "BOARDWIRE"
    date_label = getattr(card, "date_label", "") or ""

    accent = _accent_for(source)
    is_light = visual_theme.lower() == "light"
    tokens = _theme_tokens(is_light)

    renderers = {
        LAYOUT_STAT: (_stat_layout_css, _render_stat_body),
        LAYOUT_QUOTE: (_quote_layout_css, _render_quote_body),
        LAYOUT_REPO: (_repo_layout_css, _render_repo_body),
        LAYOUT_RELEASE: (_release_layout_css, _render_release_body),
        LAYOUT_SECURITY: (_security_layout_css, _render_security_body),
        LAYOUT_CLAIM: (_claim_layout_css, _render_claim_body),
    }
    if layout not in renderers:
        layout = LAYOUT_CLAIM
    css_fn, body_fn = renderers[layout]
    layout_css = css_fn()
    body_html = body_fn(card)

    source_html = escape(source)
    wordmark_html = escape(wordmark)
    date_html = escape(date_label)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Boardwire</title>
  <style>
    {_base_css(tokens, accent)}
    {layout_css}
  </style>
</head>
<body>
  <div class="card layout-{layout}">
    <div class="kicker">
      <span class="dot"></span>
      <span class="kicker-text">{source_html}</span>
    </div>
    {body_html}
    <div class="footer">
      <span class="wordmark">{wordmark_html}</span>
      <span class="date">{date_html}</span>
    </div>
  </div>
</body>
</html>
"""
