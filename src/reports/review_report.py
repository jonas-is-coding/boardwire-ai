from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.storage.json_store import JsonStore


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def generate_review_queue_report(review_queue_path: Path, report_path: Path) -> int:
    queue = JsonStore.load(review_queue_path, default=[])
    pending = [item for item in queue if item.get("status") == "pending_review"]
    pending_sorted = sorted(pending, key=lambda x: _parse_dt(x.get("created_at")), reverse=True)

    lines: list[str] = []
    lines.append("# Boardwire Review Queue")
    lines.append("")
    lines.append(f"## Pending: {len(pending_sorted)}")
    lines.append("")

    if not pending_sorted:
        lines.append("No pending review items.")
        lines.append("")
    else:
        for item in pending_sorted:
            source_item = item.get("source_item", {})
            title = str(source_item.get("title", "Untitled"))
            item_id = str(item.get("id", ""))
            score = item.get("score", "n/a")
            source = str(source_item.get("source", "Unknown"))
            created_at = str(item.get("created_at", ""))
            post = str(item.get("proposed_post", "")).strip()
            source_link = str(source_item.get("link", "")).strip()

            lines.append(f"### {title}")
            lines.append(f"ID: `{item_id}`")
            lines.append(f"Score: `{score}`")
            lines.append(f"Source: `{source}`")
            lines.append(f"Created: `{created_at}`")
            lines.append("")
            lines.append("Post:")
            lines.append(f"> {post}")
            lines.append("")
            lines.append("Source:")
            lines.append(source_link)
            lines.append("")
            lines.append("Approve:")
            lines.append(f"`python -m src.main --approve-review {item_id}`")
            lines.append("")
            lines.append("Reject:")
            lines.append(f"`python -m src.main --reject-review {item_id}`")
            lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return len(pending_sorted)
