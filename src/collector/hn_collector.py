from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from logging import Logger

import requests

from src.models import FeedItem

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_USER_AGENT = "BoardwireAI/0.1 (+https://github.com/)"
SOURCE_NAME = "HackerNews"
SOURCE_TIER = 3

# Short tokens are matched as whole words; longer/multi-word tokens as substrings.
_AI_WORD_TOKENS = (
    "ai", "llm", "llms", "gpt", "rag", "mcp", "agent", "agents",
    "claude", "gemini", "mistral", "anthropic", "openai", "deepmind",
    "ollama", "vllm", "langchain", "llamaindex", "fastembed", "groq",
    "llama", "mixtral", "qwen", "deepseek", "copilot", "codex", "whisper",
    "midjourney", "huggingface", "pytorch", "tensorflow",
)
_AI_SUBSTRING_TOKENS = (
    "transformer", "embedding", "fine-tun", "inference",
    "hugging face", "machine learning", "neural network", "diffusion model",
    "open-source model", "open-weight", "model weights", "phi-",
)

_WORD_BOUNDARY_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _AI_WORD_TOKENS) + r")\b",
    re.IGNORECASE,
)


def _matches_ai(title: str, url: str) -> bool:
    haystack = f"{title} {url}"
    if _WORD_BOUNDARY_RE.search(haystack):
        return True
    low = haystack.lower()
    return any(tok in low for tok in _AI_SUBSTRING_TOKENS)


def _engagement(points: int, comments: int) -> float:
    return float(points) + 0.5 * float(comments)


def fetch_hackernews(
    logger: Logger | None = None,
    hours_back: int = 48,
    min_points: int = 30,
    hits_per_page: int = 100,
) -> tuple[list[FeedItem], dict[str, object]]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    cutoff_unix = int(cutoff.timestamp())

    params = {
        "tags": "story",
        "numericFilters": f"points>{min_points},created_at_i>{cutoff_unix}",
        "hitsPerPage": hits_per_page,
    }

    try:
        response = requests.get(
            ALGOLIA_URL,
            params=params,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        if logger:
            logger.warning("HN fetch failed: %s", exc)
        return [], {"count": 0, "error": str(exc)}

    payload = response.json()
    hits = payload.get("hits", []) or []

    items: list[FeedItem] = []
    seen: set[str] = set()
    matched_count = 0

    for hit in hits:
        title = (hit.get("title") or hit.get("story_title") or "").strip()
        url = (hit.get("url") or "").strip()
        object_id = str(hit.get("objectID") or "").strip()
        if not title or not object_id:
            continue
        link = url or f"https://news.ycombinator.com/item?id={object_id}"
        if link in seen:
            continue
        seen.add(link)

        if not _matches_ai(title, url):
            continue
        matched_count += 1

        points = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        author = str(hit.get("author") or "")
        created_at_ts = hit.get("created_at_i")
        if created_at_ts:
            published_at = datetime.fromtimestamp(int(created_at_ts), tz=timezone.utc)
        else:
            published_at = datetime.now(tz=timezone.utc)

        summary_parts = [f"{points} points, {comments} comments on Hacker News"]
        if author:
            summary_parts.append(f"submitted by {author}")
        if url:
            summary_parts.append(f"original: {url}")
        summary = " — ".join(summary_parts)

        items.append(
            FeedItem(
                source=SOURCE_NAME,
                title=title,
                link=link,
                summary=summary,
                published_at=published_at,
                source_tier=SOURCE_TIER,
                engagement_score=_engagement(points, comments),
            )
        )

    items.sort(key=lambda i: i.engagement_score, reverse=True)

    if logger:
        logger.info(
            "HN: %d total hits, %d AI-relevant items kept",
            len(hits),
            len(items),
        )

    return items, {
        "count": len(items),
        "total_hits": len(hits),
        "ai_matched": matched_count,
        "error": None,
        "top_titles": [i.title for i in items[:3]],
    }
