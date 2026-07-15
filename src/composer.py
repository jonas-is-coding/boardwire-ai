"""Budget-aware Bluesky post composition.

Bluesky allows 300 graphemes per post; this module budgets in UTF-8 bytes as
the conservative bound (byte count >= grapheme count for any string), which
also matches the facet indices the publisher computes (byte offsets).

The old pipeline hard-truncated the body with ``[:280]`` and then trimmed
again byte-wise in the publisher — live posts ended mid-sentence and hashtags
never survived. The new composition reserves the link suffix and the hashtag
line FIRST, then fits hook + question + fact into what remains, shortening
only at word boundaries.

Priority when space is tight: link > hashtags > hook > question > fact.
Structure of the composed body:

    hook line (title)
    <blank>
    supporting-fact line (subtitle)
    <blank>
    optional question line
    <blank>
    hashtag line (2-3 tags)

The source link is appended by the publisher (with a link facet), so this
module only *reserves* its bytes.
"""

from __future__ import annotations

import hashlib
import re

# Conservative Bluesky budget: 300 graphemes; we bound by 300 UTF-8 bytes.
BLUESKY_MAX_BYTES = 300
LINK_PREFIX = "\n\n🔗 "
_SEPARATOR_BYTES = 2  # "\n\n"
_ELLIPSIS = "…"
# Below this many bytes a shortened fact line is noise, so it is dropped.
_MIN_FACT_BYTES = 24

# Share of posts that get a closing engagement question (Task 5). Deterministic
# by item key so a rerun composes the same variant.
QUESTION_VARIANT_PERCENT = 40

_ENGAGEMENT_BAIT_PHRASES = (
    "what do you think",
    "what are your thoughts",
    "thoughts?",
    "let me know",
    "agree?",
    "am i right",
    "who else",
    "like and repost",
    "follow for more",
)


def byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def shorten_at_word_boundary(text: str, max_bytes: int) -> str:
    """Shorten text to at most max_bytes, never cutting mid-word.

    The result either ends with a clean sentence (., !, ?) or with an
    ellipsis placed on a word boundary. Returns "" when nothing meaningful
    fits.
    """
    text = text.strip()
    if byte_len(text) <= max_bytes:
        return text
    budget = max_bytes - byte_len(_ELLIPSIS)
    if budget <= 0:
        return ""
    # Byte-safe cut, then back off to the last whitespace so no word is split.
    cut = text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    if cut and len(cut) < len(text) and not text[len(cut)].isspace():
        space_idx = max(cut.rfind(" "), cut.rfind("\n"))
        if space_idx <= 0:
            return ""
        cut = cut[:space_idx]
    cut = cut.rstrip().rstrip(",;:—-")
    if not cut:
        return ""
    if cut[-1] in ".!?":
        return cut
    return f"{cut}{_ELLIPSIS}"


def compose_post_body(
    hook: str,
    fact: str = "",
    hashtags: list[str] | None = None,
    source_link: str | None = None,
    question: str = "",
    limit: int = BLUESKY_MAX_BYTES,
) -> str:
    """Compose the Bluesky body so that body + link suffix fits the budget.

    The link suffix bytes are reserved but NOT appended — the publisher owns
    the suffix and its link facet. Hashtags are reserved before any prose so
    they always survive into the published text.
    """
    hook = " ".join((hook or "").split())
    fact = " ".join((fact or "").split())
    question = " ".join((question or "").split())
    tags_line = " ".join(t.strip() for t in (hashtags or []) if t and t.strip())

    budget = limit
    if source_link and source_link.strip():
        budget -= byte_len(f"{LINK_PREFIX}{source_link.strip()}")

    remaining = budget
    if tags_line:
        remaining -= byte_len(tags_line) + _SEPARATOR_BYTES

    hook_fitted = shorten_at_word_boundary(hook, max(0, remaining))
    remaining -= byte_len(hook_fitted)

    question_fitted = ""
    if question:
        needed = _SEPARATOR_BYTES + byte_len(question)
        if needed <= remaining:
            question_fitted = question
            remaining -= needed

    fact_fitted = ""
    if fact:
        available = remaining - _SEPARATOR_BYTES
        if available >= _MIN_FACT_BYTES:
            fact_fitted = shorten_at_word_boundary(fact, available)

    parts = [hook_fitted]
    if fact_fitted:
        parts.append(fact_fitted)
    if question_fitted:
        parts.append(question_fitted)
    if tags_line:
        parts.append(tags_line)
    return "\n\n".join(p for p in parts if p).strip()


def select_format_variant(item_key: str) -> str:
    """Deterministically pick "question" for ~40% of items, else "plain".

    Uses a stable hash of the item key (source link) so reruns and tests are
    reproducible.
    """
    digest = hashlib.sha1((item_key or "").encode("utf-8")).hexdigest()
    return "question" if int(digest, 16) % 100 < QUESTION_VARIANT_PERCENT else "plain"


def validate_question(question: str | None, max_chars: int = 60) -> str | None:
    """Validate an LLM-suggested closing question.

    Must be a short genuine question: ends with "?", within max_chars, and not
    a generic engagement-bait phrase. Returns the cleaned question or None.
    """
    if not question:
        return None
    q = " ".join(str(question).split())
    if not q or len(q) > max_chars or not q.endswith("?"):
        return None
    lowered = q.lower()
    if any(p in lowered for p in _ENGAGEMENT_BAIT_PHRASES):
        return None
    if not re.search(r"[a-zA-Z]{2,}", q):
        return None
    return q
