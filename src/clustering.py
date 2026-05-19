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

_CLUSTER_THRESHOLD = 0.62
OVERCLUSTER_MAX_SIZE = 25
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
_GENERIC_AI_TERMS = {
    "ai", "model", "models", "llm", "llms", "agent", "agents", "open", "release",
    "new", "data", "code", "api", "benchmark", "research", "source", "open-source",
    "learn", "using", "build", "building",
}
_COMMON_TERM_EXCLUDE = _GENERIC_AI_TERMS | {
    "openai", "anthropic", "google", "how", "our", "benchmarks", "framework", "frameworks",
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
    return f"{title} {summary}".strip()


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_text(text).split() if len(t) >= 3 and t not in _STOPWORDS}


def _strong_tokens(text: str) -> set[str]:
    return {t for t in _tokens(text) if t not in _GENERIC_AI_TERMS}


def _extract_repo_id(link: str) -> tuple[str, str] | None:
    try:
        parsed = urlparse(link or "")
        host = parsed.netloc.lower()
        if "github.com" not in host:
            return None
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            return None
        owner = parts[0].lower()
        repo = parts[1].lower()
        return owner, repo
    except Exception:
        return None


def _same_project_or_repo(a: FeedItem, b: FeedItem) -> bool:
    repo_a = _extract_repo_id(a.link)
    repo_b = _extract_repo_id(b.link)
    if repo_a and repo_b:
        # Be conservative: only exact owner/repo or exact same repo name.
        return repo_a == repo_b or (repo_a[1] == repo_b[1] and repo_a[1] != "")
    return False


def _project_markers(item: FeedItem) -> set[str]:
    markers: set[str] = set()
    repo = _extract_repo_id(item.link)
    if repo:
        markers.add(f"{repo[0]}/{repo[1]}")
        markers.add(repo[1])
    text = f"{item.title} {item.summary}"
    for tok in _tokens(text):
        if tok in _GENERIC_AI_TERMS:
            continue
        # Prefer concrete identifiers over plain words.
        if any(c.isdigit() for c in tok) or "-" in tok:
            markers.add(tok)
    return markers


def _keyword_overlap(a: FeedItem, b: FeedItem) -> bool:
    if _same_project_or_repo(a, b):
        return True
    strong_inter = _strong_tokens(f"{a.title} {a.summary}") & _strong_tokens(f"{b.title} {b.summary}")
    if len(strong_inter) >= 4:
        return True
    if _project_markers(a) & _project_markers(b):
        return True
    return False


