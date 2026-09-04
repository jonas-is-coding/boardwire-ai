"""Daily reply digest — human-in-the-loop, NO auto-posting.

Replies are the strongest ranking/visibility signal on Bluesky, but automated
replies would be spam — and LLM replies under strangers' posts get an account
muted by exactly the people whose audience it needs. This module therefore
only *suggests*: it finds fresh posts worth replying to, drafts one substantive
reply suggestion per post via the existing LLM chain, and sends the digest to
Slack. A person reads it and posts 1-3 replies by hand.

HARD RULE: this tool must never post replies itself — no record is ever
created, changed or deleted. It performs read-only GET requests against the
Bluesky AppView and one Slack webhook POST. The only other POST it may make is
``com.atproto.server.createSession``: the public AppView answers ``403`` to
unauthenticated ``searchPosts`` calls from CI (every keyword search in the
scheduled runs failed that way), so when ``BLUESKY_HANDLE`` +
``BLUESKY_APP_PASSWORD`` are present the keyword search runs through the
authenticated PDS instead. Author feeds stay on the public AppView.

Ranking (``select_digest``):

* **Target accounts first.** ``target_handles`` are the accounts whose
  audience Boardwire needs. A fixed share of the digest (``target_quota``,
  default 60 %) is *reserved* for their fresh posts. A score multiplier was
  rejected: a 3x bonus loses against any viral stranger's post, which is
  exactly when the target list should win.
* **Freshness.** Only posts younger than ``max_age_hours`` qualify — a reply
  is worth most in the first hours of a post — and the search is asked for
  ``since`` that cutoff.
* **Crowding.** Threads with more than ``max_reply_count`` replies are
  skipped (a reply there is buried) and no author takes more than
  ``max_per_author`` slots.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from logging import Logger
from pathlib import Path
from typing import Any

import requests
from dateutil import parser as date_parser

from src.config import REPLY_DIGEST_CONFIG_PATH
from src.storage.json_store import JsonStore

# Public, unauthenticated AppView endpoints (same host the engagement collector
# uses). Read-only; require no Bluesky secrets.
_SEARCH_POSTS_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
_AUTHOR_FEED_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
# Authenticated read path: the PDS proxies AppView reads with the session's
# credentials. searchPosts is the one endpoint the public host refuses (403)
# for CI callers, so keyword search goes here whenever a session exists.
_PDS_URL = "https://bsky.social"
_CREATE_SESSION_URL = f"{_PDS_URL}/xrpc/com.atproto.server.createSession"
_AUTH_SEARCH_POSTS_URL = f"{_PDS_URL}/xrpc/app.bsky.feed.searchPosts"

SOURCE_TARGET = "target"
SOURCE_KEYWORD = "keyword"

_DEFAULT_KEYWORDS = ["Claude Code", "MCP", "local LLM", "open weights"]


def _normalize_handle(value: Any) -> str:
    return str(value or "").strip().lstrip("@").lower()


@dataclass(slots=True)
class ReplyDigestConfig:
    keywords: list[str] = field(default_factory=list)
    target_handles: list[str] = field(default_factory=list)
    max_posts: int = 8
    posts_per_keyword: int = 5
    posts_per_target: int = 5
    min_engagement: int = 5
    target_min_engagement: int = 0
    target_quota: float = 0.6
    max_age_hours: float = 36.0
    max_reply_count: int = 40
    max_per_author: int = 2

    @property
    def target_slots(self) -> int:
        """Digest slots reserved for target-account posts."""
        if not self.target_handles or self.target_quota <= 0:
            return 0
        return min(self.max_posts, math.ceil(self.max_posts * self.target_quota))


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
    created_at: str | None = None
    source: str = SOURCE_KEYWORD

    @property
    def engagement(self) -> int:
        return self.like_count + 2 * self.repost_count + self.reply_count

    @property
    def is_target(self) -> bool:
        return self.source == SOURCE_TARGET

    @property
    def web_url(self) -> str:
        """Best-effort bsky.app URL for a human to open the post."""
        # at://did:plc:xyz/app.bsky.feed.post/rkey -> https://bsky.app/profile/<handle>/post/<rkey>
        rkey = self.uri.rsplit("/", 1)[-1] if "/" in self.uri else self.uri
        return f"https://bsky.app/profile/{self.author_handle}/post/{rkey}"

    def age_hours(self, now: datetime | None = None) -> float | None:
        if not self.created_at:
            return None
        try:
            created = date_parser.parse(self.created_at)
        except (ValueError, OverflowError, TypeError):
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        return (now - created.astimezone(timezone.utc)).total_seconds() / 3600.0


def load_reply_digest_config(path: Path | None = None) -> ReplyDigestConfig:
    raw = JsonStore.load(path or REPLY_DIGEST_CONFIG_PATH, default={})
    if not isinstance(raw, dict):
        raw = {}
    keywords = [str(k).strip() for k in raw.get("keywords", []) if str(k).strip()]
    if not keywords:
        keywords = list(_DEFAULT_KEYWORDS)
    targets: list[str] = []
    raw_targets = raw.get("target_handles", [])
    for handle in raw_targets if isinstance(raw_targets, list) else []:
        normalized = _normalize_handle(handle)
        if normalized and normalized not in targets:
            targets.append(normalized)

    def _int(key: str, default: int, minimum: int = 1) -> int:
        try:
            return max(minimum, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return ReplyDigestConfig(
        keywords=keywords,
        target_handles=targets,
        max_posts=_int("max_posts", 8),
        posts_per_keyword=_int("posts_per_keyword", 5),
        posts_per_target=_int("posts_per_target", 5),
        min_engagement=_int("min_engagement", 5, minimum=0),
        target_min_engagement=_int("target_min_engagement", 0, minimum=0),
        target_quota=min(1.0, max(0.0, _float("target_quota", 0.6))),
        max_age_hours=max(1.0, _float("max_age_hours", 36.0)),
        max_reply_count=_int("max_reply_count", 40, minimum=0),
        max_per_author=_int("max_per_author", 2),
    )


# ---------------------------------------------------------------------------
# read-only fetches
# ---------------------------------------------------------------------------


def bluesky_read_session(logger: Logger, handle: str | None = None, app_password: str | None = None) -> str | None:
    """Access token for authenticated *reads*, or None without credentials.

    Uses ``BLUESKY_HANDLE`` / ``BLUESKY_APP_PASSWORD`` unless given explicitly.
    A failed login is logged and degrades to the public AppView — the digest
    must still go out with the target-account channel alone.
    """
    handle = (handle if handle is not None else os.getenv("BLUESKY_HANDLE", "")).strip().lstrip("@")
    app_password = (app_password if app_password is not None else os.getenv("BLUESKY_APP_PASSWORD", "")).strip()
    if not handle or not app_password:
        return None
    try:
        resp = requests.post(_CREATE_SESSION_URL, json={"identifier": handle, "password": app_password}, timeout=30)
    except requests.RequestException as exc:
        logger.warning("Reply digest login failed (%s); keyword search falls back to the public AppView", exc)
        return None
    if resp.status_code >= 400:
        logger.warning("Reply digest login returned %d; keyword search falls back to the public AppView", resp.status_code)
        return None
    try:
        token = str(resp.json().get("accessJwt") or "")
    except ValueError:
        token = ""
    if not token:
        logger.warning("Reply digest login response carried no accessJwt; using the public AppView")
        return None
    return token


def _get_json(url: str, params: dict[str, str], what: str, logger: Logger, token: str | None = None) -> dict:
    """One read-only GET. ``token`` adds the session's Authorization header for
    the authenticated read path; nothing is ever written to Bluesky."""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as exc:
        logger.warning("Reply digest %s failed: %s", what, exc)
        return {}
    if resp.status_code >= 400:
        logger.warning("Reply digest %s returned %d", what, resp.status_code)
        return {}
    try:
        body = resp.json()
    except ValueError:
        logger.warning("Reply digest %s returned non-JSON", what)
        return {}
    return body if isinstance(body, dict) else {}


def _search_posts(
    keyword: str,
    limit: int,
    logger: Logger,
    since: str | None = None,
    token: str | None = None,
) -> list[dict]:
    params = {"q": keyword, "sort": "top", "limit": str(limit)}
    if since:
        params["since"] = since
    url = _AUTH_SEARCH_POSTS_URL if token else _SEARCH_POSTS_URL
    posts = _get_json(url, params, f"search '{keyword}'", logger, token=token).get("posts", [])
    return posts if isinstance(posts, list) else []


def _fetch_target_posts(handle: str, limit: int, logger: Logger, max_pages: int = 3) -> list[dict]:
    """Newest original posts (no reposts, no replies) of a target account.

    The feed's ``limit`` applies before reposts are filtered out, so the feed
    is paged until ``limit`` originals are collected or it is exhausted — a
    target that just reposted a few times must not leave the digest's
    reserved slots empty.
    """
    posts: list[dict] = []
    cursor: str | None = None
    page_size = str(max(10, min(100, limit * 2)))
    for _ in range(max(1, max_pages)):
        params = {"actor": handle, "limit": page_size, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        body = _get_json(_AUTHOR_FEED_URL, params, f"author feed @{handle}", logger)
        feed = body.get("feed") or []
        for item in feed:
            if not isinstance(item, dict) or item.get("reason"):
                continue  # reposts carry a ``reason``
            post = item.get("post")
            if not isinstance(post, dict):
                continue
            record = post.get("record") if isinstance(post.get("record"), dict) else {}
            if record.get("reply") is not None:
                continue
            posts.append(post)
            if len(posts) >= limit:
                return posts
        cursor = body.get("cursor")
        if not cursor or not feed:
            break
    return posts


def _post_to_candidate(post: dict, *, keyword: str, source: str) -> ReplyCandidate | None:
    uri = str(post.get("uri", ""))
    author = post.get("author", {}) if isinstance(post.get("author"), dict) else {}
    handle = str(author.get("handle", "")).strip()
    record = post.get("record", {}) if isinstance(post.get("record"), dict) else {}
    text = " ".join(str(record.get("text", "")).split())
    if not uri or not handle or not text:
        return None
    created = record.get("createdAt") or post.get("indexedAt")
    return ReplyCandidate(
        uri=uri,
        author_handle=handle,
        text=text,
        keyword=keyword,
        like_count=int(post.get("likeCount", 0) or 0),
        reply_count=int(post.get("replyCount", 0) or 0),
        repost_count=int(post.get("repostCount", 0) or 0),
        created_at=str(created) if created else None,
        source=source,
    )


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------


def _is_fresh(cand: ReplyCandidate, max_age_hours: float, now: datetime) -> bool:
    age = cand.age_hours(now)
    return age is None or age <= max_age_hours  # unknown date: keep, the human decides


def _cap_per_author(ranked: list[ReplyCandidate], max_per_author: int) -> list[ReplyCandidate]:
    counts: dict[str, int] = {}
    kept: list[ReplyCandidate] = []
    for cand in ranked:
        key = cand.author_handle.lower()
        if counts.get(key, 0) >= max_per_author:
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(cand)
    return kept


def select_digest(
    target_pool: list[ReplyCandidate],
    keyword_pool: list[ReplyCandidate],
    config: ReplyDigestConfig,
    now: datetime | None = None,
) -> list[ReplyCandidate]:
    """Fill the digest: reserved target slots first (newest post first, then
    engagement), keyword hits by engagement for the rest, and leftover target
    posts if the keyword pool runs short."""
    now = now or datetime.now(timezone.utc)

    def _target_key(cand: ReplyCandidate) -> tuple[float, int]:
        age = cand.age_hours(now)
        return (age if age is not None else float("inf"), -cand.engagement)

    targets = _cap_per_author(sorted(target_pool, key=_target_key), config.max_per_author)
    keywords = _cap_per_author(sorted(keyword_pool, key=lambda c: -c.engagement), config.max_per_author)

    slots = config.target_slots if targets else 0
    picked = targets[:slots]
    picked += keywords[: max(0, config.max_posts - len(picked))]
    for cand in targets[slots:]:
        if len(picked) >= config.max_posts:
            break
        picked.append(cand)
    return picked[: config.max_posts]


def collect_reply_candidates(
    config: ReplyDigestConfig,
    logger: Logger,
    own_handle: str = "",
    now: datetime | None = None,
    token: str | None = None,
) -> list[ReplyCandidate]:
    """Fetch fresh posts worth replying to: target-account posts first, then
    high-engagement keyword hits. Read-only; ``token`` (a read session from
    ``bluesky_read_session``) routes the keyword search through the PDS."""
    now = now or datetime.now(timezone.utc)
    own = _normalize_handle(own_handle)
    targets = [h for h in (_normalize_handle(t) for t in config.target_handles) if h and h != own]
    target_set = set(targets)
    seen: set[str] = set()
    target_pool: list[ReplyCandidate] = []
    keyword_pool: list[ReplyCandidate] = []

    def _admit_target(cand: ReplyCandidate) -> None:
        if not _is_fresh(cand, config.max_age_hours, now):
            return
        if cand.reply_count > config.max_reply_count:
            return
        if cand.engagement < config.target_min_engagement:
            return
        target_pool.append(cand)

    for handle in targets:
        for post in _fetch_target_posts(handle, config.posts_per_target, logger):
            cand = _post_to_candidate(post, keyword=f"@{handle}", source=SOURCE_TARGET)
            if cand is None or cand.uri in seen:
                continue
            seen.add(cand.uri)
            _admit_target(cand)

    since = (now - timedelta(hours=config.max_age_hours)).isoformat().replace("+00:00", "Z")
    for keyword in config.keywords:
        for post in _search_posts(keyword, config.posts_per_keyword, logger, since=since, token=token):
            cand = _post_to_candidate(post, keyword=keyword, source=SOURCE_KEYWORD)
            if cand is None or cand.uri in seen:
                continue
            author = cand.author_handle.lower()
            if own and author == own:
                continue
            seen.add(cand.uri)
            if author in target_set:
                cand.source = SOURCE_TARGET
                _admit_target(cand)
                continue
            if not _is_fresh(cand, config.max_age_hours, now):
                continue
            if cand.reply_count > config.max_reply_count:
                continue
            if cand.engagement >= config.min_engagement:
                keyword_pool.append(cand)

    return select_digest(target_pool, keyword_pool, config, now=now)


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------


def build_digest_text(candidates: list[ReplyCandidate], now: datetime | None = None) -> str:
    """Render the Slack digest. Suggestions only — a human posts manually."""
    now = now or datetime.now(timezone.utc)
    n_target = sum(1 for c in candidates if c.is_target)
    lines = [
        ":speech_balloon: *Boardwire reply digest* — suggestions only, nothing was posted.",
        f"{len(candidates)} fresh post(s): {n_target} from target accounts, {len(candidates) - n_target} from keyword search. "
        "Review each suggestion and post manually if it adds value.",
        "",
    ]
    for idx, cand in enumerate(candidates, start=1):
        excerpt = cand.text[:220] + ("…" if len(cand.text) > 220 else "")
        age = cand.age_hours(now)
        age_text = f"{age:.0f}h ago" if age is not None else "age unknown"
        tag = ":dart: target account" if cand.is_target else f"keyword: `{cand.keyword}`"
        lines.append(
            f"*{idx}. @{cand.author_handle}* — {cand.engagement} engagement "
            f"(likes {cand.like_count}, replies {cand.reply_count}, reposts {cand.repost_count}) "
            f"· {age_text} · {tag}"
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
    to Bluesky — it only reads the public AppView and notifies Slack.
    """
    from src.llm import sarah_generation
    from src.notifications import persona_voice as voice
    from src.notifications import slack as notify

    config = config or load_reply_digest_config()
    own_handle = os.getenv("BLUESKY_HANDLE", "")
    token = bluesky_read_session(logger)
    logger.info(
        "Reply digest keyword search: %s",
        "authenticated (PDS)" if token else "public AppView (set BLUESKY_APP_PASSWORD; the public host refuses search from CI)",
    )
    candidates = collect_reply_candidates(config, logger, own_handle=own_handle, token=token)
    if not candidates:
        logger.info("Reply digest: no fresh niche posts found above the thresholds")
        return 0

    for cand in candidates:
        context = "target account Boardwire follows closely" if cand.is_target else cand.keyword
        # The provider chain allows one call per provider per process; reset
        # before each draft so every suggestion gets the full chain instead of
        # only the first one (the rest used to come back "exhausted").
        sarah_generation.reset_state()
        cand.suggestion = voice.draft_reply_suggestion(cand.author_handle, cand.text, context)

    digest = build_digest_text(candidates)
    notify.reply_digest(digest)
    logger.info(
        "Reply digest sent with %d suggestion(s) (%d target, %d keyword)",
        len(candidates),
        sum(1 for c in candidates if c.is_target),
        sum(1 for c in candidates if not c.is_target),
    )
    return len(candidates)
