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


def _structured_features(post: dict[str, Any]) -> list[float]:
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

    return [
        score,
        float(len(text)),
        hour,
        1.0 if any(k in lowered for k in _RELEASE_KEYWORDS) else 0.0,
        1.0 if post.get("source_link") else 0.0,
    ]


def _post_to_feed_item(post: dict[str, Any]) -> FeedItem:
    from datetime import datetime

    return FeedItem(
        source=post.get("platform", "bluesky"),
        title=post.get("source_title") or post.get("post", "")[:120],
        link=post.get("source_link") or f"id:{post.get('id', '')}",
        summary=post.get("post", ""),
        published_at=datetime.now(timezone.utc),
    )


def build_training_data(
    published: list[dict[str, Any]],
    store: dict[str, Any],
    logger: Logger,
    min_age_hours: float = 24.0,
) -> TrainingData | None:
    """Assemble (features, label) rows for posts with mature engagement data."""
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
