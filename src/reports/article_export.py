from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from src.storage.json_store import JsonStore
from src.notifications import persona_voice as voice


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def _safe_iso_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return datetime.now(timezone.utc).date().isoformat()


_PLACEHOLDER_TEXT = {
    "local newsworthiness fallback",
    "n/a",
    "unknown",
}


def _clean_text(value: str | None) -> str:
    """Strip machine annotations so degraded-mode prose stays readable."""
    if not value:
        return ""
    text = str(value)
    # Drop internal cluster annotations like "[Cluster context: ...]".
    text = re.sub(r"\[Cluster context:[^\]]*\]", "", text)
    # Drop redundant "original: <url>" tails (the link lives in Sources).
    text = re.sub(r"[—-]?\s*original:\s*\S+", "", text, flags=re.IGNORECASE)
    # Collapse leftover whitespace.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text).strip()
    if text.lower() in _PLACEHOLDER_TEXT:
        return ""
    return text


def _front_matter(item: dict) -> str:
    """Publishable front matter for the static blog site."""
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "Untitled")).strip() or "Untitled"
    source = str(source_item.get("source", "Unknown Source")).strip() or "Unknown Source"
    link = str(source_item.get("link", "")).strip()
    date = _safe_iso_date(item.get("created_at"))

    escaped_title = title.replace('"', '\\"')

    lines = [
        "---",
        f'title: "{escaped_title}"',
        f"date: {date}",
        f"source: {source}",
        f"source_url: {link or 'n/a'}",
        "---",
        "",
        "",
    ]
    return "\n".join(lines)


def _fallback_article_body(item: dict) -> str:
    """Best-effort readable article when no LLM draft is available.

    This is a real blog post for a reader, not internal review documentation.
    It only restates facts we actually have, woven into prose.
    """
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "Untitled")).strip() or "Untitled"
    source = str(source_item.get("source", "Unknown Source")).strip() or "Unknown Source"
    link = str(source_item.get("link", "")).strip()
    summary = _clean_text(source_item.get("summary"))
    reason = _clean_text(item.get("reason"))

    paragraphs: list[str] = [f"# {title}", ""]

    # Lead with the editorial angle when we have it; it reads more like prose
    # than raw source metadata. Fall back to the cleaned source summary.
    lede = reason or summary
    if lede:
        paragraphs.extend([lede, ""])

    # Add the remaining grounded context as a second paragraph if distinct.
    extra = summary if lede is reason else reason
    if extra and extra != lede and extra.lower() not in lede.lower():
        paragraphs.extend([extra, ""])

    # Always give the reader the orientation of where this came from.
    paragraphs.extend(
        [
            f"This story surfaced via {source}. For the original details and any "
            "numbers we have not confirmed here, follow the source below.",
            "",
        ]
    )

    if link:
        paragraphs.extend(["## Sources", "", f"- [{source}]({link})", ""])

    return "\n".join(paragraphs)


def _build_article_markdown(item: dict) -> str:
    return _front_matter(item) + _fallback_article_body(item)


def export_review_articles(review_queue_path: Path, output_dir: Path) -> int:
    queue = JsonStore.load(review_queue_path, default=[])
    output_dir.mkdir(parents=True, exist_ok=True)

    exportable = [
        item
        for item in queue
        if item.get("status") in {"approved", "published_dry_run", "pending_review"}
    ]

    written = 0
    llm_calls = 0
    try:
        llm_budget = max(0, int(os.getenv("BOARDWIRE_TIFFANY_CALL_BUDGET", "3").strip()))
    except ValueError:
        llm_budget = 3

    for item in exportable:
        source_item = item.get("source_item", {})
        title = str(source_item.get("title", "Untitled"))
        date_prefix = _safe_iso_date(item.get("created_at"))
        filename = f"{date_prefix}-{_slugify(title)}-{item.get('id', 'item')}.md"
        target = output_dir / filename
        source_item = item.get("source_item", {})
        ai_article = None
        if llm_calls < llm_budget:
            ai_article = voice.tiffany_write_article(
            title=str(source_item.get("title", "Untitled")),
            source=str(source_item.get("source", "Unknown Source")),
            link=str(source_item.get("link", "")),
            status=str(item.get("status", "unknown")),
            score=int(item.get("score") or 0),
            reason=str(item.get("reason", "")),
            proposed_post=str(item.get("proposed_post", "")),
            summary=str(source_item.get("summary", "")),
            created_at=str(item.get("created_at", "")),
            )
            llm_calls += 1
        if isinstance(ai_article, str) and ai_article.strip():
            body = _front_matter(item) + ai_article.strip()
        else:
            body = _build_article_markdown(item)
        target.write_text(body + "\n", encoding="utf-8")
        written += 1
    return written


def write_article_for_item(item: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "Untitled"))
    date_prefix = _safe_iso_date(item.get("created_at"))
    filename = f"{date_prefix}-{_slugify(title)}-{item.get('id', 'item')}.md"
    target = output_dir / filename
    body = _build_article_markdown(item)
    target.write_text(body + "\n", encoding="utf-8")
    return target
