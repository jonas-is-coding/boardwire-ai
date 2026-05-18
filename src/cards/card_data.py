from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from dateutil import parser as date_parser


@dataclass(slots=True)
class CardData:
    review_id: str
    card_headline: str
    card_summary: str
    visual_theme: str
    source_label: str
    source: str
    date_label: str
    footer: str


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
    s = source.upper().strip()
    s = s.replace("BLOG", "").strip()
    s = s.replace("&", "AND")
    return _shorten_chars(" ".join(s.split()), 24)


def _clean_post_text(post: str) -> str:
    text = " ".join(post.split())
    text = re.sub(r"(?i)matched keywords?:[^.]*\.?\s*", "", text).strip()
    return text


def _card_summary(title: str, post: str, summary: str, reason: str) -> str:
    clean_post = _clean_post_text(post)
    clean_summary = " ".join(summary.split())
    base = clean_summary or clean_post or reason
    base = re.sub(r"\s+", " ", base).strip()
    if not base:
        return ""
    lower = base.lower()
    title_lower = title.lower()
    if title_lower and lower == title_lower:
        base = clean_post or reason
    base = re.sub(r"(?i)^why it matters:\s*", "", base).strip()
    base = re.sub(r"(?i)^the signal:\s*", "", base).strip()
    base = re.sub(r"(?i)^watch:\s*", "", base).strip()
    return _shorten_chars(base, 140)


def _card_headline(title: str) -> str:
    headline = _shorten_words(title, 10)
    return _shorten_chars(headline, 82)


def from_review_item(item: dict) -> CardData:
    src = item.get("source_item", {})
    title = str(src.get("title", "Untitled"))
    post = str(item.get("proposed_post", ""))
    src_summary = str(src.get("summary", ""))
    source = str(src.get("source", "Unknown Source"))
    created_at = str(item.get("created_at", ""))
    reason = str(item.get("reason", ""))

    dt = _parse_dt(created_at)
    date_label = dt.strftime("%Y-%m-%d")

    sarah = item.get("sarah_package") or {}
    sarah_title = str(sarah.get("title", "")).strip()
    sarah_description = str(sarah.get("description", "")).strip() or str(sarah.get("subtitle", "")).strip()

    if sarah_title:
        card_headline = _card_headline(sarah_title)
    else:
        card_headline = _card_headline(title)

    if sarah_description:
        body = re.sub(r"(?i)^why it matters:\s*", "", sarah_description).strip()
        card_summary = _shorten_chars(body, 140)
    else:
        card_summary = _card_summary(title=title, post=post, summary=src_summary, reason=reason)

    return CardData(
        review_id=str(item.get("id", "unknown")),
        card_headline=card_headline,
        card_summary=card_summary,
        visual_theme=_visual_theme(title=title, post=post, source=source, summary=src_summary),
        source_label=_source_label(source),
        source=source,
        date_label=date_label,
        footer="BOARDWIRE",
    )
