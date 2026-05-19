from __future__ import annotations

from datetime import datetime, timezone
from logging import Logger

import requests

from src.models import FeedItem

DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_USER_AGENT = "BoardwireAI/0.1 (boardwire-ai signal feed)"
SOURCE_TIER = 3

DEFAULT_SUBREDDITS: tuple[tuple[str, str], ...] = (
    ("LocalLLaMA", "day"),
    ("MachineLearning", "day"),
    ("singularity", "day"),
)


def _engagement(score: int, comments: int) -> float:
    return float(score) + 0.5 * float(comments)


def _fetch_subreddit(
    subreddit: str,
    period: str,
    limit: int,
    logger: Logger | None,
) -> tuple[list[FeedItem], dict[str, object]]:
    url = f"https://www.reddit.com/r/{subreddit}/top.json"
    params = {"t": period, "limit": limit}

    try:
        response = requests.get(
            url,
            params=params,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        if logger:
            logger.warning("Reddit r/%s fetch failed: %s", subreddit, exc)
        return [], {"count": 0, "error": str(exc)}

    payload = response.json()
    children = payload.get("data", {}).get("children", []) or []
    source_name = f"Reddit r/{subreddit}"

    items: list[FeedItem] = []
    seen: set[str] = set()

    for child in children:
        data = child.get("data", {}) or {}
        if data.get("stickied") or data.get("over_18"):
            continue

        title = str(data.get("title") or "").strip()
        if not title:
            continue

        permalink = str(data.get("permalink") or "").strip()
        external_url = str(data.get("url") or "").strip()
        is_self = bool(data.get("is_self"))
        link = (
            f"https://www.reddit.com{permalink}"
            if is_self or not external_url
            else external_url
        )
        if not link or link in seen:
            continue
        seen.add(link)

        score = int(data.get("score") or 0)
        num_comments = int(data.get("num_comments") or 0)
        author = str(data.get("author") or "")
        selftext = str(data.get("selftext") or "").strip()
        created_utc = data.get("created_utc")
        if created_utc:
            published_at = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
        else:
            published_at = datetime.now(tz=timezone.utc)

        if selftext:
            body_excerpt = selftext[:400].replace("\n", " ")
            summary = f"r/{subreddit} | {score} upvotes, {num_comments} comments | {body_excerpt}"
        else:
            summary = (
                f"r/{subreddit} discussion: {score} upvotes, {num_comments} comments"
                + (f" — submitted by {author}" if author else "")
            )

        items.append(
            FeedItem(
                source=source_name,
                title=title,
                link=link,
                summary=summary,
                published_at=published_at,
                source_tier=SOURCE_TIER,
                engagement_score=_engagement(score, num_comments),
            )
        )

    items.sort(key=lambda i: i.engagement_score, reverse=True)
    if logger:
        logger.info("Reddit r/%s: %d items", subreddit, len(items))

    return items, {
        "count": len(items),
        "error": None,
        "top_titles": [i.title for i in items[:3]],
    }


def fetch_reddit(
    logger: Logger | None = None,
    subreddits: tuple[tuple[str, str], ...] | None = None,
    limit_per_sub: int = 25,
) -> tuple[list[FeedItem], dict[str, dict[str, object]]]:
    selected = subreddits or DEFAULT_SUBREDDITS
    all_items: list[FeedItem] = []
    report: dict[str, dict[str, object]] = {}
    seen_links: set[str] = set()

    for subreddit, period in selected:
        items, sub_report = _fetch_subreddit(subreddit, period, limit_per_sub, logger)
        report[f"Reddit r/{subreddit}"] = sub_report
        for item in items:
            if item.link in seen_links:
                continue
            seen_links.add(item.link)
            all_items.append(item)

    all_items.sort(key=lambda i: i.engagement_score, reverse=True)
    return all_items, report
