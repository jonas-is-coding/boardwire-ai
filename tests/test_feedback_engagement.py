from datetime import datetime, timedelta, timezone
import logging

from src.feedback import collect as collect_module
from src.feedback.bluesky_metrics import PostMetrics
from src.feedback.collect import collect_engagement
from src.feedback.engagement_store import (
    is_mature,
    latest_snapshot,
    record_snapshot,
    virality_label,
)

_LOGGER = logging.getLogger("test")


def _post(post_id: str, published_at: str, uri: str = "at://did:plc:x/app.bsky.feed.post/abc") -> dict:
    return {
        "id": post_id,
        "platform": "bluesky",
        "published_at": published_at,
        "external_id": uri,
        "post": "Some AI release ships today",
        "score": 90,
        "source_link": "https://example.com/x",
    }


def test_total_engagement_weights_reposts_and_quotes() -> None:
    metrics = PostMetrics("at://x", like_count=10, repost_count=3, reply_count=2, quote_count=1)
    # 10 + 2*3 + 2*1 + 2 = 20
    assert metrics.total_engagement == 20


def test_record_snapshot_computes_age_and_label() -> None:
    published = "2026-05-01T00:00:00Z"
    observed = datetime(2026, 5, 2, 0, 0, 0, tzinfo=timezone.utc)  # 24h later
    store: dict = {}
    record_snapshot(store, _post("p1", published), PostMetrics("at://x", 5, 0, 0, 0), observed)
    record_snapshot(store, _post("p1", published), PostMetrics("at://x", 12, 1, 0, 0), observed + timedelta(hours=12))

    record = store["p1"]
    assert len(record["snapshots"]) == 2
    assert record["snapshots"][0]["age_hours"] == 24.0
    assert latest_snapshot(record)["like_count"] == 12
    # peak weighted engagement: max(5, 12 + 2) = 14
    assert virality_label(record) == 14


def test_is_mature_requires_min_age_snapshot() -> None:
    published = "2026-05-01T00:00:00Z"
    store: dict = {}
    record_snapshot(
        store,
        _post("p1", published),
        PostMetrics("at://x", 1, 0, 0, 0),
        datetime(2026, 5, 1, 6, 0, 0, tzinfo=timezone.utc),  # only 6h old
    )
    assert is_mature(store["p1"], min_age_hours=24.0) is False

    record_snapshot(
        store,
        _post("p1", published),
        PostMetrics("at://x", 9, 0, 0, 0),
        datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc),  # 36h old
    )
    assert is_mature(store["p1"], min_age_hours=24.0) is True


def test_collect_engagement_skips_old_and_records_measured(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fresh = _post("fresh", (now - timedelta(days=1)).isoformat(), uri="at://did/app.bsky.feed.post/fresh")
    stale = _post("stale", (now - timedelta(days=60)).isoformat(), uri="at://did/app.bsky.feed.post/stale")

    def fake_fetch(uris, logger):
        return {u: PostMetrics(u, 7, 1, 0, 0) for u in uris}

    monkeypatch.setattr(collect_module, "fetch_post_metrics", fake_fetch)

    store: dict = {}
    summary = collect_engagement([fresh, stale], store, _LOGGER)

    assert summary.tracked == 1  # stale post excluded by age
    assert summary.measured == 1
    assert "fresh" in store and "stale" not in store
