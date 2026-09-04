from __future__ import annotations

from logging import getLogger

from src.feedback import reply_digest as mod
from src.feedback.reply_digest import (
    ReplyDigestConfig,
    build_digest_text,
    collect_reply_candidates,
    load_reply_digest_config,
)

_LOGGER = getLogger("test")


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _search_payload() -> dict:
    return {
        "posts": [
            {
                "uri": "at://did:plc:aaa/app.bsky.feed.post/111",
                "author": {"handle": "builder.bsky.social"},
                "record": {"text": "Shipping an MCP server for our internal tools, works great"},
                "likeCount": 20,
                "replyCount": 4,
                "repostCount": 3,
            },
            {
                "uri": "at://did:plc:bbb/app.bsky.feed.post/222",
                "author": {"handle": "quiet.bsky.social"},
                "record": {"text": "low engagement post"},
                "likeCount": 1,
                "replyCount": 0,
                "repostCount": 0,
            },
            {
                "uri": "at://did:plc:ccc/app.bsky.feed.post/333",
                "author": {"handle": "boardwire.bsky.social"},
                "record": {"text": "our own post must be excluded"},
                "likeCount": 50,
                "replyCount": 5,
                "repostCount": 5,
            },
        ]
    }


def test_collect_filters_and_ranks(monkeypatch) -> None:
    calls: list = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return _Resp(200, _search_payload())

    monkeypatch.setattr(mod.requests, "get", fake_get)

    config = ReplyDigestConfig(keywords=["MCP"], max_posts=8, posts_per_keyword=5, min_engagement=5)
    candidates = collect_reply_candidates(config, _LOGGER, own_handle="boardwire.bsky.social")

    # Read-only: only GETs against the public search endpoint, never a POST.
    assert all("searchPosts" in c["url"] for c in calls)
    # Low-engagement and own posts filtered out.
    assert [c.author_handle for c in candidates] == ["builder.bsky.social"]
    assert candidates[0].engagement == 30  # 20 + 2*3 + 4


def test_digest_never_posts_to_bluesky(monkeypatch) -> None:
    """The digest path must not perform any write request to Bluesky."""
    posted: list = []

    def fake_get(url, **kwargs):
        return _Resp(200, _search_payload())

    def fake_post(url, **kwargs):  # any POST would be a violation unless it's Slack
        posted.append(url)
        return _Resp(200, {})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "post", fake_post)
    monkeypatch.setenv("BLUESKY_HANDLE", "boardwire.bsky.social")
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)  # no session → not even a login POST
    # LLM drafting off (no providers configured in tests) → suggestion is None.
    import src.notifications.persona_voice as voice

    monkeypatch.setattr(voice, "draft_reply_suggestion", lambda *a, **k: "Try pairing it with a local runner?")
    import src.notifications.slack as slack

    slack_calls: list = []
    monkeypatch.setattr(slack, "reply_digest", lambda text: slack_calls.append(text))

    count = mod.run_reply_digest(_LOGGER, config=ReplyDigestConfig(keywords=["MCP"], max_posts=3, posts_per_keyword=3, min_engagement=5))

    assert count == 1
    assert posted == []  # zero POSTs from this module: nothing published anywhere
    assert len(slack_calls) == 1
    assert "suggestions only" in slack_calls[0].lower() or "nothing was posted" in slack_calls[0].lower()


