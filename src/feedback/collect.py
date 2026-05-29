from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger
from typing import Any

from src.feedback.bluesky_metrics import fetch_post_metrics
from src.feedback.engagement_store import record_snapshot

# Posts older than this are unlikely to still gain engagement, so we stop
# polling them to keep each run's API footprint small.
_DEFAULT_MAX_TRACK_AGE_DAYS = 14


@dataclass(slots=True)
class CollectionSummary:
    tracked: int
    measured: int
    missing: int


def _too_old(published_at: str | None, max_age_days: int, now: datetime) -> bool:
    if not published_at:
        return False
    try:
        from dateutil import parser as date_parser

        published = date_parser.parse(published_at)
    except (ValueError, OverflowError, TypeError):
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (now - published.astimezone(timezone.utc)).days > max_age_days


def collect_engagement(
    published: list[dict[str, Any]],
    store: dict[str, Any],
    logger: Logger,
    max_track_age_days: int = _DEFAULT_MAX_TRACK_AGE_DAYS,
) -> CollectionSummary:
    """Fetch fresh engagement for trackable Bluesky posts and append snapshots."""
    now = datetime.now(timezone.utc)
    trackable = [
        p
        for p in published
        if (p.get("external_id") or p.get("url"))
        and p.get("platform") == "bluesky"
        and not _too_old(p.get("published_at"), max_track_age_days, now)
    ]
    if not trackable:
        logger.info("No trackable Bluesky posts within %d days", max_track_age_days)
        return CollectionSummary(tracked=0, measured=0, missing=0)

    uri_to_post: dict[str, dict[str, Any]] = {}
    for post in trackable:
        uri = post.get("external_id") or post.get("url")
        if uri:
            uri_to_post[uri] = post

    metrics = fetch_post_metrics(list(uri_to_post.keys()), logger)

    measured = 0
    for uri, post in uri_to_post.items():
        post_metrics = metrics.get(uri)
        if post_metrics is None:
            continue
        record_snapshot(store, post, post_metrics, observed_at=now)
        measured += 1

    missing = len(uri_to_post) - measured
    logger.info(
        "Engagement collected: tracked=%d measured=%d missing=%d",
        len(uri_to_post),
        measured,
        missing,
    )
    return CollectionSummary(tracked=len(uri_to_post), measured=measured, missing=missing)
