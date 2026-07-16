from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from dateutil import parser as date_parser

# Card layout templates (Task 3). Selected deterministically by content type.
LAYOUT_STAT = "stat"
LAYOUT_CLAIM = "claim"
LAYOUT_QUOTE = "quote"

# card_claim must ADD information, not restate the post title. Reject a claim
# that shares more than this fraction of its tokens with the title.
_CLAIM_TITLE_OVERLAP_MAX = 0.60
_CARD_CLAIM_MAX_WORDS = 8
_CARD_CONTEXT_MAX_CHARS = 90
_STAT_MAX_CHARS = 8


@dataclass(slots=True)
class CardData:
    review_id: str
    layout: str
    source_label: str
    source: str
    date_label: str
    visual_theme: str
    wordmark: str = "BOARDWIRE"
    card_stat: str = ""
    stat_unit: str = ""
    card_claim: str = ""
    card_context: str = ""
    # Legacy fallbacks kept so older callers / tests still render something.
    card_headline: str = ""
    card_summary: str = ""


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _visual_theme(title: str, post: str, source: str, summary: str) -> str:
    t = f"{title} {post} {source}".lower()
    s = summary.lower()
    joined = f"{t} {s}"
    if "robot" in joined or "robotics" in joined:
        return "robotics"
    if "arxiv" in joined or "research" in joined or "paper" in joined:
        return "research"
    if "agent" in t or "workflow" in t:
        return "agents"
    if "open source" in t or "open-source" in t or "open model" in t:
        return "open_source"
    if "infra" in t or "inference" in t or "deployment" in t:
        return "infrastructure"
    return "news"


