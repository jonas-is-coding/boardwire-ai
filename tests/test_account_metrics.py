from __future__ import annotations

import json
from datetime import datetime, timezone
from logging import getLogger

from src.feedback import account_metrics as mod
from src.feedback.account_metrics import (
    AccountCounts,
    account_did_from_posts,
    account_trend,
    fetch_account_counts,
    record_account_snapshot,
    render_account_section,
)

_LOGGER = getLogger("test")


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_account_did_comes_from_the_newest_at_uri() -> None:
    published = [
        {"published_at": "2026-09-01T00:00:00Z", "external_id": "at://did:plc:old/app.bsky.feed.post/1"},
        {"published_at": "2026-09-03T00:00:00Z", "url": "at://did:plc:new/app.bsky.feed.post/2"},
        {"published_at": "2026-09-04T00:00:00Z", "external_id": "dry-run://thread/x/post/1"},
        "garbage",
    ]
    assert account_did_from_posts(published) == "did:plc:new"
    assert account_did_from_posts([]) is None


def test_fetch_account_counts_reads_public_profile(monkeypatch) -> None:
    calls: list = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Resp(200, {"did": "did:plc:me", "handle": "boardwire.bsky.social", "followersCount": 41, "followsCount": 24, "postsCount": 203})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    counts = fetch_account_counts("did:plc:me", _LOGGER)
    assert counts == AccountCounts(did="did:plc:me", handle="boardwire.bsky.social", followers=41, follows=24, posts=203)
    assert calls[0][1]["params"] == {"actor": "did:plc:me"}
    assert "public.api.bsky.app" in calls[0][0]

    monkeypatch.setattr(mod.requests, "get", lambda url, **kwargs: _Resp(502, {}))
    assert fetch_account_counts("did:plc:me", _LOGGER) is None


def test_snapshots_append_and_trend_reports_deltas(tmp_path) -> None:
    path = tmp_path / "account_snapshots.json"
    base = datetime(2026, 9, 4, 4, 0, tzinfo=timezone.utc)
    counts = AccountCounts(did="did:plc:me", handle="boardwire.bsky.social", followers=40, follows=24, posts=200)
    record_account_snapshot(path, counts, observed_at=base.replace(day=1))
    record_account_snapshot(path, AccountCounts("did:plc:me", "boardwire.bsky.social", 40, 24, 202), observed_at=base.replace(day=3))
    snapshots = record_account_snapshot(path, AccountCounts("did:plc:me", "boardwire.bsky.social", 43, 24, 203), observed_at=base)
    assert len(json.loads(path.read_text())) == 3

    trend = account_trend(snapshots, now=base)
    assert trend is not None
    assert (trend.followers, trend.followers_delta_1d, trend.followers_delta_7d) == (43, 3, None)
    assert trend.snapshots == 3

    section = "\n".join(render_account_section(snapshots, now=base))
    assert "**43** followers" in section and "1d: +3" in section and "7d: n/a" in section


def test_render_without_snapshots_is_a_hint_not_a_crash() -> None:
    assert account_trend([]) is None
    assert "No account snapshots yet" in "\n".join(render_account_section([]))
