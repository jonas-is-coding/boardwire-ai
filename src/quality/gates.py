from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_GENERIC_FALLBACK_SENTENCES = (
    "the signal to watch",
    "check whether this changes",
    "agent reliability in production is still the hard part",
    "training improvements matter most",
)
_BORING_RELEASE_PHRASES = (
    "ships version",
    "claims improved performance",
    "released with enhancements",
    "bug fixes and improvements",
    "performance improvements",
    "new version is available",
)
_CONCRETE_BUILDER_TERMS = (
    "api",
    "cli",
    "sdk",
    "mcp",
    "plugin",
    "integration",
    "sandbox",
    "local",
    "weights",
    "dataset",
    "benchmark",
    "browser automation",
    "rag",
    "vector",
    "inference",
)
_BUILDER_IMPLICATION_TERMS = (
    "builders",
    "developers",
    "workflow",
    "workflows",
    "infrastructure",
    "primitive",
    "production",
    "deployment",
    "coding loop",
    "retrieval",
    "cost",
    "reliability",
    "turns",
    "enables",
    "reduces",
    "cuts",
    "means",
    "matters",
)


@dataclass(slots=True)
class QualityConfig:
    max_post_length: int
    min_llm_score: int
    min_rule_score: int
    max_defer_count: int
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


def _is_boring_release_post(text: str) -> bool:
    normalized = _normalize(text)
    if not any(phrase in normalized for phrase in _BORING_RELEASE_PHRASES):
        return False
    if any(term in normalized for term in _CONCRETE_BUILDER_TERMS):
        return False
    if re.search(r"\b\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s?(?:x|×)\b", normalized):
        return False
    return True


def _has_builder_implication(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in _BUILDER_IMPLICATION_TERMS)


def _is_dry_ships_outperforms_stars_post(text: str) -> bool:
    normalized = _normalize(text)
    has_ships_feature = bool(re.search(r"\b[\w.-]+\s+(?:library\s+)?ships\s+", normalized))
    has_outperforms = "outperforms others" in normalized
    has_stars = bool(re.search(r"\bwith\s+\+\d[\d,]*\s+stars\b", normalized))
    if not (has_ships_feature and has_outperforms and has_stars):
        return False
    return not _has_builder_implication(normalized)


def check_quality(
    post: str,
    source_link: str | None,
    score: int,
    is_llm_mode: bool,
    config: QualityConfig,
    history_posts: list[str],
    context: str = "review",
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

    for phrase in _GENERIC_FALLBACK_SENTENCES:
        if phrase in normalized:
            reasons.append(f"Generic fallback sentence detected: '{phrase}'")

    if _is_boring_release_post(post):
        reasons.append("Boring release phrasing without concrete builder capability")

    if _is_dry_ships_outperforms_stars_post(post):
        reasons.append("Dry ships/outperforms/stars post without builder implication")

    if context in {"review", "publish"} and _near_duplicate(post, history_posts):
        reasons.append("Duplicate or near-duplicate post detected")

    min_score = config.min_llm_score if is_llm_mode else config.min_rule_score
    if score < min_score:
        reasons.append(f"Score below threshold ({score} < {min_score})")

    return QualityResult(passed=not reasons, reasons=reasons)