def _shorten_chars(text: str, max_len: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _shorten_words(text: str, max_words: int) -> str:
    clean = " ".join(text.split())
    words = clean.split(" ")
    if len(words) <= max_words:
        return clean
    return " ".join(words[:max_words]).rstrip(".,;:") + "…"


def _source_label(source: str) -> str:
    s = source.strip()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    s = re.sub(r"(?i)\b(releases?|feed|rss|atom|news|blog)\s*$", "", s).strip()
    s = s.replace("&", "and")
    s = " ".join(s.split()).upper()
    return _shorten_chars(s, 36)


def _token_overlap_ratio(a: str, b: str) -> float:
    """Fraction of a's word-tokens that also appear in b (no new deps)."""
    ta = set(re.findall(r"[a-z0-9]+", a.lower()))
    tb = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def valid_card_claim(claim: str, post_title: str) -> bool:
    """A claim is valid when it is present, within the word budget, and does
    not merely restate the post title (token overlap <= 60%)."""
    clean = " ".join((claim or "").split())
    if not clean:
        return False
    if len(clean.split()) > _CARD_CLAIM_MAX_WORDS:
        return False
    return _token_overlap_ratio(clean, post_title or "") <= _CLAIM_TITLE_OVERLAP_MAX


def valid_card_context(context: str) -> bool:
    """Valid when non-empty and within the 90-char budget. Never truncated on
    the card: an over-budget context is rejected here and a fallback is used."""
    clean = " ".join((context or "").split())
    return bool(clean) and len(clean) <= _CARD_CONTEXT_MAX_CHARS


def _first_fitting_fragment(text: str, max_chars: int) -> str:
    """Return the longest leading run of complete sentences / `·` fragments
    that fits in max_chars — a complete unit, never a mid-sentence cut."""
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    if len(clean) <= max_chars:
        return clean
    # Prefer splitting on sentence enders, then on `·`, then on commas.
    for pattern in (r"(?<=[.!?])\s+", r"\s*·\s*", r",\s+"):
        parts = re.split(pattern, clean)
        acc = ""
        sep = " · " if "·" in pattern else " "
        for part in parts:
            candidate = part if not acc else f"{acc}{sep}{part}"
            if len(candidate) <= max_chars:
                acc = candidate
            else:
                break
        acc = acc.strip(" ·,")
        if acc:
            return acc
    # Last resort: a single leading word run (still whole words, no mid-word).
    words = clean.split(" ")
    acc = ""
    for w in words:
        candidate = w if not acc else f"{acc} {w}"
        if len(candidate) <= max_chars:
            acc = candidate
        else:
            break
    return acc.strip()


def _split_stat(card_stat: str) -> tuple[str, str]:
    """Split a hero token into (value, unit). '104 pts' -> ('104','pts');
    '+607★' -> ('+607★',''); '1-bit' -> ('1-bit','')."""
    stat = card_stat.strip()
    if not stat:
        return "", ""
    if " " in stat:
        value, unit = stat.split(" ", 1)
        return value.strip(), unit.strip()
    return stat, ""


def _clean_post_text(post: str) -> str:
    text = " ".join(post.split())
    text = re.sub(r"(?i)matched keywords?:[^.]*\.?\s*", "", text).strip()
    return text


def _select_layout(card_stat: str, source: str, link: str, summary: str) -> str:
    """Deterministic layout selection by content type."""
    if card_stat.strip():
        return LAYOUT_STAT
    s = f"{source} {link}".lower()
    is_discussion = (
        "hackernews" in s
        or "hacker news" in s
        or "news.ycombinator.com" in link.lower()
    )
    is_opinion = any(k in summary.lower() for k in ("opinion", "essay", "perspective", "i think", "we argue"))
    if is_discussion or is_opinion:
        return LAYOUT_QUOTE
    return LAYOUT_CLAIM


def _fallback_claim(sarah_title: str, title: str, post_title: str) -> str:
    """Pick a claim that adds information when the LLM claim is missing/invalid."""
    for candidate in (sarah_title, title):
        cand = " ".join((candidate or "").split())
        if cand and valid_card_claim(cand, post_title):
            return _shorten_words(cand, _CARD_CLAIM_MAX_WORDS)
    # Nothing distinct available — fall back to the shortened title so the card
    # still says something; the layout still adds the stat/context/context.
    return _shorten_words(title or sarah_title or "", _CARD_CLAIM_MAX_WORDS)


def from_review_item(item: dict) -> CardData:
    src = item.get("source_item", {})
    title = str(src.get("title", "Untitled"))
    post = str(item.get("proposed_post", ""))
    src_summary = str(src.get("summary", ""))
    source = str(src.get("source", "Unknown Source"))
    link = str(src.get("link", ""))
    created_at = str(item.get("created_at", ""))

    dt = _parse_dt(created_at)
    date_label = dt.strftime("%Y-%m-%d")

    sarah = item.get("sarah_package") or {}
    sarah_title = str(sarah.get("title", "")).strip()
    post_title = sarah_title or title

    # Card fields from Sarah, validated (never truncated on the card).
    raw_stat = str(sarah.get("card_stat", "")).strip()
    card_stat = raw_stat if len(raw_stat) <= _STAT_MAX_CHARS else ""
    stat_value, stat_unit = _split_stat(card_stat)

    raw_claim = str(sarah.get("card_claim", "")).strip()
    if valid_card_claim(raw_claim, post_title):
        card_claim = _shorten_words(raw_claim, _CARD_CLAIM_MAX_WORDS)
    else:
        card_claim = _fallback_claim(sarah_title, title, post_title)

    raw_context = str(sarah.get("card_context", "")).strip()
    if valid_card_context(raw_context):
        card_context = raw_context
    else:
        # Reject over-budget/empty context; derive a COMPLETE fallback fragment
        # from the description/subtitle/summary (never a mid-sentence cut).
        source_context = (
            str(sarah.get("description", "")).strip()
            or str(sarah.get("subtitle", "")).strip()
            or _clean_post_text(post)
            or src_summary
        )
        source_context = re.sub(r"(?i)^why it matters:\s*", "", source_context).strip()
        card_context = _first_fitting_fragment(source_context, _CARD_CONTEXT_MAX_CHARS)

    layout = _select_layout(card_stat, source, link, src_summary)

    return CardData(
        review_id=str(item.get("id", "unknown")),
        layout=layout,
        source_label=_source_label(source),
        source=source,
        date_label=date_label,
        visual_theme=_visual_theme(title=title, post=post, source=source, summary=src_summary),
        wordmark="BOARDWIRE",
        card_stat=stat_value,
        stat_unit=stat_unit,
        card_claim=card_claim,
        card_context=card_context,
        card_headline=_shorten_words(post_title, 10),
        card_summary=card_context,
    )


def build_card_alt_text(card: CardData) -> str:
    """ALT text describing the card's actual content: stat, claim, context."""
    parts: list[str] = [f"Boardwire {card.layout} card"]
    if card.source_label:
        parts.append(f"source {card.source_label}")
    if card.card_stat:
        stat = card.card_stat + (f" {card.stat_unit}" if card.stat_unit else "")
        parts.append(f"headline stat {stat}")
    if card.card_claim:
        parts.append(f"claim: {card.card_claim}")
    if card.card_context:
        parts.append(f"context: {card.card_context}")
    return ". ".join(parts)[:1000]


def build_github_og_alt(owner: str, repo: str, description: str = "") -> str:
    """ALT text for the GitHub-preview card variant."""
    base = f"GitHub repository preview card for {owner}/{repo}"
    if description.strip():
        base += f": {description.strip()}"
    return base[:1000]
