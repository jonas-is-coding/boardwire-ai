from __future__ import annotations

from src.models import EvaluationResult, FeedItem, Persona

# Keywords weighted by signal strength for builder-focused AI coverage.
# High weight: signals something is available/usable today.
# Medium weight: relevant domain, may still pass threshold.
# The rule-based evaluator is a fast pre-filter; LLM does the nuanced call.

_HIGH_SIGNAL = {
    "release": 4,
    "released": 4,
    "launches": 4,
    "ships": 4,
    "available": 3,
    "open source": 4,
    "open-source": 4,
    "open weight": 4,
    "open-weight": 4,
    "open model": 4,
    "weights": 3,
    "api": 3,
    "download": 3,
    "agent": 3,
    "llm": 3,
    "fine-tun": 3,
    "inference": 3,
    "deployment": 2,
    "production": 3,
    # GitHub release feed items
    "v0.": 4,
    "v1.": 4,
    "v2.": 4,
    "v3.": 4,
    "changelog": 3,
    "mcp": 4,
    "claude code": 4,
    "claude ": 3,
    "sdk": 3,
    "plugin": 2,
    "extension": 2,
}

_MEDIUM_SIGNAL = {
    "ai": 1,
    "model": 2,
    "benchmark": 2,
    "robotics": 2,
    "research": 1,
    "tool": 2,
    "framework": 2,
    "dataset": 2,
    "training": 2,
    "multimodal": 2,
    "embedding": 2,
    "rag": 3,
    "retrieval": 2,
}

_LOW_SIGNAL_PENALTY = {
    "funding": -2,
    "raises": -2,
    "valuation": -2,
    "partnership": -1,
    "opinion": -2,
    "might": -1,
    "could eventually": -2,
    "in the future": -2,
    # Release candidates and internal merges are not worth posting
    "-rc": -5,
    "merge remote-tracking": -10,
    "merge branch": -5,
}


_TIER_BONUS = {1: 3, 2: 1, 3: 0}


def evaluate_item(item: FeedItem, personas: list[Persona]) -> EvaluationResult:
    _ = personas
    haystack = f"{item.title} {item.summary}".lower()

    score = 0
    matched: list[str] = []

    for keyword, weight in _HIGH_SIGNAL.items():
        if keyword in haystack:
            score += weight
            matched.append(keyword)

    for keyword, weight in _MEDIUM_SIGNAL.items():
        if keyword in haystack and keyword not in matched:
            score += weight
            matched.append(keyword)

    for phrase, penalty in _LOW_SIGNAL_PENALTY.items():
        if phrase in haystack:
            score += penalty

    tier_bonus = _TIER_BONUS.get(item.source_tier, 0)
    score += tier_bonus

    if item.engagement_score >= 100:
        score += 2
    elif item.engagement_score >= 25:
        score += 1

    score = max(0, score)
    should_post = score >= 4

    if should_post:
        tier_note = f" (T{item.source_tier})" if tier_bonus else ""
        reason = (
            f"Builder signal{tier_note}: {', '.join(matched[:4])}"
            if matched
            else f"Source signal (Tier {item.source_tier})"
        )
    else:
        reason = "Weak builder signal — no clear release, tool, or actionable output"

    return EvaluationResult(should_post=should_post, score=score, reason=reason)
