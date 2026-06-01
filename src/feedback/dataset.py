from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timezone
from logging import Logger
from typing import Any

import numpy as np
from dateutil import parser as date_parser

from src.board.embeddings import EmbeddingService
from src.config import EMBEDDINGS_CACHE_PATH
from src.feedback.engagement_store import is_mature, virality_label
from src.models import FeedItem

# Structured features appended after the text embedding. Keep this list in sync
# with _structured_features so the stored model's feature_dim stays meaningful.
STRUCTURED_FEATURE_NAMES = (
    "score",
    "post_len",
    "hour_of_day",
    "has_release_kw",
    "has_link",
)

# When training also learns from other channels' posts (reference mode) the
# internal funnel "score" does not exist for foreign posts, so we drop it to keep
# the feature space identical for our posts and theirs — otherwise a constant
# stand-in would secretly encode "is this one of ours".
REFERENCE_FEATURE_NAMES = tuple(n for n in STRUCTURED_FEATURE_NAMES if n != "score")

_RELEASE_KEYWORDS = (
    "release",
    "released",
    "ships",
    "launch",
    "open-source",
    "open source",
    "weights",
    "api",
    "sdk",
)


@dataclass(slots=True)
class TrainingData:
    X: np.ndarray
    y: np.ndarray
    ids: list[str]
    feature_dim: int
    # Optional per-row training weights (e.g. to anchor the model on our own
    # voice when learning from larger reference channels). None means uniform.
    sample_weight: np.ndarray | None = None
    # How the label was constructed, so the scorer back-transforms correctly:
    #   "log1p_engagement" — y = log1p(weighted engagement) (single-account)
    #   "zscore"           — y = per-account z-score of log1p(engagement)
    label_kind: str = "log1p_engagement"
    # Which structured features were used (stored so scoring stays in sync).
    structured_features: tuple[str, ...] = STRUCTURED_FEATURE_NAMES


