"""Constructive-journalism editorial signals.

Boardwire's editorial line is to prioritise GOOD, solution-oriented
information and to push doom, outrage and clickbait down. This module turns
that stance into a small, tunable scoring layer that sits alongside the
existing newsworthiness scoring.

Two outputs matter:

- :func:`constructiveness_score` — a signed score (roughly -100..+100) where
  positive means progress/solutions/recovery and negative means doom/outrage/
  clickbait. Used as a *soft* ranking signal.
- :func:`is_doomscroll` — a *hard* gate flag for items that are overwhelmingly
  negative or clickbait with no constructive substance.

Everything is keyword-heuristic and config-driven (``config/editorial.json``),
mirroring the coarse-but-effective style of ``score_newsworthiness``. It is a
ranking aid, not a fact-checker.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from src.config import CONFIG_DIR
from src.models import FeedItem
from src.storage.json_store import JsonStore

EDITORIAL_PATH = CONFIG_DIR / "editorial.json"

_POSITIVE_CATEGORIES = ("constructive", "solution")
_NEGATIVE_CATEGORIES = ("doom", "outrage", "clickbait")


@dataclass(slots=True)
class EditorialConfig:
    constructive_mode: bool = False
    weights: dict[str, int] = field(default_factory=dict)
    max_terms_per_category: int = 3
    score_floor: int = -100
    score_ceiling: int = 100
    doomscroll_drop_threshold: int = 28
    terms: dict[str, list[str]] = field(default_factory=dict)

    def weight(self, category: str) -> int:
        try:
            return int(self.weights.get(category, 0))
        except (TypeError, ValueError):
            return 0


def load_editorial_config(path=EDITORIAL_PATH) -> EditorialConfig:
    raw = JsonStore.load(path, default={})
    if not isinstance(raw, dict):
        raw = {}
    weights = raw.get("weights") if isinstance(raw.get("weights"), dict) else {}
    terms = {
        cat: [str(t).strip().lower() for t in (raw.get(f"{cat}_terms") or []) if str(t).strip()]
        for cat in (*_POSITIVE_CATEGORIES, *_NEGATIVE_CATEGORIES)
    }
    return EditorialConfig(
        constructive_mode=bool(raw.get("constructive_mode", False)),
        weights={k: int(v) for k, v in weights.items() if isinstance(v, (int, float))},
        max_terms_per_category=int(raw.get("max_terms_per_category", 3) or 3),
        score_floor=int(raw.get("score_floor", -100)),
        score_ceiling=int(raw.get("score_ceiling", 100)),
        doomscroll_drop_threshold=int(raw.get("doomscroll_drop_threshold", 28)),
        terms=terms,
    )


def constructive_mode_enabled(config: EditorialConfig | None = None) -> bool:
    """Master switch: env var overrides config; both default to off.

    This is the single toggle that turns the Good-News editorial line on for
    the live pipeline once constructive sources are in place.
    """
    raw = os.getenv("BOARDWIRE_CONSTRUCTIVE_MODE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    cfg = config or load_editorial_config()
    return bool(cfg.constructive_mode)


def _item_text(item: FeedItem) -> str:
    return f"{item.title} {item.summary}".lower()


def _term_matches(text: str, term: str) -> bool:
    """Whole-word/phrase match so 'hope' does not fire inside 'hopeless'."""
    pattern = r"(?<![a-z])" + re.escape(term) + r"(?![a-z])"
    return re.search(pattern, text) is not None


def _category_hits(text: str, terms: list[str], cap: int) -> list[str]:
    hits = [t for t in terms if t and _term_matches(text, t)]
    return hits[:cap] if cap > 0 else hits


def classify(item: FeedItem, config: EditorialConfig | None = None) -> dict:
    """Break an item down into per-category contributions and a net score."""
    cfg = config or load_editorial_config()
    text = _item_text(item)
    cap = cfg.max_terms_per_category

    contributions: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    for cat in (*_POSITIVE_CATEGORIES, *_NEGATIVE_CATEGORIES):
        hits = _category_hits(text, cfg.terms.get(cat, []), cap)
        matched[cat] = hits
        contributions[cat] = len(hits) * cfg.weight(cat)

    positive = sum(contributions[c] for c in _POSITIVE_CATEGORIES)
    negative = sum(contributions[c] for c in _NEGATIVE_CATEGORIES)
    net = max(cfg.score_floor, min(cfg.score_ceiling, positive - negative))
    return {
        "score": net,
        "positive": positive,
        "negative": negative,
        "contributions": contributions,
        "matched": matched,
    }


def constructiveness_score(item: FeedItem, config: EditorialConfig | None = None) -> int:
    """Signed constructiveness score: positive = good news, negative = doom."""
    return int(classify(item, config)["score"])


def is_doomscroll(item: FeedItem, config: EditorialConfig | None = None) -> bool:
    """True for items that are overwhelmingly negative/clickbait with no upside.

    Used as an optional hard gate: doom and clickbait clear the drop threshold
    while constructive substance is absent.
    """
    cfg = config or load_editorial_config()
    breakdown = classify(item, cfg)
    if breakdown["positive"] > 0:
        return False
    return breakdown["negative"] >= cfg.doomscroll_drop_threshold


def adjust_newsworthiness(
    base_score: int,
    item: FeedItem,
    config: EditorialConfig | None = None,
) -> int:
    """Fold the constructive signal into a newsworthiness score.

    The constructiveness score (-100..+100) is scaled into newsworthiness
    space and added to the base; pure doom/clickbait items take an extra
    penalty so they sink rather than surface. Never returns below 0. This is
    only applied when constructive mode is enabled (the caller guards on
    :func:`constructive_mode_enabled`).
    """
    cfg = config or load_editorial_config()
    delta = constructiveness_score(item, cfg)
    adjusted = int(base_score) + round(delta * 0.5)
    if is_doomscroll(item, cfg):
        adjusted -= 60
    return max(0, int(adjusted))


def constructive_reason_parts(item: FeedItem, config: EditorialConfig | None = None) -> list[str]:
    """Human-readable tags for logs/debugging, mirroring newsworthiness reasons."""
    breakdown = classify(item, config)
    parts: list[str] = []
    for cat in _POSITIVE_CATEGORIES:
        if breakdown["contributions"].get(cat):
            parts.append(f"+{cat}")
    for cat in _NEGATIVE_CATEGORIES:
        if breakdown["contributions"].get(cat):
            parts.append(f"-{cat}")
    return parts
