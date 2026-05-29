from __future__ import annotations

import time
from dataclasses import dataclass
from logging import Logger

import requests

# Public, unauthenticated AppView. Read-only engagement counts do not require a
# session, so the engagement collector needs no Bluesky secrets in CI.
_PUBLIC_GETPOSTS_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts"

# getPosts accepts at most 25 URIs per request.
_MAX_URIS_PER_CALL = 25


@dataclass(slots=True)
class PostMetrics:
    uri: str
    like_count: int
    repost_count: int
    reply_count: int
    quote_count: int

    @property
    def total_engagement(self) -> int:
        """Weighted engagement: reposts/quotes spread reach more than a like."""
        return (
            self.like_count
            + 2 * self.repost_count
            + 2 * self.quote_count
            + self.reply_count
        )


def _chunk(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _get_with_retry(url: str, params: list[tuple[str, str]], logger: Logger) -> requests.Response | None:
    attempts = 3
    delay_seconds = 2
    for idx in range(attempts):
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            logger.warning("Bluesky metrics request error (attempt %d): %s", idx + 1, exc)
            if idx == attempts - 1:
                return None
            time.sleep(delay_seconds)
            delay_seconds *= 2
            continue
        if resp.status_code >= 500:
            logger.warning("Bluesky metrics %d (attempt %d)", resp.status_code, idx + 1)
            if idx == attempts - 1:
                return resp
            time.sleep(delay_seconds)
            delay_seconds *= 2
            continue
        return resp
    return None


def fetch_post_metrics(uris: list[str], logger: Logger) -> dict[str, PostMetrics]:
    """Fetch engagement counts for AT-URIs. Returns a uri -> PostMetrics map.

    Missing/deleted posts are silently omitted from the result so callers can
    distinguish "no data yet" from "zero engagement".
    """
    valid = [u for u in uris if isinstance(u, str) and u.startswith("at://")]
    metrics: dict[str, PostMetrics] = {}
    for batch in _chunk(valid, _MAX_URIS_PER_CALL):
        params = [("uris", u) for u in batch]
        resp = _get_with_retry(_PUBLIC_GETPOSTS_URL, params, logger)
        if resp is None or resp.status_code >= 400:
            status = resp.status_code if resp is not None else "no-response"
            logger.warning("Skipping metrics batch of %d (status: %s)", len(batch), status)
            continue
        try:
            posts = resp.json().get("posts", [])
        except ValueError:
            logger.warning("Bluesky metrics returned non-JSON for batch of %d", len(batch))
            continue
        for post in posts:
            uri = post.get("uri")
            if not uri:
                continue
            metrics[uri] = PostMetrics(
                uri=uri,
                like_count=int(post.get("likeCount", 0) or 0),
                repost_count=int(post.get("repostCount", 0) or 0),
                reply_count=int(post.get("replyCount", 0) or 0),
                quote_count=int(post.get("quoteCount", 0) or 0),
            )
    return metrics
