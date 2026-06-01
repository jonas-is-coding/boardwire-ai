import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from src.feedback import dataset as dataset_module
from src.feedback import reference_feeds as ref_module
from src.feedback.bluesky_metrics import PostMetrics
from src.feedback.dataset import REFERENCE_FEATURE_NAMES, build_training_data
from src.feedback.engagement_store import record_snapshot
from src.feedback.reference_feeds import (
    ReferenceConfig,
    ReferencePost,
    fetch_reference_posts,
    load_reference_config,
)

_LOGGER = logging.getLogger("test")


def _ref_post(handle: str, uri: str, likes: int, text: str = "AI release ships") -> ReferencePost:
    return ReferencePost(
        handle=handle,
        uri=uri,
        text=text,
        created_at="2026-05-01T00:00:00Z",
        like_count=likes,
        repost_count=0,
        reply_count=0,
        quote_count=0,
        has_link=True,
    )


class _FakeEmbeddingService:
    """Deterministic embeddings keyed by FeedItem.link, no model load."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def embed_items(self, items):
        out = {}
        for item in items:
            # Stable pseudo-embedding from the link hash so rows differ.
            seed = abs(hash(item.link)) % (2**32)
            rng = np.random.default_rng(seed)
            out[item.link] = rng.normal(size=4).astype(np.float32)
        return out


# --- config ----------------------------------------------------------------


def test_load_reference_config_parses_handles(monkeypatch) -> None:
    monkeypatch.setenv(
        "BOARDWIRE_VIRALITY_REFERENCE_HANDLES", " a.bsky.social , b.bsky.social ,"
    )
    monkeypatch.setenv("BOARDWIRE_VIRALITY_OWN_WEIGHT", "4")
    cfg = load_reference_config()
    assert cfg.handles == ("a.bsky.social", "b.bsky.social")
    assert cfg.enabled is True
    assert cfg.own_weight == 4.0


def test_config_disabled_when_no_handles(monkeypatch) -> None:
    monkeypatch.delenv("BOARDWIRE_VIRALITY_REFERENCE_HANDLES", raising=False)
    cfg = load_reference_config()
    assert cfg.handles == ()
    assert cfg.enabled is False


# --- engagement weighting ---------------------------------------------------


def test_reference_total_engagement_matches_postmetrics() -> None:
    rp = ReferencePost(
        handle="h", uri="at://x", text="t", created_at=None,
        like_count=10, repost_count=3, reply_count=2, quote_count=1, has_link=False,
    )
    # Same weighting as our own posts: 10 + 2*3 + 2*1 + 2 = 20.
    assert rp.total_engagement == PostMetrics("at://x", 10, 3, 2, 1).total_engagement
    assert rp.total_engagement == 20


# --- feed fetching ----------------------------------------------------------


class _FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_reference_posts_skips_reposts_replies_and_recent(monkeypatch) -> None:
    old = "2026-05-01T00:00:00Z"
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    feed = {
        "feed": [
            # original mature post -> kept
            {"post": {"uri": "at://p1", "likeCount": 5, "record": {"text": "hello", "createdAt": old}}},
            # repost (has reason) -> skipped
            {"reason": {"$type": "repost"}, "post": {"uri": "at://p2", "record": {"text": "x", "createdAt": old}}},
            # reply -> skipped
            {"post": {"uri": "at://p3", "record": {"text": "y", "createdAt": old, "reply": {}}}},
            # too recent -> skipped
            {"post": {"uri": "at://p4", "likeCount": 9, "record": {"text": "z", "createdAt": recent}}},
        ],
        "cursor": None,
    }

    monkeypatch.setattr(ref_module, "_get_with_retry", lambda url, params, logger: _FakeResp(feed))

    cfg = ReferenceConfig(handles=("h.bsky.social",), max_posts_per_handle=100, min_account_posts=5, own_weight=3.0)
    posts = fetch_reference_posts(cfg, _LOGGER)

    assert [p.uri for p in posts] == ["at://p1"]
    assert posts[0].like_count == 5


# --- z-score training data --------------------------------------------------


def _mature_own(store, post_id, likes):
    published = "2026-05-01T00:00:00Z"
    observed = datetime(2026, 5, 2, 6, 0, 0, tzinfo=timezone.utc)  # 30h later
    post = {"id": post_id, "published_at": published, "external_id": "at://o/" + post_id}
    record_snapshot(store, post, PostMetrics("at://o/" + post_id, likes, 0, 0, 0), observed)
    return {"id": post_id, "post": f"own post {post_id}", "published_at": published, "score": 90, "source_link": "https://x"}


def test_reference_mode_builds_zscore_labels_and_weights(monkeypatch) -> None:
    monkeypatch.setattr(dataset_module, "EmbeddingService", _FakeEmbeddingService)

    store: dict = {}
    own_posts = [_mature_own(store, f"o{i}", likes) for i, likes in enumerate([3, 9])]

    # Two reference accounts, each with enough spread-out mature posts.
    refs = []
    for likes in (1, 5, 10, 50, 100):
        refs.append(_ref_post("big.bsky.social", f"at://big/{likes}", likes))
    for likes in (2, 4, 8, 16, 32):
        refs.append(_ref_post("mid.bsky.social", f"at://mid/{likes}", likes))

    data = build_training_data(
        own_posts, store, _LOGGER,
        reference_posts=refs, own_weight=3.0, min_account_posts=5,
    )

    assert data is not None
    assert data.label_kind == "zscore"
    assert data.structured_features == REFERENCE_FEATURE_NAMES
    assert "score" not in data.structured_features

    # Own account has only 2 mature posts (< min 5) -> dropped; 10 external rows.
    assert data.X.shape[0] == 10
    assert data.sample_weight is not None
    # No own rows survived, so all weights are the external default 1.0.
    assert np.allclose(data.sample_weight, 1.0)

    # Per-account z-score => labels within each account are mean ~0, std ~1.
    assert abs(float(data.y.mean())) < 1e-5
    assert abs(float(data.y.std()) - 1.0) < 1e-4


def test_reference_mode_keeps_and_upweights_own_when_enough(monkeypatch) -> None:
    monkeypatch.setattr(dataset_module, "EmbeddingService", _FakeEmbeddingService)

    store: dict = {}
    own_posts = [_mature_own(store, f"o{i}", likes) for i, likes in enumerate([1, 4, 8, 20, 40])]
    refs = [_ref_post("big.bsky.social", f"at://big/{k}", k) for k in (1, 5, 10, 50, 100)]

    data = build_training_data(
        own_posts, store, _LOGGER,
        reference_posts=refs, own_weight=3.0, min_account_posts=5,
    )
    assert data is not None
    assert data.X.shape[0] == 10  # 5 own + 5 external
    # 5 own rows weighted 3.0, 5 external weighted 1.0.
    assert sorted(np.unique(data.sample_weight).tolist()) == [1.0, 3.0]
    assert int((data.sample_weight == 3.0).sum()) == 5


def test_no_reference_posts_keeps_log1p_behaviour(monkeypatch) -> None:
    monkeypatch.setattr(dataset_module, "EmbeddingService", _FakeEmbeddingService)

    store: dict = {}
    own_posts = [_mature_own(store, f"o{i}", likes) for i, likes in enumerate([3, 9, 12])]

    data = build_training_data(own_posts, store, _LOGGER)
    assert data is not None
    assert data.label_kind == "log1p_engagement"
    assert data.sample_weight is None
    assert "score" in data.structured_features
