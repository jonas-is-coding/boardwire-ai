from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from src.growth.client import GrowthClientError
from src.growth.discover import (
    CHANNEL_BIO,
    CHANNEL_LISTS,
    CHANNEL_RECIPROCITY,
    CHANNEL_SEARCH,
    CHANNEL_SEED,
    CHANNEL_SEED_FOLLOWERS,
    CHANNEL_SEED_FOLLOWS,
    Candidate,
    discover_candidates,
    rejection_reason,
    resolve_list_uri,
    seed_candidates,
    verify_lists,
    verify_seeds,
)
from src.growth.settings import CandidateFilters, GrowthConfig

_LOGGER = logging.getLogger("test")
_NOW = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)
_LIST = "at://did:plc:list/app.bsky.graph.list/pack"


def _iso(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _profile(
    handle: str,
    *,
    followers: int = 500,
    follows: int = 300,
    posts: int = 100,
    description: str = "Building MCP servers and local LLM tooling",
    following: bool = False,
    labels: tuple[str, ...] = (),
    labeler: bool = False,
    blocked: bool = False,
    muted: bool = False,
) -> dict:
    return {
        "handle": handle,
        "displayName": handle.split(".")[0],
        "description": description,
        "followersCount": followers,
        "followsCount": follows,
        "postsCount": posts,
        "viewer": {
            "following": "at://did:plc:me/app.bsky.graph.follow/x" if following else None,
            "blocking": "at://did:plc:me/app.bsky.graph.block/x" if blocked else None,
            "muted": muted,
        },
        "labels": [{"val": v} for v in labels],
        "associated": {"labeler": labeler},
    }


class FakeGraph:
    """In-memory AT graph standing in for GrowthClient. Graph pages and search
    return *bare* profile views (no counts, no viewer) exactly like the real
    AppView; only get_profiles returns the detailed, authenticated view."""

    def __init__(self, profiles: dict[str, dict], **graph) -> None:
        self.profiles = profiles
        self.follows: dict[str, list[str]] = graph.get("follows", {})
        self.followers: dict[str, list[str]] = graph.get("followers", {})
        self.lists: dict[str, list[str]] = graph.get("lists", {})
        self.search: dict[str, list[str]] = graph.get("search", {})
        self.latest: dict[str, str | None] = graph.get("latest", {})
        self.calls: Counter = Counter()
        self.did = "did:plc:me"

    def _resolve(self, actor: str) -> str:
        if actor.startswith("did:"):
            return actor
        for did, profile in self.profiles.items():
            if profile["handle"] == actor:
                return did
        return actor

    def _bare(self, did: str) -> dict:
        return {"did": did, "handle": self.profiles[did]["handle"]}

    def get_profiles(self, actors: list[str]) -> list[dict]:
        self.calls["get_profiles"] += 1
        out = []
        for actor in actors:
            did = self._resolve(actor)
            if did in self.profiles:
                out.append(dict(self.profiles[did], did=did))
        return out

    def get_profile(self, actor: str) -> dict:
        self.calls["get_profile"] += 1
        did = self._resolve(actor)
        if did not in self.profiles:
            raise GrowthClientError("Profile not found", status=400, error="InvalidRequest")
        return dict(self.profiles[did], did=did)

    def get_follows(self, actor: str, limit: int = 100) -> list[dict]:
        return [self._bare(d) for d in self.follows.get(actor, [])][:limit]

    def get_followers(self, actor: str, limit: int = 100) -> list[dict]:
        return [self._bare(d) for d in self.followers.get(actor, [])][:limit]

    def get_list_members(self, list_uri: str, limit: int = 100) -> list[dict]:
        return [self._bare(d) for d in self.lists.get(list_uri, [])][:limit]

    def search_actors(self, query: str, limit: int = 50) -> list[dict]:
        return [self._bare(d) for d in self.search.get(query, [])][:limit]

    def latest_post_at(self, actor: str) -> str | None:
        self.calls["latest_post_at"] += 1
        return self.latest.get(actor)

    def get_starter_pack(self, uri: str) -> dict:
        self.calls["get_starter_pack"] += 1
        if uri == "at://did:plc:list/app.bsky.graph.starterpack/pack":
            return {"uri": uri, "list": {"uri": _LIST, "name": "AI builders", "listItemCount": 42}}
        raise GrowthClientError("Starter pack not found", status=400, error="InvalidRequest")

    def get_list_info(self, list_uri: str) -> dict:
        if list_uri == _LIST:
            return {"uri": _LIST, "name": "AI builders", "listItemCount": 42}
        raise GrowthClientError("List not found", status=400, error="InvalidRequest")


def _config(**overrides) -> GrowthConfig:
    base = dict(
        seed_handles=["seed1.test", "seed2.test"],
        list_uris=[_LIST],
        keywords=["MCP"],
        follows_per_run=2,
        freshness_pool_factor=2,
    )
    base.update(overrides)
    return GrowthConfig(**base)


def _graph() -> FakeGraph:
    profiles = {
        "did:plc:me": _profile("boardwire.test"),                                     # own account
        "did:plc:seed1": _profile("seed1.test", followers=5000),
        "did:plc:seed2": _profile("seed2.test", followers=8000),
        "did:plc:a": _profile("a.test", description="Ships agents in production"),   # followed by both seeds
        "did:plc:b": _profile("b.test", description="Runs an MCP meetup"),           # seed1 follows + list
        "did:plc:c": _profile("c.test", description="MCP and local LLM enthusiast"),  # search only
        "did:plc:d": _profile("d.test", following=True),                              # already followed
    }
    return FakeGraph(
        profiles,
        follows={"did:plc:seed1": ["did:plc:a", "did:plc:b", "did:plc:d"], "did:plc:seed2": ["did:plc:a", "did:plc:seed1"]},
        followers={"did:plc:seed1": ["did:plc:me"]},
        lists={_LIST: ["did:plc:b"]},
        search={"MCP": ["did:plc:c", "did:plc:d"]},
        latest={did: _iso(2) for did in profiles},
    )


def test_scores_sum_channel_weights_and_rank_multi_seed_first() -> None:
    graph = _graph()
    found = discover_candidates(graph, _config(), _LOGGER, own_did="did:plc:me", now=_NOW)

    assert [c.did for c in found] == ["did:plc:a", "did:plc:b", "did:plc:c"]
    a, b, c = found
    assert a.channels == {CHANNEL_SEED_FOLLOWS: 2.0}
    assert a.score == 2.0
    assert set(b.channels) == {CHANNEL_SEED_FOLLOWS, CHANNEL_LISTS, CHANNEL_BIO}
    assert b.score == 1.0 + 0.8 + 0.2
    # search-only account: search weight + two bio keyword hits capped by weight
    assert c.channels[CHANNEL_SEARCH] == 0.4
    assert c.channels[CHANNEL_BIO] == 0.2
    assert "@seed1.test follows" in a.via and "@seed2.test follows" in a.via
    assert a.top_channel == CHANNEL_SEED_FOLLOWS


def test_reciprocity_bonus_rewards_generous_followers_only() -> None:
    """The reciprocity channel — the one signal that measures follow-back
    propensity rather than graph relevance — only fires for accounts whose
    follows/followers ratio clears reciprocity_min_follow_ratio."""
    graph = _graph()
    # b.test: bump into "generous follower" territory (ratio 0.9 >= 0.8 default).
    graph.profiles["did:plc:b"]["followersCount"] = 400
    graph.profiles["did:plc:b"]["followsCount"] = 360
    found = discover_candidates(graph, _config(), _LOGGER, own_did="did:plc:me", now=_NOW)
    by_did = {c.did: c for c in found}

    b = by_did["did:plc:b"]
    assert CHANNEL_RECIPROCITY in b.channels
    assert b.channels[CHANNEL_RECIPROCITY] == 0.5
    assert b.score == 1.0 + 0.8 + 0.2 + 0.5

    # a.test keeps the default 300/500 = 0.6 ratio, below the 0.8 threshold.
    a = by_did["did:plc:a"]
    assert CHANNEL_RECIPROCITY not in a.channels
    assert a.score == 2.0


def test_known_accounts_are_pruned_before_hydration() -> None:
    graph = _graph()
    found = discover_candidates(graph, _config(), _LOGGER, own_did="did:plc:me", exclude_dids={"did:plc:c"}, now=_NOW)
    dids = {c.did for c in found}
    assert "did:plc:me" not in dids          # own account (surfaced as a seed follower)
    assert "did:plc:seed1" not in dids       # seeds are followed via seed mode
    assert "did:plc:c" not in dids           # in ledger
    assert "did:plc:d" not in dids           # viewer.following after hydration


def test_hydration_is_authoritative_for_viewer_state() -> None:
    """Graph pages carry no viewer state; only the getProfiles hydration can
    reveal that we already follow an account."""
    graph = _graph()
    found = discover_candidates(graph, _config(), _LOGGER, own_did="did:plc:me", now=_NOW)
    assert graph.calls["get_profiles"] >= 2  # seeds + hydration batch
    assert all(not c.viewer_following for c in found)
    assert all(c.followers_count == 500 for c in found)  # counts only exist on the hydrated view


def test_hydration_failure_yields_no_candidates() -> None:
    graph = _graph()
    original = graph.get_profiles
    state = {"n": 0}

    def flaky(actors):
        state["n"] += 1
        if state["n"] > 1:
            raise GrowthClientError("boom", status=500)
        return original(actors)

    graph.get_profiles = flaky  # type: ignore[assignment]
    assert discover_candidates(graph, _config(), _LOGGER, own_did="did:plc:me", now=_NOW) == []


def test_freshness_drops_dormant_and_bounds_feed_calls() -> None:
    graph = _graph()
    graph.latest["did:plc:a"] = _iso(90)   # dormant
    graph.latest["did:plc:b"] = None       # never posted / feed unavailable
    graph.latest["did:plc:c"] = _iso(1)
    config = _config(follows_per_run=1, freshness_pool_factor=2)

    found = discover_candidates(graph, config, _LOGGER, own_did="did:plc:me", now=_NOW)
    assert [c.did for c in found] == ["did:plc:c"]
    assert found[0].last_post_at == _iso(1)
    assert graph.calls["latest_post_at"] == 3
    assert graph.calls["latest_post_at"] <= config.freshness_pool * 2

    # The last-post check is bounded to 2x the pool: with a pool of one, the
    # two dormant accounts ahead of c exhaust the budget and c is never reached.
    tight = _config(follows_per_run=1, freshness_pool_factor=1)
    graph.calls.clear()
    assert discover_candidates(graph, tight, _LOGGER, own_did="did:plc:me", now=_NOW) == []
    assert graph.calls["latest_post_at"] == 2


def test_rejection_reasons_cover_every_filter() -> None:
    config = GrowthConfig(filters=CandidateFilters(min_followers=30, max_followers=1000, min_posts=10, max_follow_ratio=4.0))

    def cand(**kw) -> Candidate:
        base = dict(did="did:plc:x", handle="x.test", description="builder", followers_count=500, follows_count=100, posts_count=50)
        base.update(kw)
        return Candidate(**base)

    ok = cand()
    assert rejection_reason(ok, config, own_did="did:plc:me") is None
    assert rejection_reason(cand(did="did:plc:me"), config, own_did="did:plc:me") == "own account"
    assert rejection_reason(ok, config, own_did="did:plc:me", seed_dids={"did:plc:x"}).startswith("seed")
    assert rejection_reason(ok, config, own_did="did:plc:me", exclude_dids={"did:plc:x"}) == "in ledger"
    assert rejection_reason(cand(viewer_following=True), config, own_did="did:plc:me") == "already following"
    assert rejection_reason(cand(viewer_blocked=True), config, own_did="did:plc:me") == "blocked"
    assert rejection_reason(cand(muted=True), config, own_did="did:plc:me") == "muted"
    assert rejection_reason(cand(is_labeler=True), config, own_did="did:plc:me") == "labeler service"
    assert rejection_reason(cand(labels=["spam"]), config, own_did="did:plc:me") == "label spam"
    assert rejection_reason(cand(description=""), config, own_did="did:plc:me") == "empty bio"
    assert rejection_reason(cand(followers_count=5), config, own_did="did:plc:me") == "too few followers"
    assert rejection_reason(cand(followers_count=5000), config, own_did="did:plc:me") == "too many followers"
    assert rejection_reason(cand(posts_count=3), config, own_did="did:plc:me") == "too few posts"
    assert rejection_reason(cand(followers_count=100, follows_count=900), config, own_did="did:plc:me") == "follow ratio"
    assert rejection_reason(cand(description="NFT collector"), config, own_did="did:plc:me") == "blocked keyword 'nft'"
    # word boundary: a token embedded in another word is not a hit
    assert rejection_reason(cand(description="confnft conference"), config, own_did="did:plc:me") is None


def test_seed_candidates_keep_config_order_and_skip_own() -> None:
    graph = _graph()
    graph.profiles["did:plc:seed2"]["viewer"]["following"] = "at://did:plc:me/app.bsky.graph.follow/1"
    config = _config(seed_handles=["seed2.test", "boardwire.test", "seed1.test", "ghost.test"])

    seeds = seed_candidates(graph, config, _LOGGER, own_did="did:plc:me")
    assert [c.handle for c in seeds] == ["seed2.test", "seed1.test"]
    assert seeds[0].viewer_following is True   # the drip skips it, the summary shows it
    assert seeds[0].channels == {CHANNEL_SEED: 1.0}
    assert CHANNEL_SEED_FOLLOWERS not in seeds[0].channels


def test_verify_seeds_reports_unresolved_handles() -> None:
    graph = _graph()
    graph.latest["did:plc:seed1"] = _iso(3)
    config = _config(seed_handles=["seed1.test", "ghost.test"])

    rows = verify_seeds(graph, config, _LOGGER, now=_NOW)
    assert [row["ok"] for row in rows] == [True, False]
    assert rows[0]["handle"] == "seed1.test"
    assert rows[0]["followers"] == 5000
    assert rows[0]["last_post_days"] == 3.0
    assert rows[1]["reason"] == "unresolved"


# --- lists / starter packs --------------------------------------------------


def _graph_with_curator() -> FakeGraph:
    graph = _graph()
    graph.profiles["did:plc:list"] = _profile("curator.test")
    return graph


def test_resolve_list_uri_accepts_every_reference_shape() -> None:
    graph = _graph_with_curator()
    assert resolve_list_uri(graph, _LIST, _LOGGER) == _LIST
    assert resolve_list_uri(graph, "at://did:plc:list/app.bsky.graph.starterpack/pack", _LOGGER) == _LIST
    assert resolve_list_uri(graph, "https://bsky.app/starter-pack/curator.test/pack", _LOGGER) == _LIST
    assert resolve_list_uri(graph, "https://bsky.app/starter-pack/did:plc:list/pack", _LOGGER) == _LIST
    assert resolve_list_uri(graph, "https://bsky.app/profile/curator.test/lists/pack", _LOGGER) == _LIST
    assert resolve_list_uri(graph, "https://bsky.app/starter-pack/curator.test/missing", _LOGGER) is None
    assert resolve_list_uri(graph, "https://bsky.app/starter-pack/ghost.test/pack", _LOGGER) is None
    assert resolve_list_uri(graph, "https://example.com/not-a-list", _LOGGER) is None


def test_discovery_reads_starter_pack_members_via_web_url() -> None:
    graph = _graph_with_curator()
    config = _config(list_uris=["https://bsky.app/starter-pack/curator.test/pack"])
    found = discover_candidates(graph, config, _LOGGER, own_did="did:plc:me", now=_NOW)
    b = next(c for c in found if c.did == "did:plc:b")
    assert CHANNEL_LISTS in b.channels
    assert graph.calls["get_starter_pack"] == 1


def test_verify_lists_reports_name_size_and_unresolved() -> None:
    graph = _graph_with_curator()
    config = _config(list_uris=["https://bsky.app/starter-pack/curator.test/pack", "https://bsky.app/starter-pack/curator.test/nope"])
    rows = verify_lists(graph, config, _LOGGER)
    assert rows[0]["ok"] and rows[0]["name"] == "AI builders" and rows[0]["items"] == 42 and rows[0]["uri"] == _LIST
    assert rows[1] == {"reference": "https://bsky.app/starter-pack/curator.test/nope", "ok": False, "reason": "unresolved"}


def test_verify_seeds_flags_dormant_accounts() -> None:
    graph = _graph()
    graph.latest["did:plc:seed1"] = _iso(200)
    graph.latest["did:plc:seed2"] = _iso(10)
    config = _config(seed_handles=["seed1.test", "seed2.test"], seed_max_days_since_post=90)

    rows = verify_seeds(graph, config, _LOGGER, now=_NOW)
    assert rows[0]["ok"] is False and rows[0]["reason"].startswith("dormant (200d")
    assert rows[1]["ok"] is True and rows[1]["reason"] is None


def test_verify_seeds_flags_accounts_without_posts() -> None:
    graph = _graph()
    graph.profiles["did:plc:seed1"]["postsCount"] = 0
    graph.latest["did:plc:seed1"] = None
    rows = verify_seeds(graph, _config(seed_handles=["seed1.test"]), _LOGGER, now=_NOW)
    assert rows[0]["ok"] is False and rows[0]["reason"].startswith("no posts")
