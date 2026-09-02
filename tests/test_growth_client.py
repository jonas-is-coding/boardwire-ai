from __future__ import annotations

import logging

import pytest

from src.growth import client as mod
from src.growth.client import FOLLOW_COLLECTION, PROFILE_COLLECTION, GrowthClient, GrowthClientError

_LOGGER = logging.getLogger("test")


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b"{}"

    def json(self) -> dict:
        return self._payload


def _client(monkeypatch, calls: list, *, get=None, post=None) -> GrowthClient:
    def fake_get(url, **kwargs):
        calls.append({"method": "GET", "url": url, "kwargs": kwargs})
        return get(url, kwargs) if get else _Resp(200, {})

    def fake_post(url, **kwargs):
        calls.append({"method": "POST", "url": url, "kwargs": kwargs})
        if url.endswith("createSession"):
            return _Resp(200, {"accessJwt": "jwt", "did": "did:plc:me", "handle": "boardwire.bsky.social"})
        return post(url, kwargs) if post else _Resp(200, {"uri": "at://did:plc:me/x/1", "cid": "cid1"})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "post", fake_post)
    client = GrowthClient("@boardwire.bsky.social", "pw", logger=_LOGGER, sleeper=lambda s: None)
    client.login()
    return client


def _actors(call: dict) -> list[str]:
    return [value for key, value in call["kwargs"]["params"] if key == "actors"]


def test_login_sets_session_and_strips_at(monkeypatch) -> None:
    calls: list = []
    client = _client(monkeypatch, calls)
    assert client.did == "did:plc:me"
    assert client.access_jwt == "jwt"
    assert client.handle == "boardwire.bsky.social"
    assert calls[0]["kwargs"]["json"]["identifier"] == "boardwire.bsky.social"
    assert "Authorization" not in calls[0]["kwargs"]["headers"]


def test_login_failure_raises_with_error_name(monkeypatch) -> None:
    monkeypatch.setattr(
        mod.requests,
        "post",
        lambda url, **kw: _Resp(401, {"error": "AuthenticationRequired", "message": "Invalid identifier or password"}),
    )
    client = GrowthClient("h", "pw", logger=_LOGGER, sleeper=lambda s: None)
    with pytest.raises(GrowthClientError) as exc:
        client.login()
    assert exc.value.status == 401
    assert exc.value.error == "AuthenticationRequired"


def test_reads_require_login(monkeypatch) -> None:
    client = GrowthClient("h", "pw", logger=_LOGGER, sleeper=lambda s: None)
    with pytest.raises(GrowthClientError):
        client.get_profile("x")


def test_get_profiles_batches_by_25_with_bearer(monkeypatch) -> None:
    calls: list = []

    def get(url, kwargs):
        actors = [value for key, value in kwargs["params"] if key == "actors"]
        return _Resp(200, {"profiles": [{"did": a, "handle": f"{a}.test"} for a in actors]})

    client = _client(monkeypatch, calls, get=get)
    profiles = client.get_profiles([f"did:plc:{i}" for i in range(60)])

    get_calls = [c for c in calls if c["method"] == "GET"]
    assert len(get_calls) == 3
    assert [len(_actors(c)) for c in get_calls] == [25, 25, 10]
    assert all(c["kwargs"]["headers"]["Authorization"] == "Bearer jwt" for c in get_calls)
    assert len(profiles) == 60


def test_follow_creates_follow_record(monkeypatch) -> None:
    calls: list = []
    client = _client(monkeypatch, calls)
    resp = client.follow("did:plc:target")

    assert calls[-1]["url"].endswith("com.atproto.repo.createRecord")
    body = calls[-1]["kwargs"]["json"]
    assert body["collection"] == FOLLOW_COLLECTION
    assert body["repo"] == "did:plc:me"
    assert body["record"]["$type"] == FOLLOW_COLLECTION
    assert body["record"]["subject"] == "did:plc:target"
    assert body["record"]["createdAt"].endswith("Z")
    assert resp["uri"]


