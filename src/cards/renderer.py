from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from src.cards.card_data import CardData
from src.cards.html_template import render_card_html


def render_card_png(card: CardData, output_path: Path) -> Path:
    html = render_card_html(card)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 1200})
        page.set_content(html, wait_until="load")
        page.screenshot(path=str(output_path), full_page=True)
        browser.close()

    return output_path
