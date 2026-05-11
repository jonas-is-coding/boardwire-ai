from __future__ import annotations

from html import escape

from src.cards.card_data import CardData


def render_card_html(card: CardData) -> str:
    theme_class = f"theme-{escape(card.visual_theme)}"
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Boardwire Card</title>
  <style>
    :root {{
      --bg: #000000;
      --fg: #ffffff;
      --muted: #afafaf;
      --line: #2d2d2d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      width: 1200px;
      height: 1200px;
      font-family: \"Arial Narrow\", \"Segoe UI\", -apple-system, BlinkMacSystemFont, Arial, sans-serif;
    }}
    .canvas {{
      width: 1200px;
      height: 1200px;
      border: 1px solid var(--line);
      padding: 44px 48px;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 34px;
      position: relative;
    }}
    .top {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 24px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--line);
    }}
    .brand {{
      font-size: 32px;
      letter-spacing: 0.15em;
      font-weight: 800;
      text-transform: uppercase;
    }}
    .source-label {{
      font-size: 16px;
      letter-spacing: 0.14em;
      color: var(--muted);
      text-transform: uppercase;
      font-weight: 700;
      white-space: nowrap;
      max-width: 56%;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .content {{
      display: grid;
      grid-template-columns: 1.18fr 0.82fr;
      gap: 34px;
      min-height: 0;
    }}
    .story {{
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 0;
    }}
    .headline {{
      font-size: 88px;
      line-height: 0.96;
      font-weight: 830;
      letter-spacing: -0.01em;
      text-wrap: balance;
      overflow-wrap: anywhere;
      margin-top: 6px;
    }}
    .summary {{
      margin-top: 24px;
      font-size: 27px;
      line-height: 1.25;
      color: #e0e0e0;
      font-weight: 520;
      max-width: 92%;
      overflow-wrap: anywhere;
    }}
    .visual {{
      border: 1px solid #4d4d4d;
      background: #050505;
      position: relative;
      min-height: 0;
      height: 100%;
      overflow: hidden;
    }}
    .visual::before, .visual::after {{
      content: \"\";
      position: absolute;
      inset: 0;
      pointer-events: none;
    }}
    .theme-agents .visual::before {{
      background:
        linear-gradient(90deg, transparent 0%, #ffffff 8%, transparent 8.5%) 12% 18%/72% 2px no-repeat,
        linear-gradient(90deg, transparent 0%, #ffffff 8%, transparent 8.5%) 22% 35%/68% 2px no-repeat,
        linear-gradient(90deg, transparent 0%, #ffffff 8%, transparent 8.5%) 16% 52%/74% 2px no-repeat,
        linear-gradient(90deg, transparent 0%, #ffffff 8%, transparent 8.5%) 28% 68%/64% 2px no-repeat;
      opacity: 0.75;
    }}
    .theme-agents .visual::after {{
      background:
        linear-gradient(#ffffff,#ffffff) 8% 14%/42% 16% no-repeat,
        linear-gradient(#ffffff,#ffffff) 28% 36%/50% 16% no-repeat,
        linear-gradient(#ffffff,#ffffff) 14% 58%/55% 16% no-repeat,
        linear-gradient(#ffffff,#ffffff) 38% 80%/46% 14% no-repeat;
      mix-blend-mode: screen;
      opacity: 0.9;
    }}
    .theme-research .visual::before {{
      background:
        repeating-linear-gradient(0deg, #1f1f1f 0 1px, transparent 1px 42px),
        repeating-linear-gradient(90deg, #1f1f1f 0 1px, transparent 1px 42px);
      opacity: 0.9;
    }}
    .theme-research .visual::after {{
      background:
        linear-gradient(90deg, #fff 0 100%) 12% 18%/68% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 20% 34%/54% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 24% 50%/62% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 14% 66%/58% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 18% 82%/46% 2px no-repeat;
      opacity: 0.82;
    }}
    .theme-open_source .visual::before {{
      background:
        linear-gradient(#fff,#fff) 10% 14%/30% 24% no-repeat,
        linear-gradient(#fff,#fff) 45% 14%/45% 24% no-repeat,
        linear-gradient(#fff,#fff) 10% 46%/42% 20% no-repeat,
        linear-gradient(#fff,#fff) 56% 46%/34% 20% no-repeat,
        linear-gradient(#fff,#fff) 10% 74%/30% 16% no-repeat,
        linear-gradient(#fff,#fff) 45% 74%/45% 16% no-repeat;
      opacity: 0.88;
    }}
    .theme-open_source .visual::after {{
      background:
        repeating-linear-gradient(90deg, transparent 0 36px, #0c0c0c 36px 38px);
      opacity: 0.7;
    }}
    .theme-infrastructure .visual::before {{
      background:
        repeating-linear-gradient(0deg, #1d1d1d 0 1px, transparent 1px 28px),
        repeating-linear-gradient(90deg, #1d1d1d 0 1px, transparent 1px 28px);
      opacity: 0.95;
    }}
    .theme-infrastructure .visual::after {{
      background:
        linear-gradient(90deg, #fff 0 100%) 8% 16%/78% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 8% 30%/64% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 8% 44%/84% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 8% 58%/58% 2px no-repeat,
        linear-gradient(90deg, #fff 0 100%) 8% 72%/74% 2px no-repeat;
      opacity: 0.85;
    }}
    .theme-robotics .visual::before {{
      background:
        radial-gradient(circle at 26% 26%, transparent 0 48px, #fff 49px 51px, transparent 52px),
        radial-gradient(circle at 66% 44%, transparent 0 58px, #fff 59px 61px, transparent 62px),
        radial-gradient(circle at 38% 76%, transparent 0 72px, #fff 73px 75px, transparent 76px);
      opacity: 0.88;
    }}
    .theme-robotics .visual::after {{
      background:
        linear-gradient(45deg, transparent 48%, #fff 49%, #fff 51%, transparent 52%) 20% 18%/56% 38% no-repeat,
        linear-gradient(45deg, transparent 48%, #fff 49%, #fff 51%, transparent 52%) 42% 40%/46% 34% no-repeat,
        linear-gradient(45deg, transparent 48%, #fff 49%, #fff 51%, transparent 52%) 24% 64%/52% 26% no-repeat;
      opacity: 0.8;
    }}
    .theme-news .visual::before {{
      background:
        repeating-linear-gradient(0deg, #1a1a1a 0 1px, transparent 1px 40px),
        repeating-linear-gradient(90deg, #1a1a1a 0 1px, transparent 1px 40px);
      opacity: 0.85;
    }}
    .theme-news .visual::after {{
      background:
        linear-gradient(#fff,#fff) 12% 18%/76% 20% no-repeat,
        linear-gradient(#fff,#fff) 12% 44%/52% 14% no-repeat,
        linear-gradient(#fff,#fff) 12% 64%/68% 12% no-repeat;
      opacity: 0.9;
    }}
    .meta {{
      display: flex;
      justify-content: flex-start;
      gap: 12px;
      font-size: 17px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.11em;
      font-weight: 680;
      border-top: 1px solid var(--line);
      padding-top: 16px;
      white-space: nowrap;
    }}
  </style>
</head>
<body>
  <div class=\"canvas {theme_class}\">
    <div class=\"top\">
      <div class=\"brand\">BOARDWIRE</div>
      <div class=\"source-label\">{escape(card.source_label)}</div>
    </div>
    <div class=\"content\">
      <div class=\"story\">
        <div class=\"headline\">{escape(card.card_headline)}</div>
        <div class=\"summary\">{escape(card.card_summary)}</div>
      </div>
      <div class=\"visual\" aria-label=\"Editorial visual\"></div>
    </div>
    <div class=\"meta\">
      <span>{escape(card.source_label)}</span>
      <span>/</span>
      <span>{escape(card.date_label)}</span>
      <span>/</span>
      <span>{escape(card.footer)}</span>
    </div>
  </div>
</body>
</html>
"""
