from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.models import FeedItem

_CLUSTER_THRESHOLD = 0.42
_STRONG_TERMS = {
    "release", "released", "launch", "launched", "ships", "shipping", "open-source",
    "opensource", "api", "sdk", "cli", "weights", "benchmark", "benchmarks",
}
_WEAK_TERMS = {
    "opinion", "funding", "partnership", "rumor", "rumour", "might", "could", "someday",
}
_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "about", "after", "before",
    "your", "their", "have", "has", "was", "were", "will", "also", "more", "than", "into",
    "news", "ai", "new", "over", "under", "into", "using", "build", "builder", "today",
}


@dataclass(slots=True)
class NewsCluster:
    id: str
    items: list[FeedItem]
    main_item: FeedItem
    sources: list[str]
    source_count: int
    total_engagement_score: float
    best_source_tier: int
    cluster_score: int
    common_terms: list[str]
    cluster_summary: str


def normalize_text(text: str) -> str:
    cleaned = re.sub(r"https?://\S+", " ", text or "")
    cleaned = cleaned.lower()
    cleaned = re.sub(r"[^a-z0-9+#./ -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _url_keywords(link: str) -> str:
    try:
        parsed = urlparse(link or "")
        base = f"{parsed.netloc} {parsed.path}".replace("/", " ").replace("-", " ").replace("_", " ")
        return normalize_text(base)
    except Exception:
        return ""


def build_item_text(item: FeedItem) -> str:
    title = normalize_text(item.title)
    summary = normalize_text(item.summary)
    source = normalize_text(item.source)
    url_terms = _url_keywords(item.link)
    return f"{title} {summary} {source} {url_terms}".strip()


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_text(text).split() if len(t) >= 3 and t not in _STOPWORDS}


def _keyword_overlap(a: FeedItem, b: FeedItem) -> bool:
    title_a = _tokens(a.title)
    title_b = _tokens(b.title)
    if not title_a or not title_b:
        return False
    inter = title_a & title_b
    if len(inter) >= 3:
        return True

    url_a = _tokens(_url_keywords(a.link))
    url_b = _tokens(_url_keywords(b.link))
    if len(url_a & url_b) >= 2:
        return True

    return False


def _choose_main_item(items: list[FeedItem]) -> FeedItem:
    return sorted(
        items,
        key=lambda it: (
            int(it.source_tier),
            -float(it.engagement_score),
            -it.published_at.replace(tzinfo=timezone.utc).timestamp()
            if it.published_at.tzinfo is None
            else -it.published_at.astimezone(timezone.utc).timestamp(),
        ),
    )[0]


def _common_terms(items: Iterable[FeedItem], limit: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    for item in items:
        counter.update(_tokens(f"{item.title} {item.summary}"))
    common = [term for term, _ in counter.most_common(limit)]
    return common


def _cluster_summary(items: list[FeedItem], common_terms: list[str], source_count: int, engagement: float) -> str:
    headline = items[0].title if items else ""
    terms = ", ".join(common_terms[:4]) if common_terms else ""
    base = f"{source_count} sources, engagement {int(engagement)}"
    if terms:
        return f"{base}. Common terms: {terms}. Lead: {headline[:120]}"
    return f"{base}. Lead: {headline[:120]}"


def score_cluster(cluster: NewsCluster) -> int:
    score = 0
    if cluster.source_count >= 3:
        score += 30
    elif cluster.source_count == 2:
        score += 20

    if cluster.best_source_tier == 1:
        score += 25
    elif cluster.best_source_tier == 2:
        score += 15

    if cluster.total_engagement_score >= 500:
        score += 20
    elif cluster.total_engagement_score >= 100:
        score += 10

    haystack = normalize_text(" ".join(f"{it.title} {it.summary}" for it in cluster.items))

    if any(term in haystack for term in _STRONG_TERMS):
        score += 20
    if any(term in haystack for term in _WEAK_TERMS):
        score -= 30

    return score


def cluster_feed_items(items: list[FeedItem]) -> list[NewsCluster]:
    if not items:
        return []
    if len(items) == 1:
        single = items[0]
        common_terms = _common_terms([single])
        cluster = NewsCluster(
            id="c1",
            items=[single],
            main_item=single,
            sources=[single.source],
            source_count=1,
            total_engagement_score=float(single.engagement_score),
            best_source_tier=int(single.source_tier),
            cluster_score=0,
            common_terms=common_terms,
            cluster_summary=_cluster_summary([single], common_terms, 1, float(single.engagement_score)),
        )
        cluster.cluster_score = score_cluster(cluster)
        return [cluster]

    docs = [build_item_text(item) for item in items]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=6000)
    tfidf = vectorizer.fit_transform(docs)
    sim = cosine_similarity(tfidf)

    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    n = len(items)
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] > _CLUSTER_THRESHOLD or _keyword_overlap(items[i], items[j]):
                union(i, j)

    grouped: dict[int, list[FeedItem]] = {}
    for idx, item in enumerate(items):
        root = find(idx)
        grouped.setdefault(root, []).append(item)

    clusters: list[NewsCluster] = []
    for cidx, grouped_items in enumerate(grouped.values(), start=1):
        main_item = _choose_main_item(grouped_items)
        sources = sorted({it.source for it in grouped_items})
        source_count = len(sources)
        engagement = float(sum(max(0.0, float(it.engagement_score)) for it in grouped_items))
        best_tier = min(int(it.source_tier) for it in grouped_items)
        common_terms = _common_terms(grouped_items)
        cluster = NewsCluster(
            id=f"c{cidx}",
            items=grouped_items,
            main_item=main_item,
            sources=sources,
            source_count=source_count,
            total_engagement_score=engagement,
            best_source_tier=best_tier,
            cluster_score=0,
            common_terms=common_terms,
            cluster_summary=_cluster_summary(grouped_items, common_terms, source_count, engagement),
        )
        cluster.cluster_score = score_cluster(cluster)
        clusters.append(cluster)

    return clusters


def select_top_clusters(clusters: list[NewsCluster], top_k: int) -> list[NewsCluster]:
    if top_k <= 0:
        return []
    ranked = sorted(
        clusters,
        key=lambda c: (
            -c.cluster_score,
            -c.source_count,
            -c.total_engagement_score,
            c.best_source_tier,
            -c.main_item.published_at.astimezone(timezone.utc).timestamp()
            if c.main_item.published_at.tzinfo
            else -c.main_item.published_at.replace(tzinfo=timezone.utc).timestamp(),
        ),
    )
    return ranked[:top_k]