def _edge_decision(a: FeedItem, b: FeedItem, sim_score: float) -> tuple[bool, str, list[str]]:
    strong_inter = sorted(_strong_tokens(f"{a.title} {a.summary}") & _strong_tokens(f"{b.title} {b.summary}"))
    if _same_project_or_repo(a, b):
        return True, "repo_match", strong_inter[:8]
    if len(strong_inter) >= 4:
        return True, "token_overlap", strong_inter[:8]
    if _project_markers(a) & _project_markers(b):
        return True, "project_name", strong_inter[:8]
    # Cosine alone should never force a cluster; require at least the stricter overlap.
    if sim_score > _CLUSTER_THRESHOLD and len(strong_inter) >= 4:
        return True, "cosine", strong_inter[:8]
    return False, "", strong_inter[:8]


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
        counter.update(t for t in _tokens(f"{item.title} {item.summary}") if t not in _COMMON_TERM_EXCLUDE)
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
    if len(cluster.items) > OVERCLUSTER_MAX_SIZE:
        # Overcluster penalty cap to keep these out of top selections.
        return min(10, max(0, int(cluster.total_engagement_score // 200)))

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


def cluster_feed_items(items: list[FeedItem], logger=None) -> list[NewsCluster]:
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
    size = [1 for _ in items]
    edge_logs: dict[int, list[dict]] = {i: [] for i in range(len(items))}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int, edge: dict) -> None:
        ra = find(a)
        rb = find(b)
        if ra == rb:
            return
        if size[ra] + size[rb] > OVERCLUSTER_MAX_SIZE:
            if logger:
                logger.warning("Cluster union blocked: would exceed max size")
            return
        parent[rb] = ra
        size[ra] += size[rb]
        merged_logs = edge_logs.get(ra, []) + edge_logs.get(rb, [])
        merged_logs.append(edge)
        edge_logs[ra] = merged_logs[:200]
        edge_logs.pop(rb, None)

    n = len(items)
    for i in range(n):
        for j in range(i + 1, n):
            sim_score = float(sim[i, j])
            should_link, reason, shared_tokens = _edge_decision(items[i], items[j], sim_score)
            if should_link or _keyword_overlap(items[i], items[j]):
                edge = {
                    "a_title": items[i].title[:140],
                    "b_title": items[j].title[:140],
                    "sim_score": round(sim_score, 4),
                    "shared_tokens": shared_tokens,
                    "reason": reason or "keyword_overlap",
                }
                union(i, j, edge)

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

    if logger:
        for cluster in clusters:
            if len(cluster.items) > OVERCLUSTER_MAX_SIZE:
                root_idx = find(items.index(cluster.main_item))
                logger.warning("Overcluster detected: id=%s size=%d", cluster.id, len(cluster.items))
                for edge in edge_logs.get(root_idx, [])[:20]:
                    logger.warning(
                        "Overcluster edge: A=%s | B=%s | sim=%.4f | shared=%s | reason=%s",
                        edge.get("a_title", ""),
                        edge.get("b_title", ""),
                        float(edge.get("sim_score", 0.0)),
                        ",".join(edge.get("shared_tokens", [])),
                        edge.get("reason", ""),
                    )

    return clusters


def _sort_key_cluster(c: NewsCluster) -> tuple[float, float, float, int, float]:
    return (
        -c.cluster_score,
        -c.source_count,
        -c.total_engagement_score,
        c.best_source_tier,
        -c.main_item.published_at.astimezone(timezone.utc).timestamp()
        if c.main_item.published_at.tzinfo
        else -c.main_item.published_at.replace(tzinfo=timezone.utc).timestamp(),
    )


def _sort_key_item(item: FeedItem) -> tuple[int, float, float]:
    return (
        int(item.source_tier),
        -float(item.engagement_score),
        -item.published_at.astimezone(timezone.utc).timestamp()
        if item.published_at.tzinfo
        else -item.published_at.replace(tzinfo=timezone.utc).timestamp(),
    )


def select_top_clusters(clusters: list[NewsCluster], top_k: int, logger=None) -> list[NewsCluster]:
    if top_k <= 0:
        return []

    eligible: list[NewsCluster] = []
    overclustered: list[NewsCluster] = []
    for cluster in clusters:
        if len(cluster.items) > OVERCLUSTER_MAX_SIZE:
            overclustered.append(cluster)
            if logger:
                logger.info("Skipping overclustered cluster %s size=%d", cluster.id, len(cluster.items))
            continue
        eligible.append(cluster)

    ranked = sorted(eligible, key=_sort_key_cluster)
    selected = ranked[:top_k]
    if len(selected) >= top_k:
        return selected

    selected_links = {c.main_item.link for c in selected}
    fallback_items: list[FeedItem] = []
    for cluster in overclustered:
        for item in cluster.items:
            if item.link not in selected_links:
                fallback_items.append(item)
    for cluster in eligible[top_k:]:
        if cluster.main_item.link not in selected_links:
            fallback_items.append(cluster.main_item)

    fallback_items = sorted(fallback_items, key=_sort_key_item)
    next_id = len(clusters) + 1
    for item in fallback_items:
        if len(selected) >= top_k:
            break
        if item.link in selected_links:
            continue
        single = NewsCluster(
            id=f"c{next_id}",
            items=[item],
            main_item=item,
            sources=[item.source],
            source_count=1,
            total_engagement_score=float(item.engagement_score),
            best_source_tier=int(item.source_tier),
            cluster_score=0,
            common_terms=_common_terms([item]),
            cluster_summary=_cluster_summary([item], _common_terms([item]), 1, float(item.engagement_score)),
        )
        single.cluster_score = score_cluster(single)
        selected.append(single)
        selected_links.add(item.link)
        next_id += 1

    return selected