def _structured_features(
    post: dict[str, Any], names: tuple[str, ...] = STRUCTURED_FEATURE_NAMES
) -> list[float]:
    text = post.get("post") or ""
    lowered = text.lower()
    try:
        score = float(post.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0

    hour = 0.0
    published_at = post.get("published_at")
    if published_at:
        try:
            dt = date_parser.parse(published_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hour = float(dt.astimezone(timezone.utc).hour)
        except (ValueError, OverflowError, TypeError):
            hour = 0.0

    values = {
        "score": score,
        "post_len": float(len(text)),
        "hour_of_day": hour,
        "has_release_kw": 1.0 if any(k in lowered for k in _RELEASE_KEYWORDS) else 0.0,
        "has_link": 1.0 if post.get("source_link") else 0.0,
    }
    return [values[name] for name in names]


def _post_to_feed_item(post: dict[str, Any]) -> FeedItem:
    from datetime import datetime

    # ``embed_link`` lets reference posts force a unique embedding-cache key
    # (their AT-URI) so two foreign posts that link to the same article are not
    # collapsed into one row; our own posts keep their existing source_link key.
    link = (
        post.get("embed_link")
        or post.get("source_link")
        or f"id:{post.get('id', '')}"
    )
    return FeedItem(
        source=post.get("platform", "bluesky"),
        title=post.get("source_title") or post.get("post", "")[:120],
        link=link,
        summary=post.get("post", ""),
        published_at=datetime.now(timezone.utc),
    )


_OWN_ACCOUNT = "__own__"


def build_training_data(
    published: list[dict[str, Any]],
    store: dict[str, Any],
    logger: Logger,
    min_age_hours: float = 24.0,
    reference_posts: list[Any] | None = None,
    own_weight: float = 1.0,
    min_account_posts: int = 5,
) -> TrainingData | None:
    """Assemble (features, label) rows for posts with mature engagement data.

    Single-account mode (no ``reference_posts``): labels are ``log1p`` of our own
    weighted engagement — unchanged historical behaviour.

    Reference mode (``reference_posts`` given): we *also* learn from larger
    comparable channels. To stop big accounts from simply teaching "have more
    followers", each account's posts are labelled by their **z-score within that
    account** (how well the post did *for that channel*), which is exactly the
    relative signal a ranking scorer needs. Our own posts can be up-weighted via
    ``own_weight`` so the model stays anchored on our voice.
    """
    if reference_posts:
        return _build_reference_training_data(
            published,
            store,
            reference_posts,
            logger,
            min_age_hours=min_age_hours,
            own_weight=own_weight,
            min_account_posts=min_account_posts,
        )

    rows: list[tuple[str, dict[str, Any], int]] = []
    for post in published:
        post_id = post.get("id")
        record = store.get(post_id) if post_id else None
        if not record or not is_mature(record, min_age_hours):
            continue
        rows.append((post_id, post, virality_label(record)))

    if not rows:
        logger.info("No mature engagement rows available for training yet")
        return None

    embed_service = EmbeddingService(EMBEDDINGS_CACHE_PATH, logger=logger)
    feed_items = [_post_to_feed_item(post) for _, post, _ in rows]
    embeddings = embed_service.embed_items(feed_items)

    feature_rows: list[np.ndarray] = []
    labels: list[float] = []
    ids: list[str] = []
    for (post_id, post, label), item in zip(rows, feed_items):
        emb = embeddings.get(item.link)
        if emb is None:
            continue
        structured = np.asarray(_structured_features(post), dtype=np.float32)
        feature_rows.append(np.concatenate([emb, structured]))
        # log1p compresses the heavy tail of engagement counts.
        labels.append(math.log1p(float(label)))
        ids.append(post_id)

    if not feature_rows:
        return None

    X = np.vstack(feature_rows).astype(np.float32)
    y = np.asarray(labels, dtype=np.float32)
    return TrainingData(X=X, y=y, ids=ids, feature_dim=X.shape[1])


def _build_reference_training_data(
    published: list[dict[str, Any]],
    store: dict[str, Any],
    reference_posts: list[Any],
    logger: Logger,
    *,
    min_age_hours: float,
    own_weight: float,
    min_account_posts: int,
) -> TrainingData | None:
    # One unified row shape for our posts and foreign posts: (account, unique id,
    # post-like dict for features/embedding, raw weighted engagement, is_own).
    rows: list[tuple[str, str, dict[str, Any], int, bool]] = []

    for post in published:
        post_id = post.get("id")
        record = store.get(post_id) if post_id else None
        if not record or not is_mature(record, min_age_hours):
            continue
        rows.append((_OWN_ACCOUNT, post_id, post, virality_label(record), True))

    for rp in reference_posts:
        rows.append((rp.handle, rp.uri, rp.to_post_dict(), rp.total_engagement, False))

    if not rows:
        logger.info("No mature engagement rows available for training yet")
        return None

    # Per-account z-score of log1p(engagement). Accounts with too few mature
    # posts (or no spread) can't yield a stable normaliser, so they're dropped.
    by_account: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        by_account.setdefault(row[0], []).append(i)

    zlabels: dict[int, float] = {}
    for account, idxs in by_account.items():
        logs = np.array(
            [math.log1p(float(rows[i][3])) for i in idxs], dtype=np.float64
        )
        if len(idxs) < min_account_posts:
            logger.info(
                "Reference account %s skipped: %d/%d mature posts",
                account,
                len(idxs),
                min_account_posts,
            )
            continue
        std = float(logs.std())
        if std == 0.0:
            logger.info("Reference account %s skipped: no engagement spread", account)
            continue
        mean = float(logs.mean())
        for i in idxs:
            zlabels[i] = (math.log1p(float(rows[i][3])) - mean) / std

    kept = [i for i in range(len(rows)) if i in zlabels]
    if not kept:
        logger.info(
            "Reference training skipped: no account had >= %d mature posts",
            min_account_posts,
        )
        return None

    embed_service = EmbeddingService(EMBEDDINGS_CACHE_PATH, logger=logger)
    feed_items = [_post_to_feed_item(rows[i][2]) for i in kept]
    embeddings = embed_service.embed_items(feed_items)

    feature_rows: list[np.ndarray] = []
    labels: list[float] = []
    weights: list[float] = []
    ids: list[str] = []
    for i, item in zip(kept, feed_items):
        emb = embeddings.get(item.link)
        if emb is None:
            continue
        _account, row_id, post, _engagement, is_own = rows[i]
        structured = np.asarray(
            _structured_features(post, REFERENCE_FEATURE_NAMES), dtype=np.float32
        )
        feature_rows.append(np.concatenate([emb, structured]))
        labels.append(zlabels[i])
        weights.append(own_weight if is_own else 1.0)
        ids.append(row_id)

    if not feature_rows:
        return None

    own_n = sum(1 for i in kept if rows[i][4])
    logger.info(
        "Reference training set: %d rows (%d own, %d external) across %d accounts",
        len(feature_rows),
        own_n,
        len(feature_rows) - own_n,
        sum(1 for idxs in by_account.values() if any(i in zlabels for i in idxs)),
    )

    X = np.vstack(feature_rows).astype(np.float32)
    y = np.asarray(labels, dtype=np.float32)
    return TrainingData(
        X=X,
        y=y,
        ids=ids,
        feature_dim=X.shape[1],
        sample_weight=np.asarray(weights, dtype=np.float32),
        label_kind="zscore",
        structured_features=REFERENCE_FEATURE_NAMES,
    )
