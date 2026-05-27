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


def _build_article_markdown(item: dict) -> str:
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "Untitled")).strip() or "Untitled"
    source = str(source_item.get("source", "Unknown Source")).strip() or "Unknown Source"
    link = str(source_item.get("link", "")).strip()
    score = int(item.get("score") or 0)
    reason = str(item.get("reason", "")).strip()
    created_at = str(item.get("created_at", "")).strip()
    status = str(item.get("status", "unknown")).strip()
    proposed_post = str(item.get("proposed_post", "")).strip()

    lines = [
        "---",
        f'title: "{title.replace(chr(34), "\\\"")}"',
        f"source: {source}",
        f"source_url: {link or 'n/a'}",
        f"review_id: {item.get('id', '')}",
        f"status: {status}",
        f"score: {score}",
        f"created_at: {created_at or 'n/a'}",
        "---",
        "",
        f"# {title}",
        "",
    ]

    if reason:
        lines.extend(["## Warum das relevant ist", "", reason, ""])

    if proposed_post:
        lines.extend(["## Social Kurzfassung", "", proposed_post, ""])

    if link:
        lines.extend(["## Quelle", "", f"- [{source}]({link})", ""])

    lines.extend(
        [
            "## Vollartikel (Entwurf)",
            "",
            "Dieser Artikel wurde aus dem Review-Queue-Eintrag erzeugt und ist als Markdown für boardwire-web gedacht.",
            "",
            "### Kontext",
            f"- Quelle: **{source}**",
            f"- Score: **{score}**",
            "",
            "### Einordnung",
            "Boardwire bewertet hier primär den praktischen Nutzen für AI-Builders: Ändert das Thema messbar Capability, Zuverlässigkeit oder Kosten?",
            "",
            "### Nächste Schritte",
            "- Fakten gegen Primärquelle prüfen",
            "- Ggf. um Beispiele/Code ergänzen",
            "- Für boardwire-web veröffentlichen",
            "",
        ]
    )

    return "\n".join(lines)


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
        body = ai_article.strip() if isinstance(ai_article, str) and ai_article.strip() else _build_article_markdown(item)
        target.write_text(body + "\n", encoding="utf-8")
        written += 1
    return written