def test_digest_text_marks_missing_suggestions(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        return _Resp(200, _search_payload())

    monkeypatch.setattr(mod.requests, "get", fake_get)
    config = ReplyDigestConfig(keywords=["MCP"], max_posts=3, posts_per_keyword=3, min_engagement=5)
    candidates = collect_reply_candidates(config, _LOGGER)
    text = build_digest_text(candidates)

    assert "nothing was posted" in text
    assert "bsky.app/profile/builder.bsky.social/post/111" in text
    assert "no draft available" in text


def test_load_config_defaults(tmp_path) -> None:
    config = load_reply_digest_config(tmp_path / "missing.json")
    assert config.keywords  # falls back to niche defaults
    assert config.max_posts >= 1


# --- target accounts, freshness, crowding ------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from src.feedback.reply_digest import SOURCE_KEYWORD, SOURCE_TARGET, select_digest  # noqa: E402

_NOW = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (_NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _post(handle: str, rkey: str, *, hours_ago: float, likes: int = 0, replies: int = 0, reposts: int = 0, text: str = "Shipping an MCP server today") -> dict:
    return {
        "uri": f"at://did:plc:{handle.split('.')[0]}/app.bsky.feed.post/{rkey}",
        "author": {"handle": handle},
        "record": {"text": text, "createdAt": _iso(hours_ago)},
        "likeCount": likes,
        "replyCount": replies,
        "repostCount": reposts,
    }


def _feed(posts: list[dict], *, with_repost: bool = False) -> dict:
    feed = [{"post": p} for p in posts]
    if with_repost:
        feed.insert(0, {"post": _post("someone.test", "rp", hours_ago=1, likes=999), "reason": {"$type": "app.bsky.feed.defs#reasonRepost"}})
    return {"feed": feed}


def _patch_get(monkeypatch, feeds: dict[str, list[dict]], search: list[dict]) -> list:
    calls: list = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        if "getAuthorFeed" in url:
            actor = kwargs["params"]["actor"]
            return _Resp(200, _feed(feeds.get(actor, []), with_repost=True))
        return _Resp(200, {"posts": search})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    return calls


def test_target_quota_beats_viral_strangers(monkeypatch) -> None:
    feeds = {
        "t1.test": [_post("t1.test", "a", hours_ago=5, likes=1), _post("t1.test", "b", hours_ago=2)],
        "t2.test": [_post("t2.test", "c", hours_ago=9, likes=3)],
    }
    viral = [_post(f"viral{i}.test", f"v{i}", hours_ago=3, likes=500 + i) for i in range(5)]
    calls = _patch_get(monkeypatch, feeds, viral)
    config = ReplyDigestConfig(keywords=["MCP"], target_handles=["@T1.test", "t2.test"], max_posts=5, target_quota=0.6)

    picked = collect_reply_candidates(config, _LOGGER, now=_NOW)

    assert len(picked) == 5
    assert [c.source for c in picked] == [SOURCE_TARGET] * 3 + [SOURCE_KEYWORD] * 2
    # target posts: newest first, engagement is secondary
    assert [c.uri.rsplit("/", 1)[-1] for c in picked[:3]] == ["b", "a", "c"]
    # keyword posts: engagement first
    assert [c.like_count for c in picked[3:]] == [504, 503]
    # the target account's repost never becomes a candidate
    assert all(c.author_handle != "someone.test" for c in picked)
    # every request was a read-only GET on the public AppView
    assert all("public.api.bsky.app" in c["url"] for c in calls)
    assert {c["kwargs"]["params"]["actor"] for c in calls if "getAuthorFeed" in c["url"]} == {"t1.test", "t2.test"}


def test_freshness_filter_and_since_param(monkeypatch) -> None:
    search = [
        _post("old.test", "o", hours_ago=5 * 24, likes=200),
        _post("fresh.test", "f", hours_ago=4, likes=20),
        {"uri": "at://did:plc:nodate/app.bsky.feed.post/n", "author": {"handle": "nodate.test"}, "record": {"text": "no createdAt"}, "likeCount": 30},
    ]
    calls = _patch_get(monkeypatch, {}, search)
    config = ReplyDigestConfig(keywords=["MCP"], max_posts=8, max_age_hours=36)

    picked = collect_reply_candidates(config, _LOGGER, now=_NOW)

    assert [c.author_handle for c in picked] == ["nodate.test", "fresh.test"]  # unknown date is kept, human decides
    assert picked[1].age_hours(_NOW) == 4.0
    assert calls[0]["kwargs"]["params"]["since"] == _iso(36)


def test_crowding_skips_busy_threads_and_caps_per_author(monkeypatch) -> None:
    search = [
        _post("busy.test", "1", hours_ago=2, likes=50, replies=120),
        _post("prolific.test", "2", hours_ago=2, likes=40),
        _post("prolific.test", "3", hours_ago=3, likes=30),
        _post("prolific.test", "4", hours_ago=4, likes=20),
        _post("other.test", "5", hours_ago=5, likes=10),
    ]
    _patch_get(monkeypatch, {}, search)
    config = ReplyDigestConfig(keywords=["MCP"], max_posts=8, max_reply_count=40, max_per_author=2)

    picked = collect_reply_candidates(config, _LOGGER, now=_NOW)

    assert [c.uri.rsplit("/", 1)[-1] for c in picked] == ["2", "3", "5"]


def test_targets_fill_when_keyword_pool_is_short(monkeypatch) -> None:
    feeds = {"t1.test": [_post("t1.test", str(i), hours_ago=i) for i in range(1, 5)]}
    _patch_get(monkeypatch, feeds, [])
    config = ReplyDigestConfig(keywords=["MCP"], target_handles=["t1.test"], max_posts=5, target_quota=0.6, max_per_author=4)

    picked = collect_reply_candidates(config, _LOGGER, now=_NOW)
    assert len(picked) == 4
    assert all(c.is_target for c in picked)


def test_target_author_found_via_search_counts_as_target(monkeypatch) -> None:
    search = [_post("t1.test", "s", hours_ago=1), _post("x.test", "x", hours_ago=1, likes=50)]
    _patch_get(monkeypatch, {}, search)
    config = ReplyDigestConfig(keywords=["MCP"], target_handles=["t1.test"], max_posts=4, target_quota=0.5)

    picked = collect_reply_candidates(config, _LOGGER, now=_NOW)
    assert [(c.author_handle, c.source) for c in picked] == [("t1.test", SOURCE_TARGET), ("x.test", SOURCE_KEYWORD)]


def test_select_digest_without_targets_uses_all_slots_for_keywords() -> None:
    config = ReplyDigestConfig(keywords=["MCP"], max_posts=2, target_quota=0.6)
    kw = [mod.ReplyCandidate(uri=f"at://k/{i}", author_handle=f"k{i}", text="t", keyword="MCP", like_count=i, reply_count=0, repost_count=0) for i in range(3)]
    assert [c.uri for c in select_digest([], kw, config, now=_NOW)] == ["at://k/2", "at://k/1"]
    assert config.target_slots == 0


def test_load_config_parses_new_fields(tmp_path) -> None:
    path = tmp_path / "reply_digest.json"
    path.write_text(
        '{"keywords": ["MCP"], "target_handles": ["@T1.Test", "t1.test", " "], "target_quota": 1.7, '
        '"max_age_hours": 12, "max_reply_count": 10, "max_per_author": 1, "target_min_engagement": 2}'
    )
    config = load_reply_digest_config(path)
    assert config.target_handles == ["t1.test"]
    assert config.target_quota == 1.0
    assert config.max_age_hours == 12.0
    assert config.max_reply_count == 10
    assert config.max_per_author == 1
    assert config.target_min_engagement == 2
    assert config.target_slots == 8


def test_digest_text_labels_targets_and_age(monkeypatch) -> None:
    feeds = {"t1.test": [_post("t1.test", "a", hours_ago=3)]}
    _patch_get(monkeypatch, feeds, [_post("k.test", "k", hours_ago=6, likes=9)])
    config = ReplyDigestConfig(keywords=["MCP"], target_handles=["t1.test"], max_posts=4)

    text = build_digest_text(collect_reply_candidates(config, _LOGGER, now=_NOW), now=_NOW)

    assert "1 from target accounts, 1 from keyword search" in text
    assert "target account" in text and "3h ago" in text
    assert "keyword: `MCP`" in text and "6h ago" in text
    assert "nothing was posted" in text


def test_target_feed_pages_past_reposts_until_enough_originals(monkeypatch) -> None:
    repost = {"post": _post("someone.test", "rp", hours_ago=1, likes=999), "reason": {"$type": "app.bsky.feed.defs#reasonRepost"}}
    pages = {
        None: {"feed": [repost] * 10, "cursor": "p2"},
        "p2": {"feed": [repost, {"post": _post("t1.test", "a", hours_ago=2)}, {"post": _post("t1.test", "b", hours_ago=3)}], "cursor": "p3"},
        "p3": {"feed": [{"post": _post("t1.test", "c", hours_ago=4)}]},
    }
    calls: list = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["params"])
        if "getAuthorFeed" in url:
            return _Resp(200, pages[kwargs["params"].get("cursor")])
        return _Resp(200, {"posts": []})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    config = ReplyDigestConfig(keywords=["MCP"], target_handles=["t1.test"], max_posts=5, posts_per_target=2, max_per_author=5)

    picked = collect_reply_candidates(config, _LOGGER, now=_NOW)

    assert [c.uri.rsplit("/", 1)[-1] for c in picked] == ["a", "b"]  # stopped once posts_per_target originals were found
    assert [p.get("cursor") for p in calls if "actor" in p] == [None, "p2"]


def test_digest_with_credentials_searches_through_the_pds_and_never_writes(monkeypatch) -> None:
    """The public AppView answers 403 to searchPosts from CI. With an app
    password the keyword search must go through the authenticated PDS; the
    only POST allowed is createSession — never a repo write."""
    gets: list = []
    posts: list = []

    def fake_get(url, **kwargs):
        gets.append({"url": url, "kwargs": kwargs})
        return _Resp(200, _search_payload())

    def fake_post(url, **kwargs):
        posts.append({"url": url, "kwargs": kwargs})
        assert url.endswith("com.atproto.server.createSession")
        return _Resp(200, {"accessJwt": "jwt-read", "did": "did:plc:me"})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "post", fake_post)
    monkeypatch.setenv("BLUESKY_HANDLE", "boardwire.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "app-pw")
    import src.notifications.persona_voice as voice
    import src.notifications.slack as slack

    monkeypatch.setattr(voice, "draft_reply_suggestion", lambda *a, **k: "Try pairing it with a local runner?")
    monkeypatch.setattr(slack, "reply_digest", lambda text: None)

    count = mod.run_reply_digest(_LOGGER, config=ReplyDigestConfig(keywords=["MCP"], max_posts=3, posts_per_keyword=3, min_engagement=5))

    assert count == 1
    assert [p["url"] for p in posts] == [mod._CREATE_SESSION_URL]
    assert posts[0]["kwargs"]["json"] == {"identifier": "boardwire.bsky.social", "password": "app-pw"}
    assert not any("com.atproto.repo" in p["url"] for p in posts)
    searches = [g for g in gets if "searchPosts" in g["url"]]
    assert searches and all(g["url"] == mod._AUTH_SEARCH_POSTS_URL for g in searches)
    assert all(g["kwargs"]["headers"] == {"Authorization": "Bearer jwt-read"} for g in searches)


def test_failed_login_falls_back_to_public_search(monkeypatch) -> None:
    gets: list = []

    def fake_get(url, **kwargs):
        gets.append({"url": url, "kwargs": kwargs})
        return _Resp(200, {"posts": []})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "post", lambda url, **kwargs: _Resp(401, {"error": "AuthenticationRequired"}))

    token = mod.bluesky_read_session(_LOGGER, handle="boardwire.bsky.social", app_password="wrong")
    assert token is None
    mod.collect_reply_candidates(ReplyDigestConfig(keywords=["MCP"]), _LOGGER, token=token)
    assert [g["url"] for g in gets] == [mod._SEARCH_POSTS_URL]
    assert gets[0]["kwargs"]["headers"] is None


def test_reply_suggestions_reset_the_provider_chain_per_candidate(monkeypatch) -> None:
    from src.llm import sarah_generation

    from datetime import datetime, timedelta, timezone

    def _fresh(rkey: str, hours: float) -> dict:
        post = _post("a.test", rkey, hours_ago=0)
        post["record"]["createdAt"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        return post

    feeds = {"a.test": [_fresh("1", 2), _fresh("2", 3)]}  # run_reply_digest uses the real clock
    _patch_get(monkeypatch, feeds, [])
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    import src.notifications.persona_voice as voice
    import src.notifications.slack as slack

    resets: list = []
    monkeypatch.setattr(sarah_generation, "reset_state", lambda: resets.append(1))
    monkeypatch.setattr(voice, "draft_reply_suggestion", lambda *a, **k: "A substantive reply suggestion.")
    monkeypatch.setattr(slack, "reply_digest", lambda text: None)

    config = ReplyDigestConfig(keywords=[], target_handles=["a.test"], max_posts=4, posts_per_target=2, max_per_author=2)
    assert mod.run_reply_digest(_LOGGER, config=config) == 2
    assert len(resets) == 2
