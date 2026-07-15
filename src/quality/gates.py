from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from dateutil import parser as date_parser

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


# Data point behind the version-only block: 37 of 141 published posts were
# bare version releases with ~0 engagement. A release only passes when the
# summary/dossier names a concrete capability.
_VERSION_PATTERN = r"\bv?\d+\.\d+(?:\.\d+)?(?:-rc\d+)?\b"
_VERSION_RE = re.compile(_VERSION_PATTERN, re.IGNORECASE)
DEFAULT_CAPABILITY_KEYWORDS = (
    "plugin",
    "mcp",
    "sandbox",
    "local",
    "weights",
    "api",
    "cli",
    "benchmark",
    "sdk",
    "dataset",
    "agent",
    "integration",
    "memory",
    "security fix",
    "vulnerability",
)
# Internal pipeline metadata must never leak into published text (a live post
# once contained "with 90 score").
_METADATA_LEAK_RE = re.compile(r"\b(?:with\s+)?\d{1,3}\s*(?:score|rank)\b", re.IGNORECASE)
_INTERNAL_FIELD_NAMES = (
    "source_tier",
    "engagement_score",
    "local_newsworthiness_score",
    "cluster_score",
    "newsworthiness",
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
    capability_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_CAPABILITY_KEYWORDS))


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


def is_version_dominant_title(title: str) -> bool:
    """True when a title is essentially "<project> vX.Y.Z" (a release note)."""
    t = (title or "").strip()
    if not t:
        return False
    match = _VERSION_RE.search(t)
    if not match:
        return False
    remainder = (t[: match.start()] + " " + t[match.end() :]).strip()
    remainder = re.sub(r"[^\w\s.-]", " ", remainder)
    # A bare release title leaves only the project name once the version is
    # removed; anything longer is a real headline that mentions a version.
    return len(remainder.split()) <= 3


def has_capability_signal(text: str, capability_keywords: list[str] | tuple[str, ...] = DEFAULT_CAPABILITY_KEYWORDS) -> bool:
    """True when text names a concrete capability or measurable claim."""
    normalized = _normalize(text)
    for keyword in capability_keywords:
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])", normalized):
            return True
    # Numeric % / x-factor claims count as concrete capability evidence.
    if re.search(r"\b\d+(?:\.\d+)?\s*%", normalized):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s?(?:x|×)\b|\b(?:x|×)\s?\d+(?:\.\d+)?\b", normalized):
        return True
    return False


def check_version_only_release(
    title: str,
    summary: str,
    capability_keywords: list[str] | tuple[str, ...] = DEFAULT_CAPABILITY_KEYWORDS,
) -> str | None:
    """Version-only block: reject "<project> vX.Y.Z" items without a concrete
    capability in the summary/dossier. Returns the rejection reason or None."""
    if not is_version_dominant_title(title):
        return None
    if has_capability_signal(f"{title} {summary}", capability_keywords):
        return None
    return f"Version-only release without concrete capability: '{title.strip()}'"


def check_metadata_leak(post: str) -> str | None:
    """Reject composed text that leaks internal pipeline metadata."""
    match = _METADATA_LEAK_RE.search(post or "")
    if match:
        return f"Internal metadata leaked into post: '{match.group(0).strip()}'"
    lowered = (post or "").lower()
    for name in _INTERNAL_FIELD_NAMES:
        if name in lowered:
            return f"Internal field name leaked into post: '{name}'"
    return None


def _parse_release_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = date_parser.parse(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def find_recent_release(
    records: list[dict],
    project: str,
    version: str,
    now: datetime | None = None,
    window_days: int = 14,
) -> dict | None:
    """Return the previous publish record for the same (project, version)
    within the dedupe window, or None. Evidence for this gate: ollama
    v0.30.11 was published 3 times within two days."""
    if not project or not version:
        return None
    now = now or datetime.now(timezone.utc)
    project_key = project.strip().lower()
    version_key = version.strip().lower().lstrip("v")
    for record in records:
        if str(record.get("project", "")).strip().lower() != project_key:
            continue
        if str(record.get("version", "")).strip().lower().lstrip("v") != version_key:
            continue
        published = _parse_release_dt(record.get("published_at"))
        if published is None or now - published <= timedelta(days=window_days):
            return record
    return None


def check_quality(
    post: str,
    source_link: str | None,
    score: int,
    is_llm_mode: bool,
    config: QualityConfig,
    history_posts: list[str],
    context: str = "review",
    context_text: str | None = None,
    allow_duplicate: bool = False,
    item_title: str | None = None,
    item_summary: str | None = None,
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

    leak_reason = check_metadata_leak(post)
    if leak_reason:
        reasons.append(leak_reason)

    if item_title is not None:
        version_reason = check_version_only_release(
            item_title, item_summary or "", config.capability_keywords
        )
        if version_reason:
            reasons.append(version_reason)

    # Breaking items are exempted from the near-duplicate gate: a fast-developing
    # story (e.g. a release followed by a ban/suspension) legitimately reuses the
    # same terms as the earlier post, but is genuine news rather than a repost.
    if context in {"review", "publish"} and not allow_duplicate and _near_duplicate(post, history_posts):
        reasons.append("Duplicate or near-duplicate post detected")

    min_score = config.min_llm_score if is_llm_mode else config.min_rule_score
    if score < min_score:
        reasons.append(f"Score below threshold ({score} < {min_score})")

    return QualityResult(passed=not reasons, reasons=reasons)
