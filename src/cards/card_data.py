from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from dateutil import parser as date_parser


@dataclass(slots=True)
class CardData:
    review_id: str
    category: str
    headline: str
    summary: str
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


def _category(title: str, post: str, source: str) -> str:
    t = f"{title} {post} {source}".lower()
    if "arxiv" in t or "research" in t or "paper" in t:
        return "AI RESEARCH"
    if "agent" in t or "workflow" in t:
        return "AGENTS"
    if "open source" in t or "open-source" in t or "open model" in t:
        return "OPEN SOURCE"
    if "infra" in t or "inference" in t or "deployment" in t:
        return "INFRA"
    if "benchmark" in t or "evaluation" in t:
        return "EVALUATION"
    return "AI NEWS"


def _shorten(text: str, max_len: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _summary_from_item(post: str, reason: str) -> str:
    post_clean = " ".join(post.split())
    reason_clean = " ".join(reason.split())
    if reason_clean:
        summary = f"{reason_clean}. {post_clean}"
    else:
        summary = post_clean
    return _shorten(summary, 260)


def from_review_item(item: dict) -> CardData:
    src = item.get("source_item", {})
    title = str(src.get("title", "Untitled"))
    post = str(item.get("proposed_post", ""))
    source = str(src.get("source", "Unknown Source"))
    created_at = str(item.get("created_at", ""))

    dt = _parse_dt(created_at)
    date_label = dt.strftime("%Y-%m-%d")

    return CardData(
        review_id=str(item.get("id", "unknown")),
        category=_category(title=title, post=post, source=source),
        headline=_shorten(title, 130),
        summary=_summary_from_item(post=post, reason=str(item.get("reason", ""))),
        source=source,
        date_label=date_label,
        footer="BOARDWIRE",
    )
