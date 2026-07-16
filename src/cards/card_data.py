from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from dateutil import parser as date_parser

# Card layout templates. Selected deterministically by content type. All are
# on-brand dark editorial designs (no external/GitHub OG images).
LAYOUT_STAT = "stat"          # a hero number is the story (70B, 40%, 3x)
LAYOUT_CLAIM = "claim"        # a sharp takeaway, no number
LAYOUT_QUOTE = "quote"        # HN discussion / opinion pieces
LAYOUT_REPO = "repo"          # GitHub project: owner/repo + stars
LAYOUT_RELEASE = "release"    # a version release: version tag is the hero
LAYOUT_SECURITY = "security"  # vulnerability / security alert

# card_claim must ADD information, not restate the post title. Reject a claim
# that shares more than this fraction of its tokens with the title.
_CLAIM_TITLE_OVERLAP_MAX = 0.60
_CARD_CLAIM_MAX_WORDS = 8
_CARD_CONTEXT_MAX_CHARS = 90
_STAT_MAX_CHARS = 8

_SECURITY_KEYWORDS = (
    "vulnerability",
    "vuln",
    "cve",
    "0day",
    "0-day",
    "zero-day",
    "zero day",
    "exploit",
    "rce",
    "remote code execution",
    "malware",
    "backdoor",
    "data exfiltration",
    "prompt injection",
    "security flaw",
    "security fix",
    "security advisory",
    "supply chain",
)
_RELEASE_KEYWORDS = ("release", "released", "releases", "ships", "launches", "update", "version")
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?(?:-?rc\d+)?\b", re.IGNORECASE)
# Word-boundary matchers so short tokens like "rce"/"cve" don't match inside
# words ("pe-rce-ived", "open-sou-rce-s"). Built once at import.
_SECURITY_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _SECURITY_KEYWORDS) + r")\b", re.IGNORECASE
)
_RELEASE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _RELEASE_KEYWORDS) + r")\b", re.IGNORECASE
)


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
    # Populated for the repo / release layouts.
    repo_owner: str = ""
    repo_name: str = ""
    version_tag: str = ""
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


def extract_owner_repo(link: str) -> tuple[str, str] | None:
    """Return (owner, repo) for a github.com link, else None."""
    lowered = (link or "").lower()
    if "github.com/" not in lowered:
        return None
    try:
        path = link.split("github.com/", 1)[1]
    except IndexError:
        return None
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    # Strip a trailing .git and ignore non-repo owner pages.
    repo = re.sub(r"\.git$", "", repo)
    if owner in {"orgs", "sponsors", "topics", "collections", "features"}:
        return None
    return owner, repo


def extract_version(title: str, summary: str, link: str) -> str:
    """Extract a version tag (e.g. v2.1.210) from the item, else ''."""
    for text in (title, link, summary):
        m = _VERSION_RE.search(text or "")
        if m:
            tag = m.group(0)
            return tag if tag.lower().startswith("v") else f"v{tag}"
    return ""


def _is_security(title: str, summary: str, source: str) -> bool:
    return _SECURITY_RE.search(f"{title} {summary} {source}") is not None


def _is_release_like(title: str, summary: str, source: str, link: str) -> bool:
    if "/releases/" in (link or "").lower():
        return True
    return _RELEASE_RE.search(f"{title} {source}") is not None


def _select_layout(
    card_stat: str,
    source: str,
    link: str,
    summary: str,
    title: str,
    owner_repo: tuple[str, str] | None,
    version_tag: str,
) -> str:
    """Deterministic layout selection by content type.

    Priority: security > release > repo > stat > quote > claim. Security wins
    outright (distinct alert treatment); GitHub items get the repo/release
    treatment rather than a bare stat; non-GitHub items fall through to
    stat/quote/claim.
    """
    if _is_security(title, summary, source):
        return LAYOUT_SECURITY
    if version_tag and _is_release_like(title, summary, source, link):
        return LAYOUT_RELEASE
    if owner_repo:
        return LAYOUT_REPO
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

    owner_repo = extract_owner_repo(link)
    version_tag = extract_version(title, src_summary, link)
    layout = _select_layout(card_stat, source, link, src_summary, title, owner_repo, version_tag)

    repo_owner, repo_name = owner_repo if owner_repo else ("", "")

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
        repo_owner=repo_owner,
        repo_name=repo_name,
        version_tag=version_tag,
        card_headline=_shorten_words(post_title, 10),
        card_summary=card_context,
    )


def build_card_alt_text(card: CardData) -> str:
    """ALT text describing the card's actual content per layout."""
    parts: list[str] = [f"Boardwire {card.layout} card"]
    if card.source_label:
        parts.append(f"source {card.source_label}")
    if card.layout == LAYOUT_REPO and card.repo_owner:
        parts.append(f"repository {card.repo_owner}/{card.repo_name}")
    if card.layout == LAYOUT_RELEASE and card.version_tag:
        parts.append(f"release {card.version_tag}")
    if card.card_stat:
        stat = card.card_stat + (f" {card.stat_unit}" if card.stat_unit else "")
        parts.append(f"headline stat {stat}")
    if card.card_claim:
        parts.append(f"claim: {card.card_claim}")
    if card.card_context:
        parts.append(f"context: {card.card_context}")
    return ". ".join(parts)[:1000]