def test_follow_rejects_non_did_subject(monkeypatch) -> None:
    calls: list = []
    client = _client(monkeypatch, calls)
    with pytest.raises(GrowthClientError):
        client.follow("someone.bsky.social")
    assert not any(c["url"].endswith("createRecord") for c in calls)


def test_put_record_sends_swap_and_refuses_unknown_collection(monkeypatch) -> None:
    calls: list = []
    client = _client(monkeypatch, calls)
    client.put_record(PROFILE_COLLECTION, "self", {"displayName": "x"}, swap_record="cid-old")

    assert calls[-1]["url"].endswith("com.atproto.repo.putRecord")
    body = calls[-1]["kwargs"]["json"]
    assert body["rkey"] == "self"
    assert body["swapRecord"] == "cid-old"

    with pytest.raises(GrowthClientError):
        client.put_record("app.bsky.graph.block", "x", {})


def test_get_record_returns_none_when_missing(monkeypatch) -> None:
    def get(url, kwargs):
        return _Resp(400, {"error": "RecordNotFound", "message": "Could not locate record"})

    client = _client(monkeypatch, [], get=get)
    assert client.get_record(PROFILE_COLLECTION, "self") is None


def test_get_record_reraises_other_errors(monkeypatch) -> None:
    def get(url, kwargs):
        return _Resp(400, {"error": "InvalidRequest", "message": "bad repo"})

    client = _client(monkeypatch, [], get=get)
    with pytest.raises(GrowthClientError):
        client.get_record(PROFILE_COLLECTION, "self")


def test_rate_limited_write_is_not_retried(monkeypatch) -> None:
    calls: list = []

    def post(url, kwargs):
        return _Resp(429, {"error": "RateLimitExceeded"})

    client = _client(monkeypatch, calls, post=post)
    with pytest.raises(GrowthClientError) as exc:
        client.follow("did:plc:x")
    assert exc.value.rate_limited
    assert len([c for c in calls if c["url"].endswith("createRecord")]) == 1


def test_get_retries_once_on_5xx(monkeypatch) -> None:
    state = {"n": 0}

    def get(url, kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return _Resp(503, {})
        return _Resp(200, {"follows": [{"did": "did:plc:a", "handle": "a.test"}]})

    client = _client(monkeypatch, [], get=get)
    assert [p["did"] for p in client.get_follows("did:plc:seed", limit=10)] == ["did:plc:a"]
    assert state["n"] == 2


def test_paginate_follows_cursor_and_caps_limit(monkeypatch) -> None:
    def get(url, kwargs):
        if kwargs["params"].get("cursor") is None:
            return _Resp(200, {"follows": [{"did": "did:plc:1", "handle": "one"}], "cursor": "c1"})
        return _Resp(200, {"follows": [{"did": "did:plc:2", "handle": "two"}, {"did": "did:plc:3", "handle": "three"}]})

    client = _client(monkeypatch, [], get=get)
    assert [p["did"] for p in client.get_follows("did:plc:seed", limit=2)] == ["did:plc:1", "did:plc:2"]


def test_get_list_members_unwraps_subjects(monkeypatch) -> None:
    def get(url, kwargs):
        assert url.endswith("app.bsky.graph.getList")
        return _Resp(200, {"items": [{"subject": {"did": "did:plc:l1", "handle": "l1"}}, {"uri": "broken"}]})

    client = _client(monkeypatch, [], get=get)
    assert [p["did"] for p in client.get_list_members("at://did:plc:x/app.bsky.graph.list/pack")] == ["did:plc:l1"]


def test_latest_post_at_skips_reposts(monkeypatch) -> None:
    def get(url, kwargs):
        assert kwargs["params"]["limit"] == "10"  # one item would let a repost on top hide the real last post
        return _Resp(
            200,
            {
                "feed": [
                    {"reason": {"$type": "app.bsky.feed.defs#reasonRepost"}, "post": {"record": {"createdAt": "2020-01-01T00:00:00Z"}}},
                    {"post": {"record": {"createdAt": "2026-09-01T10:00:00Z"}}},
                ]
            },
        )

    client = _client(monkeypatch, [], get=get)
    assert client.latest_post_at("did:plc:a") == "2026-09-01T10:00:00Z"


def test_public_reader_reads_without_auth_and_refuses_writes(monkeypatch) -> None:
    calls: list = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return _Resp(200, {"profiles": [{"did": "did:plc:a", "handle": "a.test"}]})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "post", lambda url, **kw: pytest.fail("public reader must never POST"))

    client = GrowthClient.public_reader(logger=_LOGGER, sleeper=lambda s: None)
    assert client.is_public
    assert [p["did"] for p in client.get_profiles(["a.test"])] == ["did:plc:a"]
    assert calls[0]["url"].startswith("https://public.api.bsky.app/xrpc/")
    assert "Authorization" not in calls[0]["kwargs"]["headers"]
    with pytest.raises(GrowthClientError):
        client.follow("did:plc:a")
    with pytest.raises(GrowthClientError):
        client.login()


