"""Follower / following / post counts of the Boardwire account over time.

The engagement collector measures posts but the repo never recorded the
account itself, so "no new followers for days" was a feeling, not a number.
One public ``getProfile`` call per collection run (no credentials: the DID
comes from the newest published post's ``at://`` URI) appends a snapshot to
``data/account_snapshots.json``; the engagement report shows the current
count and the 1-day / 7-day deltas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging import Logger
from pathlib import Path
from typing import Any

import requests
from dateutil import parser as date_parser

from src.storage.json_store import JsonStore

_PUBLIC_GETPROFILE_URL = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"


@dataclass(slots=True)
class AccountCounts:
    did: str
    handle: str
    followers: int
    follows: int
    posts: int


@dataclass(slots=True)
class AccountTrend:
    observed_at: str
    handle: str
    followers: int
    follows: int
    posts: int
    followers_delta_1d: int | None = None
    followers_delta_7d: int | None = None
    snapshots: int = 0


def account_did_from_posts(published: list[dict]) -> str | None:
    """DID of the publishing account, read from the newest ``at://`` post URI."""
    newest: tuple[str, str] | None = None
    for post in published:
        if not isinstance(post, dict):
            continue
        uri = str(post.get("external_id") or post.get("url") or "")
        if not uri.startswith("at://did:"):
            continue
        key = str(post.get("published_at") or "")
        if newest is None or key > newest[0]:
            newest = (key, uri)
    if newest is None:
        return None
    return newest[1][len("at://") :].split("/", 1)[0] or None


def fetch_account_counts(actor: str, logger: Logger) -> AccountCounts | None:
    """Public profile counts for a DID or handle; None on any failure."""
    try:
        resp = requests.get(_PUBLIC_GETPROFILE_URL, params={"actor": actor}, timeout=30)
    except requests.RequestException as exc:
        logger.warning("Account snapshot: getProfile failed: %s", exc)
        return None
    if resp.status_code >= 400:
        logger.warning("Account snapshot: getProfile returned %d", resp.status_code)
        return None
    try:
        body = resp.json()
    except ValueError:
        logger.warning("Account snapshot: getProfile returned non-JSON")
        return None
    if not isinstance(body, dict) or not body.get("did"):
        return None

    def _int(key: str) -> int:
        try:
            return int(body.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return AccountCounts(
        did=str(body.get("did")),
        handle=str(body.get("handle") or ""),
        followers=_int("followersCount"),
        follows=_int("followsCount"),
        posts=_int("postsCount"),
    )


def record_account_snapshot(path: Path, counts: AccountCounts, observed_at: datetime | None = None) -> list[dict]:
    """Append one snapshot to the JSON list at ``path`` and return the list."""
    observed_at = observed_at or datetime.now(timezone.utc)
    snapshots = JsonStore.load(path, default=[])
    if not isinstance(snapshots, list):
        snapshots = []
    snapshots.append(
        {
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "did": counts.did,
            "handle": counts.handle,
            "followers": counts.followers,
            "follows": counts.follows,
            "posts": counts.posts,
        }
    )
    JsonStore.save(path, snapshots)
    return snapshots


def _parse(value: Any) -> datetime | None:
    try:
        dt = date_parser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def account_trend(snapshots: list[dict], now: datetime | None = None) -> AccountTrend | None:
    """Latest counts plus follower deltas against the newest snapshot that is
    at least 1 / 7 days older than the latest one (None until one exists)."""
    now = now or datetime.now(timezone.utc)
    rows = [(dt, s) for s in snapshots if isinstance(s, dict) and (dt := _parse(s.get("observed_at")))]
    if not rows:
        return None
    rows.sort(key=lambda r: r[0])
    latest_dt, latest = rows[-1]

    def _followers(snapshot: dict) -> int:
        try:
            return int(snapshot.get("followers") or 0)
        except (TypeError, ValueError):
            return 0

    def _delta(days: int) -> int | None:
        cutoff = latest_dt - timedelta(days=days)
        older = [s for dt, s in rows if dt <= cutoff]
        if not older:
            return None
        return _followers(latest) - _followers(older[-1])

    return AccountTrend(
        observed_at=str(latest.get("observed_at") or ""),
        handle=str(latest.get("handle") or ""),
        followers=_followers(latest),
        follows=int(latest.get("follows") or 0),
        posts=int(latest.get("posts") or 0),
        followers_delta_1d=_delta(1),
        followers_delta_7d=_delta(7),
        snapshots=len(rows),
    )


def render_account_section(snapshots: list[dict], now: datetime | None = None) -> list[str]:
    """Markdown lines for the engagement report."""
    trend = account_trend(snapshots, now=now)
    lines = ["## Account", ""]
    if trend is None:
        lines.append("- No account snapshots yet (collected daily with `--collect-engagement`).")
        lines.append("")
        return lines

    def _fmt(delta: int | None, label: str) -> str:
        if delta is None:
            return f"{label}: n/a"
        return f"{label}: {delta:+d}"

    handle = f"@{trend.handle}" if trend.handle else "account"
    lines.append(
        f"- {handle}: **{trend.followers}** followers "
        f"({_fmt(trend.followers_delta_1d, '1d')}, {_fmt(trend.followers_delta_7d, '7d')}) · "
        f"following {trend.follows} · posts {trend.posts} · snapshots {trend.snapshots} · as of `{trend.observed_at}`"
    )
    lines.append("")
    return lines
