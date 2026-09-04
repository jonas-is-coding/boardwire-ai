"""Account discovery for the follow drip: four weighted graph channels.

Channels (weights in ``config/growth.json``):

1. ``seed_follows``   — who the seed accounts follow (curated by the seeds)
2. ``seed_followers`` — who follows the seed accounts
3. ``lists``          — members of starter packs / curated lists (``list_uris``)
4. ``search``         — ``searchActors`` over the niche keywords

A candidate's score is the sum of the channel weights that surfaced it, so an
account three seeds follow outranks one that only matched a keyword. That is
*graph relevance* — how strongly the niche already points at an account — and
deliberately not follow-back likelihood: optimising for follow-backs is
follow/unfollow thinking with an extra step.

Graph pages and search results come back as bare profile views without the
authenticated ``viewer`` state, so every surviving candidate is **re-hydrated
through ``getProfiles`` before filtering**. That hydration is what makes the
drip idempotent: ``viewer.following`` is authoritative, the local ledger is
only a cache.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import Logger

from dateutil import parser as date_parser

from src.growth.client import GrowthClient, GrowthClientError
from src.growth.settings import GrowthConfig, normalize_handle

CHANNEL_SEED_FOLLOWS = "seed_follows"
CHANNEL_SEED_FOLLOWERS = "seed_followers"
CHANNEL_LISTS = "lists"
CHANNEL_SEARCH = "search"
CHANNEL_BIO = "bio"
CHANNEL_SEED = "seed"  # seed mode: the configured seeds themselves
CHANNEL_RECIPROCITY = "reciprocity"  # generous follower: follow-back propensity, not graph relevance

_STARTER_PACK_WEB_RE = re.compile(r"^https://bsky\.app/starter-pack/([^/?#]+)/([^/?#]+)")
_LIST_WEB_RE = re.compile(r"^https://bsky\.app/profile/([^/?#]+)/lists/([^/?#]+)")
_STARTER_PACK_COLLECTION = "app.bsky.graph.starterpack"
_LIST_COLLECTION = "app.bsky.graph.list"

# Moderation labels (self-labels or labeler-applied) that disqualify an account.
_BLOCKED_LABELS = {"spam", "impersonation", "scam", "!hide", "!warn", "porn", "sexual", "nudity"}
_MAX_BIO_HITS = 3


@dataclass(slots=True)
class Candidate:
    did: str
    handle: str
    display_name: str = ""
    description: str = ""
    followers_count: int = 0
    follows_count: int = 0
    posts_count: int = 0
    score: float = 0.0
    channels: dict[str, float] = field(default_factory=dict)
    via: list[str] = field(default_factory=list)
    viewer_following: bool = False
    viewer_blocked: bool = False
    muted: bool = False
    labels: list[str] = field(default_factory=list)
    is_labeler: bool = False
    last_post_at: str | None = None

    def add(self, channel: str, weight: float, via: str | None = None) -> None:
        self.channels[channel] = self.channels.get(channel, 0.0) + weight
        self.score += weight
        if via and via not in self.via:
            self.via.append(via)

    @property
    def top_channel(self) -> str:
        if not self.channels:
            return ""
        return max(self.channels.items(), key=lambda kv: kv[1])[0]

    @property
    def follow_ratio(self) -> float:
        return self.follows_count / max(1, self.followers_count)

    @property
    def web_url(self) -> str:
        return f"https://bsky.app/profile/{self.handle}"

    def why(self) -> str:
        parts = [f"{name}={weight:.1f}" for name, weight in sorted(self.channels.items(), key=lambda kv: -kv[1])]
        via = ", ".join(self.via[:3])
        if len(self.via) > 3:
            via += f" +{len(self.via) - 3}"
        return " ".join(parts) + (f" via {via}" if via else "")


def apply_profile(cand: Candidate, profile: dict) -> None:
    """Copy whatever a profile view carries onto the candidate. A detailed view
    (getProfiles) overwrites the bare view from a graph page."""
    handle = normalize_handle(profile.get("handle"))
    if handle:
        cand.handle = handle
    cand.display_name = str(profile.get("displayName") or "").strip()
    cand.description = str(profile.get("description") or "").strip()
    for attr, key in (("followers_count", "followersCount"), ("follows_count", "followsCount"), ("posts_count", "postsCount")):
        if key in profile:
            try:
                setattr(cand, attr, int(profile.get(key) or 0))
            except (TypeError, ValueError):
                pass
    viewer = profile.get("viewer") if isinstance(profile.get("viewer"), dict) else {}
    cand.viewer_following = bool(viewer.get("following"))
    cand.viewer_blocked = bool(viewer.get("blocking") or viewer.get("blockedBy") or viewer.get("blockingByList"))
    cand.muted = bool(viewer.get("muted") or viewer.get("mutedByList"))
    labels = profile.get("labels") if isinstance(profile.get("labels"), list) else []
    cand.labels = [str(label.get("val")) for label in labels if isinstance(label, dict) and label.get("val")]
    associated = profile.get("associated") if isinstance(profile.get("associated"), dict) else {}
    cand.is_labeler = bool(associated.get("labeler"))


def candidate_from_profile(profile: dict) -> Candidate | None:
    did = str(profile.get("did") or "").strip()
    handle = normalize_handle(profile.get("handle"))
    if not did or not handle:
        return None
    cand = Candidate(did=did, handle=handle)
    apply_profile(cand, profile)
    return cand


def _sort_key(cand: Candidate) -> tuple[float, int, str]:
    return (-cand.score, -cand.followers_count, cand.handle)


def days_since(timestamp: str | None, now: datetime) -> float | None:
    if not timestamp:
        return None
    try:
        dt = date_parser.parse(timestamp)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt.astimezone(timezone.utc)).total_seconds() / 86400.0


def _keyword_hits(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for kw in keywords if kw.lower() in lowered)


def _blocked_keyword(cand: Candidate, blocked: list[str]) -> str | None:
    haystack = " ".join([cand.handle, cand.display_name, cand.description]).lower()
    for keyword in blocked:
        kw = keyword.lower().strip()
        if not kw:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", haystack):
            return kw
    return None


# ---------------------------------------------------------------------------
# lists / starter packs
# ---------------------------------------------------------------------------


def _actor_did(client: GrowthClient, actor: str) -> str:
    if actor.startswith("did:"):
        return actor
    did = str(client.get_profile(actor).get("did") or "")
    if not did:
        raise GrowthClientError(f"could not resolve DID for {actor}")
    return did


def resolve_list_uri(client: GrowthClient, reference: str, logger: Logger) -> str | None:
    """Turn a ``list_uris`` entry into an ``at://.../app.bsky.graph.list/...`` URI.

    Accepts a list URI (returned as-is), a starter-pack URI (its list is looked
    up), or the bsky.app URL of a starter pack or list. Returns None, with a
    warning, when the reference cannot be resolved.
    """
    ref = str(reference or "").strip()
    try:
        if ref.startswith("at://"):
            if f"/{_LIST_COLLECTION}/" in ref:
                return ref
            if f"/{_STARTER_PACK_COLLECTION}/" in ref:
                list_uri = str((client.get_starter_pack(ref).get("list") or {}).get("uri") or "")
                return list_uri or None
            logger.warning("Unsupported at:// reference in list_uris: %s", ref)
            return None
        match = _STARTER_PACK_WEB_RE.match(ref)
        if match:
            did = _actor_did(client, match.group(1))
            pack_uri = f"at://{did}/{_STARTER_PACK_COLLECTION}/{match.group(2)}"
            list_uri = str((client.get_starter_pack(pack_uri).get("list") or {}).get("uri") or "")
            return list_uri or None
        match = _LIST_WEB_RE.match(ref)
        if match:
            did = _actor_did(client, match.group(1))
            return f"at://{did}/{_LIST_COLLECTION}/{match.group(2)}"
    except GrowthClientError as exc:
        logger.warning("List reference %s could not be resolved: %s", ref, exc)
        return None
    logger.warning("Unrecognised list reference: %s", ref)
    return None


def verify_lists(client: GrowthClient, config: GrowthConfig, logger: Logger) -> list[dict]:
    """Resolve every ``list_uris`` entry and log its name and size."""
    rows: list[dict] = []
    for ref in config.list_uris:
        list_uri = resolve_list_uri(client, ref, logger)
        if not list_uri:
            rows.append({"reference": ref, "ok": False, "reason": "unresolved"})
            logger.warning("List %-60s UNRESOLVED", ref)
            continue
        try:
            info = client.get_list_info(list_uri)
        except GrowthClientError as exc:
            rows.append({"reference": ref, "uri": list_uri, "ok": False, "reason": str(exc)})
            logger.warning("List %-60s UNAVAILABLE (%s)", ref, exc)
            continue
        count = int(info.get("listItemCount") or 0)
        name = str(info.get("name") or "")
        rows.append({"reference": ref, "uri": list_uri, "ok": True, "name": name, "items": count})
        logger.info("List %-60s -> %-24s %4d members  %s", ref, name[:24], count, list_uri)
    unresolved = sum(1 for row in rows if not row["ok"])
    logger.info("Lists: %d resolved, %d unresolved", len(rows) - unresolved, unresolved)
    return rows


# ---------------------------------------------------------------------------
# seeds
# ---------------------------------------------------------------------------


def resolve_profiles(client: GrowthClient, handles: list[str], logger: Logger) -> dict[str, dict]:
    """handle -> detailed profile. Tries one batched getProfiles, then falls
    back to per-handle lookups so a single dead handle cannot sink the run."""
    wanted = [normalize_handle(h) for h in handles if normalize_handle(h)]
    resolved: dict[str, dict] = {}
    if not wanted:
        return resolved
    try:
        for profile in client.get_profiles(wanted):
            handle = normalize_handle(profile.get("handle"))
            if handle:
                resolved[handle] = profile
    except GrowthClientError as exc:
        logger.warning("Batch profile lookup failed (%s); resolving handles one by one", exc)
    for handle in wanted:
        if handle in resolved:
            continue
        try:
            resolved[handle] = client.get_profile(handle)
        except GrowthClientError as exc:
            logger.warning("Handle %s could not be resolved: %s", handle, exc)
    return resolved


def _latest_post(client: GrowthClient, cand: Candidate, logger: Logger) -> str | None:
    try:
        return client.latest_post_at(cand.did)
    except GrowthClientError as exc:
        logger.warning("Author feed unavailable for @%s: %s", cand.handle, exc)
        return None


def verify_seeds(client: GrowthClient, config: GrowthConfig, logger: Logger, now: datetime | None = None) -> list[dict]:
    """Resolve every configured seed and log a table with its graph stats.
    Returns one row per seed; ``ok`` is False for unresolved handles."""
    now = now or datetime.now(timezone.utc)
    profiles = resolve_profiles(client, config.seed_handles, logger)
    rows: list[dict] = []
    for handle in config.seed_handles:
        profile = profiles.get(handle)
        cand = candidate_from_profile(profile) if profile else None
        if cand is None:
            rows.append({"handle": handle, "ok": False, "reason": "unresolved"})
            logger.warning("Seed %-32s UNRESOLVED", handle)
            continue
        cand.last_post_at = _latest_post(client, cand, logger)
        age = days_since(cand.last_post_at, now)
        reason: str | None = None
        if cand.posts_count == 0:
            reason = "no posts (placeholder or wiped account)"
        elif age is not None and age > config.seed_max_days_since_post:
            reason = f"dormant ({age:.0f}d since last post, max {config.seed_max_days_since_post})"
        rows.append(
            {
                "handle": cand.handle,
                "did": cand.did,
                "ok": reason is None,
                "reason": reason,
                "followers": cand.followers_count,
                "follows": cand.follows_count,
                "posts": cand.posts_count,
                "last_post_days": round(age, 1) if age is not None else None,
                "following": cand.viewer_following,
            }
        )
        logger.log(
            logging.WARNING if reason else logging.INFO,
            "Seed %-32s followers=%-7d follows=%-6d posts=%-6d last_post=%-9s following=%s%s",
            cand.handle,
            cand.followers_count,
            cand.follows_count,
            cand.posts_count,
            f"{age:.0f}d ago" if age is not None else "unknown",
            "n/a (public read)" if getattr(client, "is_public", False) else ("yes" if cand.viewer_following else "no"),
            f"  FAIL: {reason}" if reason else "",
        )
    unresolved = sum(1 for row in rows if not row["ok"] and row.get("reason") == "unresolved")
    dormant = sum(1 for row in rows if not row["ok"] and row.get("reason") != "unresolved")
    logger.info("Seeds: %d ok, %d unresolved, %d dormant", len(rows) - unresolved - dormant, unresolved, dormant)
    return rows


def seed_candidates(client: GrowthClient, config: GrowthConfig, logger: Logger, *, own_did: str) -> list[Candidate]:
    """Seed mode: the configured seed accounts themselves, in config order.
    Already-followed seeds are kept (the drip skips them) so the summary shows
    the real state."""
    profiles = resolve_profiles(client, config.seed_handles, logger)
    out: list[Candidate] = []
    for handle in config.seed_handles:
        profile = profiles.get(handle)
        cand = candidate_from_profile(profile) if profile else None
        if cand is None or cand.did == own_did:
            continue
        cand.add(CHANNEL_SEED, 1.0, "config seed")
        out.append(cand)
    return out


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def collect_raw_candidates(
    client: GrowthClient,
    config: GrowthConfig,
    logger: Logger,
    *,
    seed_profiles: dict[str, dict],
) -> dict[str, Candidate]:
    """Run the four channels and aggregate weighted scores per DID."""
    pool: dict[str, Candidate] = {}
    weights = config.weights

    def add(profile: dict, channel: str, weight: float, via: str) -> None:
        did = str(profile.get("did") or "").strip()
        cand = pool.get(did)
        if cand is None:
            cand = candidate_from_profile(profile)
            if cand is None:
                return
            pool[cand.did] = cand
        cand.add(channel, weight, via)

    for handle, seed in seed_profiles.items():
        seed_did = str(seed.get("did") or "")
        if not seed_did:
            continue
        try:
            for profile in client.get_follows(seed_did, limit=config.graph_depth_per_seed):
                add(profile, CHANNEL_SEED_FOLLOWS, weights.seed_follows, f"@{handle} follows")
        except GrowthClientError as exc:
            logger.warning("getFollows failed for seed @%s: %s", handle, exc)
        try:
            for profile in client.get_followers(seed_did, limit=config.graph_depth_per_seed):
                add(profile, CHANNEL_SEED_FOLLOWERS, weights.seed_followers, f"follows @{handle}")
        except GrowthClientError as exc:
            logger.warning("getFollowers failed for seed @%s: %s", handle, exc)

    for reference in config.list_uris:
        list_uri = resolve_list_uri(client, reference, logger)
        if not list_uri:
            continue
        label = list_uri.rsplit("/", 1)[-1]
        try:
            for profile in client.get_list_members(list_uri, limit=config.max_list_members):
                add(profile, CHANNEL_LISTS, weights.lists, f"list {label}")
        except GrowthClientError as exc:
            logger.warning("getList failed for %s: %s", list_uri, exc)

    for keyword in config.keywords:
        try:
            for profile in client.search_actors(keyword, limit=config.max_search_results):
                add(profile, CHANNEL_SEARCH, weights.search, f"search '{keyword}'")
        except GrowthClientError as exc:
            logger.warning("searchActors failed for '%s': %s", keyword, exc)

    return pool


def hydrate(client: GrowthClient, candidates: list[Candidate], logger: Logger) -> list[Candidate]:
    """Replace bare profile views with authenticated detailed views. Candidates
    the AppView no longer returns (deleted, deactivated, taken down) drop out."""
    if not candidates:
        return []
    by_did = {cand.did: cand for cand in candidates}
    try:
        profiles = client.get_profiles(list(by_did.keys()))
    except GrowthClientError as exc:
        logger.error("Re-hydration failed, refusing to follow from stale views: %s", exc)
        return []
    hydrated: list[Candidate] = []
    for profile in profiles:
        cand = by_did.get(str(profile.get("did") or ""))
        if cand is None:
            continue
        apply_profile(cand, profile)
        hydrated.append(cand)
    return hydrated


def rejection_reason(
    cand: Candidate,
    config: GrowthConfig,
    *,
    own_did: str,
    seed_dids: set[str] | frozenset[str] = frozenset(),
    exclude_dids: set[str] | frozenset[str] = frozenset(),
) -> str | None:
    """Why a hydrated candidate must not be followed, or None if it qualifies."""
    if cand.did == own_did:
        return "own account"
    if cand.did in seed_dids:
        return "seed (use --growth-mode seed)"
    if cand.did in exclude_dids:
        return "in ledger"
    if cand.viewer_following:
        return "already following"
    if cand.viewer_blocked:
        return "blocked"
    if cand.muted:
        return "muted"
    if cand.is_labeler:
        return "labeler service"
    for label in cand.labels:
        if label in _BLOCKED_LABELS:
            return f"label {label}"
    filters = config.filters
    if filters.require_description and not cand.description:
        return "empty bio"
    if cand.followers_count < filters.min_followers:
        return "too few followers"
    if cand.followers_count > filters.max_followers:
        return "too many followers"
    if cand.posts_count < filters.min_posts:
        return "too few posts"
    if cand.follow_ratio > filters.max_follow_ratio:
        return "follow ratio"
    hit = _blocked_keyword(cand, filters.blocked_keywords)
    if hit:
        return f"blocked keyword '{hit}'"
    return None


def discover_candidates(
    client: GrowthClient,
    config: GrowthConfig,
    logger: Logger,
    *,
    own_did: str,
    exclude_dids: set[str] | frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> list[Candidate]:
    """Full discovery: channels -> prune -> hydrate -> filter -> freshness.

    Returns fresh, qualified candidates sorted by score (best first). The list
    is bounded to ``config.freshness_pool`` so a run never spends more than
    ~2x that many author-feed calls on the last-post check.
    """
    now = now or datetime.now(timezone.utc)
    stats: Counter[str] = Counter()

    seed_profiles = resolve_profiles(client, config.seed_handles, logger)
    if config.seed_handles and not seed_profiles:
        logger.warning("None of the %d seed handles resolved", len(config.seed_handles))
    seed_dids = {str(p.get("did")) for p in seed_profiles.values() if p.get("did")}

    pool = collect_raw_candidates(client, config, logger, seed_profiles=seed_profiles)
    stats["raw"] = len(pool)

    known = set(exclude_dids) | seed_dids | {own_did}
    raw = [cand for cand in pool.values() if cand.did not in known]
    stats["pruned_known"] = len(pool) - len(raw)
    raw.sort(key=_sort_key)
    to_hydrate = raw[: config.max_hydrate]
    stats["hydrated"] = len(to_hydrate)

    kept: list[Candidate] = []
    for cand in hydrate(client, to_hydrate, logger):
        hits = _keyword_hits(f"{cand.display_name} {cand.description}", config.keywords)
        if hits:
            cand.add(CHANNEL_BIO, min(_MAX_BIO_HITS, hits) * config.weights.bio_keyword)
        if cand.follow_ratio >= config.reciprocity_min_follow_ratio:
            cand.add(CHANNEL_RECIPROCITY, config.weights.reciprocity)
        reason = rejection_reason(cand, config, own_did=own_did, seed_dids=seed_dids, exclude_dids=exclude_dids)
        if reason:
            stats[f"rejected: {reason}"] += 1
            continue
        kept.append(cand)
    kept.sort(key=_sort_key)

    fresh: list[Candidate] = []
    checks = 0
    max_checks = config.freshness_pool * 2
    for cand in kept:
        if len(fresh) >= config.freshness_pool or checks >= max_checks:
            break
        checks += 1
        cand.last_post_at = _latest_post(client, cand, logger)
        age = days_since(cand.last_post_at, now)
        if age is None or age > config.filters.max_days_since_post:
            stats["rejected: dormant"] += 1
            continue
        fresh.append(cand)
    stats["fresh"] = len(fresh)

    logger.info(
        "Discovery: raw=%d pruned=%d hydrated=%d qualified=%d fresh=%d",
        stats["raw"],
        stats["pruned_known"],
        stats["hydrated"],
        len(kept),
        len(fresh),
    )
    for key, count in sorted(stats.items()):
        if key.startswith("rejected"):
            logger.info("  %-40s %d", key, count)
    return fresh
