from __future__ import annotations

from html import escape

from src.cards.card_data import CardData


def render_card_html(card: CardData) -> str:
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
      --muted: #cfcfcf;
      --line: #2a2a2a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      width: 1200px;
      height: 1200px;
      font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;
    }}
    .canvas {{
      width: 1200px;
      height: 1200px;
      border: 2px solid var(--line);
      padding: 64px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      position: relative;
    }}
    .canvas::before, .canvas::after {{
      content: \"\";
      position: absolute;
      background: var(--line);
      opacity: 0.8;
    }}
    .canvas::before {{ left: 32px; right: 32px; top: 102px; height: 1px; }}
    .canvas::after {{ left: 32px; right: 32px; bottom: 132px; height: 1px; }}
    .top {{ display: flex; justify-content: space-between; align-items: baseline; gap: 24px; }}
    .brand {{
      font-size: 30px;
      letter-spacing: 0.12em;
      font-weight: 800;
      text-transform: uppercase;
    }}
    .category {{
      font-size: 16px;
      letter-spacing: 0.16em;
      color: var(--muted);
      text-transform: uppercase;
      border: 1px solid var(--line);
      padding: 8px 12px;
      font-weight: 600;
    }}
    .content {{ margin-top: 40px; display: grid; gap: 32px; }}
    .headline {{
      font-size: 70px;
      line-height: 1.04;
      font-weight: 780;
      letter-spacing: -0.01em;
      max-width: 1000px;
    }}
    .summary {{
      font-size: 34px;
      line-height: 1.35;
      color: #e2e2e2;
      max-width: 1040px;
      font-weight: 440;
    }}
    .meta {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      font-size: 20px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.09em;
      font-weight: 560;
    }}
    .source {{ max-width: 70%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .footer {{
      font-size: 20px;
      letter-spacing: 0.24em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <div class=\"canvas\">
    <div>
      <div class=\"top\">
        <div class=\"brand\">BOARDWIRE</div>
        <div class=\"category\">{escape(card.category)}</div>
      </div>
      <div class=\"content\">
        <div class=\"headline\">{escape(card.headline)}</div>
        <div class=\"summary\">{escape(card.summary)}</div>
      </div>
    </div>

    <div>
      <div class=\"meta\">
        <div class=\"source\">{escape(card.source)}</div>
        <div>{escape(card.date_label)}</div>
      </div>
      <div class=\"footer\">{escape(card.footer)}</div>
    </div>
  </div>
</body>
</html>
"""
