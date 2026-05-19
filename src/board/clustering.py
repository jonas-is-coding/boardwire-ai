from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import Logger

import numpy as np

from src.models import FeedItem

DEFAULT_SIMILARITY_THRESHOLD = 0.88
MIN_TEXT_LEN_FOR_CLUSTERING = 25
CENTROID_TIGHTEN = 0.04  # candidate must be within (threshold - tighten) of cluster centroid too
TIER_WEIGHTS = {1: 3.0, 2: 2.0, 3: 1.0}
RECENCY_HALF_LIFE_HOURS = 48.0


@dataclass(slots=True)
class Cluster:
    cluster_id: int
    items: list[FeedItem]
    story_score: float = 0.0
    representative: FeedItem | None = None
    contributions: list[float] = field(default_factory=list)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return matrix / norms


def _centroid_clustering(
    vectors: np.ndarray,
    threshold: float,
    centroid_threshold: float,
) -> list[int]:
    """Single-pass centroid-bounded clustering.

    Iterates items in input order; assigns each to the existing cluster whose
    centroid has cosine similarity above centroid_threshold AND whose nearest
    member is above threshold. Otherwise starts a new cluster.

    This prevents single-linkage chaining: a new item must be similar BOTH to
    a member and to the cluster's overall meaning.
    """
    n = vectors.shape[0]
    if n == 0:
        return []

    centroids: list[np.ndarray] = []
    members: list[list[int]] = []
    member_matrices: list[np.ndarray] = []
    assignment = [0] * n

    for idx in range(n):
        v = vectors[idx]
        best_cluster = -1
        best_score = -1.0

        for cid, centroid in enumerate(centroids):
            centroid_sim = float(np.dot(centroid, v))
            if centroid_sim < centroid_threshold:
                continue
            # Need at least one member above threshold (member-level proximity)
            member_sims = member_matrices[cid] @ v
            max_member = float(np.max(member_sims))
            if max_member < threshold:
                continue
            combined = 0.5 * centroid_sim + 0.5 * max_member
            if combined > best_score:
                best_score = combined
                best_cluster = cid

        if best_cluster >= 0:
            members[best_cluster].append(idx)
            member_matrices[best_cluster] = np.vstack([member_matrices[best_cluster], v[np.newaxis, :]])
            new_centroid = member_matrices[best_cluster].mean(axis=0)
            norm = np.linalg.norm(new_centroid)
            if norm > 0:
                new_centroid = new_centroid / norm
            centroids[best_cluster] = new_centroid
            assignment[idx] = best_cluster
        else:
            centroids.append(v.copy())
            members.append([idx])
            member_matrices.append(v[np.newaxis, :].copy())
            assignment[idx] = len(centroids) - 1

    return assignment


def _recency_decay(published_at: datetime, now: datetime) -> float:
    delta_hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
    return math.exp(-delta_hours / RECENCY_HALF_LIFE_HOURS)


def _item_contribution(item: FeedItem, now: datetime) -> float:
    tier_weight = TIER_WEIGHTS.get(item.source_tier, 1.0)
    recency = _recency_decay(item.published_at, now)
    engagement = math.log1p(max(0.0, float(item.engagement_score)))
    return tier_weight * recency * (1.0 + 0.5 * engagement)


def _score_cluster(items: list[FeedItem], now: datetime) -> tuple[float, list[float]]:
    contributions = [_item_contribution(item, now) for item in items]
    if not contributions:
        return 0.0, contributions
    base = sum(contributions)
    size_bonus = 1.0 + 0.3 * math.log1p(len(items) - 1)
    unique_sources = {item.source for item in items}
    diversity_bonus = 1.0 + 0.2 * math.log1p(len(unique_sources) - 1)
    return base * size_bonus * diversity_bonus, contributions


def _text_signal_length(item: FeedItem) -> int:
    base = (item.title or "") + " " + (item.summary or "")
    return len(base.strip())


def cluster_items(
    items: list[FeedItem],
    embeddings: dict[str, np.ndarray],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    logger: Logger | None = None,
    now: datetime | None = None,
) -> list[Cluster]:
    if not items:
        return []

    clusterable: list[FeedItem] = []
    clusterable_vecs: list[np.ndarray] = []
    singletons: list[FeedItem] = []

    for item in items:
        vec = embeddings.get(item.link)
        if vec is None:
            continue
        if _text_signal_length(item) < MIN_TEXT_LEN_FOR_CLUSTERING:
            singletons.append(item)
            continue
        clusterable.append(item)
        clusterable_vecs.append(vec)

    if not clusterable and not singletons:
        if logger:
            logger.warning("No usable embeddings found; falling back to singleton clusters")
        return [Cluster(cluster_id=idx, items=[item]) for idx, item in enumerate(items)]

    grouped: dict[int, list[FeedItem]] = {}

    if clusterable:
        matrix = np.vstack(clusterable_vecs).astype(np.float32)
        matrix = _normalize(matrix)
        centroid_threshold = max(0.0, threshold - CENTROID_TIGHTEN)
        cluster_ids = _centroid_clustering(matrix, threshold, centroid_threshold)
        for cid, item in zip(cluster_ids, clusterable):
            grouped.setdefault(cid, []).append(item)

    next_id = max(grouped.keys(), default=-1) + 1
    for item in singletons:
        grouped[next_id] = [item]
        next_id += 1

    now_ts = now or datetime.now(tz=timezone.utc)
    clusters: list[Cluster] = []
    for cid, members in grouped.items():
        score, contributions = _score_cluster(members, now_ts)
        ranked = sorted(
            zip(members, contributions),
            key=lambda pair: (
                -TIER_WEIGHTS.get(pair[0].source_tier, 1.0),
                -_recency_decay(pair[0].published_at, now_ts),
                -pair[1],
            ),
        )
        representative = ranked[0][0] if ranked else None
        clusters.append(
            Cluster(
                cluster_id=cid,
                items=members,
                story_score=score,
                representative=representative,
                contributions=contributions,
            )
        )

    clusters.sort(key=lambda c: c.story_score, reverse=True)
    if logger:
        multi = sum(1 for c in clusters if len(c.items) > 1)
        logger.info(
            "Clustering: %d items (%d clusterable, %d short) -> %d clusters (%d multi-item)",
            len(clusterable) + len(singletons),
            len(clusterable),
            len(singletons),
            len(clusters),
            multi,
        )
    return clusters