def test_starter_pack_and_list_info_reads(monkeypatch) -> None:
    def get(url, kwargs):
        if url.endswith("app.bsky.graph.getStarterPack"):
            assert kwargs["params"]["starterPack"] == "at://did:plc:c/app.bsky.graph.starterpack/p"
            return _Resp(200, {"starterPack": {"list": {"uri": "at://did:plc:c/app.bsky.graph.list/l"}}})
        assert url.endswith("app.bsky.graph.getList") and kwargs["params"]["limit"] == "1"
        return _Resp(200, {"list": {"name": "Builders", "listItemCount": 7}, "items": []})

    client = _client(monkeypatch, [], get=get)
    assert client.get_starter_pack("at://did:plc:c/app.bsky.graph.starterpack/p")["list"]["uri"].endswith("/l")
    assert client.get_list_info("at://did:plc:c/app.bsky.graph.list/l") == {"name": "Builders", "listItemCount": 7}


def test_latest_post_at_pages_past_a_run_of_reposts(monkeypatch) -> None:
    repost = {"reason": {"$type": "app.bsky.feed.defs#reasonRepost"}, "post": {"record": {"createdAt": "2020-01-01T00:00:00Z"}}}

    def get(url, kwargs):
        if kwargs["params"].get("cursor") is None:
            return _Resp(200, {"feed": [repost] * 10, "cursor": "page2"})
        return _Resp(200, {"feed": [repost, {"post": {"record": {"createdAt": "2026-08-30T10:00:00Z"}}}]})

    client = _client(monkeypatch, [], get=get)
    assert client.latest_post_at("did:plc:a") == "2026-08-30T10:00:00Z"


def test_latest_post_at_gives_up_after_max_pages(monkeypatch) -> None:
    repost = {"reason": {"$type": "app.bsky.feed.defs#reasonRepost"}, "post": {"record": {"createdAt": "2020-01-01T00:00:00Z"}}}
    calls: list = []

    def get(url, kwargs):
        return _Resp(200, {"feed": [repost] * 10, "cursor": f"c{len(calls)}"})

    client = _client(monkeypatch, calls, get=get)
    assert client.latest_post_at("did:plc:a", max_pages=3) is None
    assert len([c for c in calls if c["method"] == "GET"]) == 3


def test_list_records_reads_own_repo_newest_first(monkeypatch) -> None:
    def get(url, kwargs):
        assert url.endswith("com.atproto.repo.listRecords")
        assert kwargs["params"] == {"repo": "did:plc:me", "collection": "app.bsky.feed.post", "limit": "50", "reverse": "true"}
        return _Resp(200, {"records": [{"uri": "at://did:plc:me/app.bsky.feed.post/1", "cid": "c1", "value": {"text": "x"}}, "junk"]})

    client = _client(monkeypatch, [], get=get)
    assert [r["cid"] for r in client.list_records("app.bsky.feed.post")] == ["c1"]
