from src.cards.card_data import CardData, from_review_item
from src.cards.html_template import render_card_html


def _card():
    return CardData(
        review_id="abc",
        card_headline="River otters return after a 20-year cleanup",
        card_summary="Their numbers are the highest in four decades.",
        visual_theme="news",
        source_label="POSITIVE NEWS",
        source="Positive News",
        date_label="2026-06-16",
        footer="DAYBREAK",
    )


def test_default_is_daybreak_theme(monkeypatch):
    monkeypatch.delenv("BOARDWIRE_CARD_THEME", raising=False)
    html = render_card_html(_card())
    assert "#FFF7ED" in html  # warm paper background
    assert "rgba(249,115,22" in html  # sunrise bloom
    assert ">DAYBREAK<" in html  # brand wordmark rendered


def test_env_can_force_dark(monkeypatch):
    monkeypatch.setenv("BOARDWIRE_CARD_THEME", "dark")
    html = render_card_html(_card())
    assert "#000000" in html
    assert "#FFF7ED" not in html


def test_brand_and_content_escaped(monkeypatch):
    monkeypatch.delenv("BOARDWIRE_CARD_THEME", raising=False)
    card = _card()
    card.card_headline = "A <b>bold</b> & risky headline"
    html = render_card_html(card)
    assert "&lt;b&gt;" in html and "&amp;" in html


def test_from_review_item_brands_daybreak():
    item = {
        "id": "x1",
        "created_at": "2026-06-16T08:00:00Z",
        "reason": "A conservation win",
        "proposed_post": "Otters are back.",
        "source_item": {
            "title": "Otters return to the river",
            "source": "Positive News",
            "summary": "Otters spotted again.",
        },
    }
    card = from_review_item(item)
    assert card.footer == "DAYBREAK"
