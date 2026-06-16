from datetime import datetime, timezone

from src.editorial import constructive as c
from src.models import FeedItem


def _item(title, summary=""):
    return FeedItem("Wire", title, "https://x", summary, datetime(2026, 6, 16, tzinfo=timezone.utc))


def test_good_news_scores_positive():
    item = _item(
        "River otters make a comeback after a decades-long cleanup",
        "Conservation effort restores the wetland; volunteers rescued the population.",
    )
    score = c.constructiveness_score(item)
    assert score > 0
    assert "+constructive" in c.constructive_reason_parts(item)


def test_doom_scores_negative_and_gates():
    item = _item(
        "Catastrophe deepens as death toll climbs in worst disaster yet",
        "Hopeless scenes; the crisis deepens with no way out.",
    )
    assert c.constructiveness_score(item) < 0
    assert c.is_doomscroll(item) is True


def test_clickbait_is_doomscroll():
    item = _item("You won't believe what happened next — it breaks the internet")
    assert c.is_doomscroll(item) is True


def test_mixed_item_with_upside_is_not_gated():
    # Negative words present, but a real solution/recovery angle exists.
    item = _item(
        "After the disaster, a community-led recovery restores clean water access",
        "A proven approach saved lives and reversed the decline.",
    )
    assert c.is_doomscroll(item) is False


def test_neutral_item_scores_zero():
    item = _item("Company releases version 2.1 of its CLI tool", "Adds new flags.")
    breakdown = c.classify(item)
    assert breakdown["score"] == 0
    assert c.is_doomscroll(item) is False


def test_env_master_switch(monkeypatch):
    monkeypatch.delenv("BOARDWIRE_CONSTRUCTIVE_MODE", raising=False)
    cfg = c.load_editorial_config()
    assert c.constructive_mode_enabled(cfg) == cfg.constructive_mode  # config default (off)
    monkeypatch.setenv("BOARDWIRE_CONSTRUCTIVE_MODE", "true")
    assert c.constructive_mode_enabled(cfg) is True
    monkeypatch.setenv("BOARDWIRE_CONSTRUCTIVE_MODE", "off")
    assert c.constructive_mode_enabled(cfg) is False


def test_term_cap_limits_runaway_scores():
    cfg = c.load_editorial_config()
    # Repeating the same kind of term shouldn't scale unbounded.
    item = _item("progress progress progress progress recovery rebound revival milestone hope")
    breakdown = c.classify(item, cfg)
    # constructive contribution capped at max_terms_per_category * weight
    cap = cfg.max_terms_per_category * cfg.weight("constructive")
    assert breakdown["contributions"]["constructive"] <= cap
