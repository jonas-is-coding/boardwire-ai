from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(slots=True)
class QualityConfig:
    max_post_length: int
    min_llm_score: int
    min_rule_score: int
    duplicate_lookback_hours: int
    fixture_duplicate_lookback_hours: int
    banned_phrases: list[str]
    generic_phrases: list[str]


@dataclass(slots=True)
class QualityResult:
    passed: bool
    reasons: list[str]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _has_claim_or_insight(text: str, context_text: str | None = None) -> bool:
    t = _normalize(text)
    if len(t.split()) < 5:
        return False

    indicators = [
        "because",
        "shows",
        "signals",
        "means",
        "matters",
        "could",
        "enables",
        "reduces",
        "improves",
        "benchmark",
        "model",
        "agent",
        "developer",
        "research",
        "open-source",
        "open source",
        "robotics",
        "training",
        "inference",
    ]
    if any(word in t for word in indicators):
        return True

    if context_text:
        ctx = _normalize(context_text)
        post_tokens = set(re.findall(r"[a-z0-9-]{4,}", t))
        ctx_tokens = set(re.findall(r"[a-z0-9-]{4,}", ctx))
        overlap = post_tokens & ctx_tokens
        # Accept when the post carries at least one concrete technical token from source text.
        if overlap:
            return True

    return False


def _near_duplicate(text: str, history: list[str]) -> bool:
    current = _normalize(text)
    if not current:
        return False
    current_tokens = set(current.split())

    for candidate in history:
        cand = _normalize(candidate)
        if not cand:
            continue
        if cand == current:
            return True

        ratio = SequenceMatcher(None, current, cand).ratio()
        if ratio >= 0.9:
            return True

        cand_tokens = set(cand.split())
        union = current_tokens | cand_tokens
        if not union:
            continue
        jaccard = len(current_tokens & cand_tokens) / len(union)
        if jaccard >= 0.82:
            return True

    return False


def check_quality(
    post: str,
    source_link: str | None,
    score: int,
    is_llm_mode: bool,
    config: QualityConfig,
    history_posts: list[str],
    context_text: str | None = None,
) -> QualityResult:
    reasons: list[str] = []
    normalized = _normalize(post)

    if not normalized:
        reasons.append("Post is empty")

    if len(post) > config.max_post_length:
        reasons.append(f"Post exceeds max length ({len(post)} > {config.max_post_length})")

    if source_link is None or not source_link.strip():
        reasons.append("Source link is missing")

    if not _has_claim_or_insight(post, context_text=context_text):
        reasons.append("Post lacks a clear claim or insight")

    for phrase in config.generic_phrases:
        if phrase in normalized:
            reasons.append(f"Generic phrase detected: '{phrase}'")

    for phrase in config.banned_phrases:
        if phrase in normalized:
            reasons.append(f"Banned phrase detected: '{phrase}'")

    if _near_duplicate(post, history_posts):
        reasons.append("Duplicate or near-duplicate post detected")

    min_score = config.min_llm_score if is_llm_mode else config.min_rule_score
    if score < min_score:
        reasons.append(f"Score below threshold ({score} < {min_score})")

    return QualityResult(passed=not reasons, reasons=reasons)
