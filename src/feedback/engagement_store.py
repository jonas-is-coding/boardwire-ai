from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser

from src.feedback.bluesky_metrics import PostMetrics

# An engagement record accumulates time-series snapshots so we can later study
# how a post grew, not just its final state. The training label uses the peak
# observed engagement (see virality_label).
#
# engagement.json shape:
#   { "<post_id>": {
#         "id": str, "uri": str, "published_at": str,
#         "snapshots": [ {observed_at, age_hours, like_count, repost_count,
#                         reply_count, quote_count, total_engagement}, ... ] } }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = date_parser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_hours(published_at: str | None, observed_at: datetime) -> float | None:
    published = _parse_dt(published_at)
    if published is None:
        return None
    delta = observed_at - published
    return round(delta.total_seconds() / 3600.0, 2)


def record_snapshot(
    store: dict[str, Any],
    post: dict[str, Any],
    metrics: PostMetrics,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Append a metrics snapshot for one published post. Mutates and returns store."""
    observed_at = observed_at or datetime.now(timezone.utc)
    post_id = post.get("id")
    if not post_id:
        return store

    record = store.get(post_id)
    if record is None:
        record = {
            "id": post_id,
            "uri": post.get("external_id") or post.get("url"),
            "published_at": post.get("published_at"),
            "snapshots": [],
        }
        store[post_id] = record

    snapshot = {
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "age_hours": _age_hours(post.get("published_at"), observed_at),
        "like_count": metrics.like_count,
        "repost_count": metrics.repost_count,
        "reply_count": metrics.reply_count,
        "quote_count": metrics.quote_count,
        "total_engagement": metrics.total_engagement,
    }
    record["snapshots"].append(snapshot)
    return store


def latest_snapshot(record: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = record.get("snapshots") or []
    return snapshots[-1] if snapshots else None


def virality_label(record: dict[str, Any]) -> int:
    """Peak observed weighted engagement for a post (0 if never measured)."""
    snapshots = record.get("snapshots") or []
    if not snapshots:
        return 0
    return max(int(s.get("total_engagement", 0) or 0) for s in snapshots)


def is_mature(record: dict[str, Any], min_age_hours: float = 24.0) -> bool:
    """True once we have a snapshot taken at least min_age_hours after publish.

    Younger posts haven't had time to accumulate engagement and would teach the
    model the wrong thing, so they are excluded from training.
    """
    for snapshot in record.get("snapshots") or []:
        age = snapshot.get("age_hours")
        if age is not None and age >= min_age_hours:
            return True
    return False
