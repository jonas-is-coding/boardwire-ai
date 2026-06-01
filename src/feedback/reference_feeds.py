"""Collect posts from comparable larger Bluesky channels for virality training.

This is opt-in transfer learning for the virality model: with too few of our own
posts the model can't learn what works, so we let it also study the public posts
of larger channels in our niche. It uses the same public, unauthenticated
AppView as the engagement collector (``app.bsky.feed.getAuthorFeed``) — no
Bluesky secrets required. With no reference handles configured, nothing changes.

The dataset layer normalises each account's engagement into a per-account
z-score, so a 50k-follower channel doesn't simply teach "get more followers";
see ``dataset._build_reference_training_data``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger
from typing import Any

from dateutil import parser as date_parser

from src.feedback.bluesky_metrics import PostMetrics, _get_with_retry

# Public, unauthenticated AppView — same host the engagement collector uses.
_AUTHOR_FEED_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"

# getAuthorFeed accepts at most 100 items per page.
_MAX_PAGE_SIZE = 100


@dataclass(slots=True)
class ReferencePost:
    handle: str
    uri: str
    text: str
    created_at: str | None
    like_count: int
    repost_count: int
    reply_count: int
    quote_count: int
    has_link: bool

    @property
    def total_engagement(self) -> int:
        # Reuse the exact weighting our own posts are scored with so the label is
        # comparable across accounts.
        return PostMetrics(
            uri=self.uri,
            like_count=self.like_count,
            repost_count=self.repost_count,
            reply_count=self.reply_count,
            quote_count=self.quote_count,
        ).total_engagement

    def to_post_dict(self) -> dict[str, Any]:
        """Shape a foreign post like our own published-post records.

        ``embed_link`` forces a unique embedding-cache key (the AT-URI) so two
        foreign posts linking to the same article are not collapsed; no ``score``
        key is set because the internal funnel score doesn't exist for them.
        """
        return {
            "id": self.uri,
            "platform": "bluesky",
            "post": self.text,
            "source_title": self.text[:120],
            "source_link": self.uri if self.has_link else None,
            "embed_link": self.uri,
            "published_at": self.created_at,
        }


@dataclass(slots=True)
class ReferenceConfig:
    handles: tuple[str, ...]
    max_posts_per_handle: int
    min_account_posts: int
    own_weight: float

    @property
    def enabled(self) -> bool:
        return bool(self.handles)


def _flag_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(h.strip() for h in raw.split(",") if h.strip())


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def load_reference_config() -> ReferenceConfig:
    return ReferenceConfig(
        handles=_flag_list("BOARDWIRE_VIRALITY_REFERENCE_HANDLES"),
        max_posts_per_handle=max(
            1, _int("BOARDWIRE_VIRALITY_REFERENCE_MAX_POSTS", 100)
        ),
        min_account_posts=max(
            2, _int("BOARDWIRE_VIRALITY_REFERENCE_MIN_POSTS", 5)
        ),
        own_weight=max(1.0, _float("BOARDWIRE_VIRALITY_OWN_WEIGHT", 3.0)),
    )


def _age_hours(created_at: str | None, now: datetime) -> float | None:
    if not created_at:
        return None
    try:
        dt = date_parser.parse(created_at)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt.astimezone(timezone.utc)).total_seconds() / 3600.0


def _detect_link(record: dict[str, Any]) -> bool:
    embed = record.get("embed") or {}
    etype = str(embed.get("$type", ""))
    if "external" in etype:
        return True
    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            if "link" in str(feature.get("$type", "")):
                return True
    return "http://" in (record.get("text") or "") or "https://" in (
        record.get("text") or ""
    )


def _parse_feed_item(handle: str, item: dict[str, Any]) -> ReferencePost | None:
    # Skip reposts (they carry a ``reason``) — we only want the author's own
    # original posts as training signal.
    if item.get("reason"):
        return None
    post = item.get("post") or {}
    record = post.get("record") or {}
    # Skip replies: thread replies behave differently from standalone posts.
    if record.get("reply") is not None:
        return None
    uri = post.get("uri")
    text = record.get("text")
    if not uri or not text:
        return None
    return ReferencePost(
        handle=handle,
        uri=uri,
        text=text,
        created_at=record.get("createdAt") or post.get("indexedAt"),
        like_count=int(post.get("likeCount", 0) or 0),
        repost_count=int(post.get("repostCount", 0) or 0),
        reply_count=int(post.get("replyCount", 0) or 0),
        quote_count=int(post.get("quoteCount", 0) or 0),
        has_link=_detect_link(record),
    )


def _fetch_author_feed(
    handle: str, max_posts: int, min_age_hours: float, logger: Logger
) -> list[ReferencePost]:
    now = datetime.now(timezone.utc)
    collected: list[ReferencePost] = []
    cursor: str | None = None
    # Cap pages defensively so a misconfigured handle can't loop forever.
    max_pages = max(1, (max_posts // _MAX_PAGE_SIZE) + 2)

    for _ in range(max_pages):
        if len(collected) >= max_posts:
            break
        params: list[tuple[str, str]] = [
            ("actor", handle),
            ("limit", str(min(_MAX_PAGE_SIZE, max_posts - len(collected)))),
            ("filter", "posts_no_replies"),
        ]
        if cursor:
            params.append(("cursor", cursor))

        resp = _get_with_retry(_AUTHOR_FEED_URL, params, logger)
        if resp is None or resp.status_code >= 400:
            status = resp.status_code if resp is not None else "no-response"
            logger.warning("Reference feed %s skipped (status: %s)", handle, status)
            break
        try:
            body = resp.json()
        except ValueError:
            logger.warning("Reference feed %s returned non-JSON", handle)
            break

        for item in body.get("feed", []):
            rp = _parse_feed_item(handle, item)
            if rp is None:
                continue
            # Only mature posts: very recent ones haven't accrued engagement and
            # would teach the wrong thing (same rule as our own posts).
            age = _age_hours(rp.created_at, now)
            if age is not None and age < min_age_hours:
                continue
            collected.append(rp)
            if len(collected) >= max_posts:
                break

        cursor = body.get("cursor")
        if not cursor:
            break

    logger.info("Reference feed %s: %d mature posts", handle, len(collected))
    return collected


def fetch_reference_posts(
    config: ReferenceConfig, logger: Logger, min_age_hours: float = 24.0
) -> list[ReferencePost]:
    """Fetch mature original posts for every configured reference handle."""
    posts: list[ReferencePost] = []
    for handle in config.handles:
        posts.extend(
            _fetch_author_feed(
                handle, config.max_posts_per_handle, min_age_hours, logger
            )
        )
    logger.info(
        "Reference posts collected: %d across %d handles",
        len(posts),
        len(config.handles),
    )
    return posts
