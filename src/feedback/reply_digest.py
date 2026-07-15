"""Daily reply digest — human-in-the-loop, NO auto-posting.

Replies are the strongest ranking/visibility signal on Bluesky, but automated
replies would be spam. This module therefore only *suggests*: it queries the
public Bluesky search API for recent, high-engagement posts in Boardwire's
niche, drafts one substantive reply suggestion per post via the existing LLM
chain, and sends the digest to Slack.

HARD RULE: this tool must never post replies itself. It performs read-only
GET requests against the public AppView and one Slack webhook POST. A human
reads the digest and posts any reply manually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path

import requests

from src.config import REPLY_DIGEST_CONFIG_PATH
from src.storage.json_store import JsonStore

# Public, unauthenticated AppView search endpoint (same host the engagement
# collector uses). Read-only; requires no Bluesky secrets.
_SEARCH_POSTS_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"


@dataclass(slots=True)
class ReplyDigestConfig:
    keywords: list[str] = field(default_factory=list)
    max_posts: int = 8
    posts_per_keyword: int = 5
    min_engagement: int = 5


@dataclass(slots=True)
class ReplyCandidate:
    uri: str
    author_handle: str
    text: str
    keyword: str
    like_count: int
    reply_count: int
    repost_count: int
    suggestion: str | None = None

    @property
    def engagement(self) -> int:
        return self.like_count + 2 * self.repost_count + self.reply_count

    @property
    def web_url(self) -> str:
        """Best-effort bsky.app URL for a human to open the post."""
        # at://did:plc:xyz/app.bsky.feed.post/rkey -> https://bsky.app/profile/<handle>/post/<rkey>
        rkey = self.uri.rsplit("/", 1)[-1] if "/" in self.uri else self.uri
        return f"https://bsky.app/profile/{self.author_handle}/post/{rkey}"


def load_reply_digest_config(path: Path | None = None) -> ReplyDigestConfig:
    raw = JsonStore.load(path or REPLY_DIGEST_CONFIG_PATH, default={})
    if not isinstance(raw, dict):
        raw = {}
    keywords = [str(k).strip() for k in raw.get("keywords", []) if str(k).strip()]
    if not keywords:
        keywords = ["Claude Code", "MCP", "local LLM", "open weights"]

    def _int(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return ReplyDigestConfig(
        keywords=keywords,
        max_posts=_int("max_posts", 8),
        posts_per_keyword=_int("posts_per_keyword", 5),
        min_engagement=max(0, _int("min_engagement", 5)),
    )


def _search_posts(keyword: str, limit: int, logger: Logger) -> list[dict]:
    """Read-only search against the public AppView. Never authenticates and
    never writes anything to Bluesky."""
    try:
        resp = requests.get(
            _SEARCH_POSTS_URL,
            params={"q": keyword, "sort": "top", "limit": str(limit)},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("Reply digest search failed for '%s': %s", keyword, exc)
        return []
    if resp.status_code >= 400:
        logger.warning("Reply digest search '%s' returned %d", keyword, resp.status_code)
        return []
    try:
        posts = resp.json().get("posts", [])
    except ValueError:
        logger.warning("Reply digest search '%s' returned non-JSON", keyword)
        return []
    return posts if isinstance(posts, list) else []


def collect_reply_candidates(
    config: ReplyDigestConfig,
    logger: Logger,
    own_handle: str = "",
) -> list[ReplyCandidate]:
    """Fetch recent high-engagement niche posts worth replying to."""
    candidates: dict[str, ReplyCandidate] = {}
    own = own_handle.strip().lstrip("@").lower()
    for keyword in config.keywords:
        for post in _search_posts(keyword, config.posts_per_keyword, logger):
            uri = str(post.get("uri", ""))
            author = post.get("author", {}) if isinstance(post.get("author"), dict) else {}
            handle = str(author.get("handle", "")).strip()
            record = post.get("record", {}) if isinstance(post.get("record"), dict) else {}
            text = " ".join(str(record.get("text", "")).split())
            if not uri or not handle or not text or uri in candidates:
                continue
            if own and handle.lower() == own:
                continue
            candidate = ReplyCandidate(
                uri=uri,
                author_handle=handle,
                text=text,
                keyword=keyword,
                like_count=int(post.get("likeCount", 0) or 0),
                reply_count=int(post.get("replyCount", 0) or 0),
                repost_count=int(post.get("repostCount", 0) or 0),
            )
            if candidate.engagement >= config.min_engagement:
                candidates[uri] = candidate

    ranked = sorted(candidates.values(), key=lambda c: c.engagement, reverse=True)
    return ranked[: config.max_posts]


def build_digest_text(candidates: list[ReplyCandidate]) -> str:
    """Render the Slack digest. Suggestions only — a human posts manually."""
    lines = [
        ":speech_balloon: *Boardwire reply digest* — suggestions only, nothing was posted.",
        "Review each suggestion and post manually if it adds value.",
        "",
    ]
    for idx, cand in enumerate(candidates, start=1):
        excerpt = cand.text[:220] + ("…" if len(cand.text) > 220 else "")
        lines.append(
            f"*{idx}. @{cand.author_handle}* — {cand.engagement} engagement "
            f"(likes {cand.like_count}, replies {cand.reply_count}, reposts {cand.repost_count}) "
            f"· keyword: `{cand.keyword}`"
        )
        lines.append(f"> {excerpt}")
        lines.append(cand.web_url)
        if cand.suggestion:
            lines.append(f"_Suggested reply:_ {cand.suggestion}")
        else:
            lines.append("_Suggested reply:_ (no draft available — LLM providers unreachable)")
        lines.append("")
    return "\n".join(lines).strip()


def run_reply_digest(logger: Logger, config: ReplyDigestConfig | None = None) -> int:
    """Collect candidates, draft suggestions, send the digest to Slack.

    Returns the number of candidates in the digest. This function NEVER posts
    to Bluesky — it only reads the public search API and notifies Slack.
    """
    import os

    from src.notifications import persona_voice as voice
    from src.notifications import slack as notify

    config = config or load_reply_digest_config()
    own_handle = os.getenv("BLUESKY_HANDLE", "")
    candidates = collect_reply_candidates(config, logger, own_handle=own_handle)
    if not candidates:
        logger.info("Reply digest: no niche posts found above the engagement threshold")
        return 0

    for cand in candidates:
        cand.suggestion = voice.draft_reply_suggestion(cand.author_handle, cand.text, cand.keyword)

    digest = build_digest_text(candidates)
    notify.reply_digest(digest)
    logger.info("Reply digest sent with %d suggestion(s)", len(candidates))
    return len(candidates)
