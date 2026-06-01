"""The news desk: turn clusters into prioritised story leads.

This wraps the existing clustering (cross-source grouping) and adds the
editorial layer a real desk provides: assign each story to a *beat*, propose a
working *angle*, and rank by priority. The output (``StoryLead``) is what a
reporter then researches in depth.
"""

from __future__ import annotations

import hashlib

from src.clustering import NewsCluster, cluster_feed_items, select_top_clusters
from src.models import FeedItem, StoryLead

# Beat → ordered keyword signals. First match wins, so order matters
# (specific before generic).
_BEAT_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("agents", ("agent", "agentic", "mcp", "tool use", "claude code", "autonomous", "orchestrat")),
    ("models", ("model weights", "open weights", "release", "gpt", "claude", "gemini", "llama", "mistral", "checkpoint")),
    ("open_source", ("open-source", "open source", "github", "repo", "apache", "mit license", "weights")),
    ("infra", ("inference", "gpu", "cuda", "serving", "vllm", "latency", "throughput", "quantiz", "kernel")),
    ("research", ("benchmark", "paper", "arxiv", "sota", "evaluation", "dataset", "fine-tune", "training")),
    ("tooling", ("sdk", "cli", "api", "framework", "library", "plugin", "integration")),
    ("business", ("funding", "raise", "acquisition", "partnership", "revenue", "ipo", "valuation")),
]


def classify_beat(text: str) -> str:
    """Assign a beat from the story's text. Falls back to 'general'."""

    lowered = (text or "").lower()
    for beat, signals in _BEAT_SIGNALS:
        if any(sig in lowered for sig in signals):
            return beat
    return "general"


def _lead_id(main_link: str, cluster_id: str) -> str:
    digest = hashlib.sha1(f"{cluster_id}|{main_link}".encode("utf-8")).hexdigest()[:12]
    return f"lead_{digest}"


def _angle_hypothesis(cluster: NewsCluster, beat: str) -> str:
    terms = ", ".join(cluster.common_terms[:4]) if cluster.common_terms else ""
    if cluster.source_count >= 2:
        base = f"{cluster.source_count} sources converging on {beat}"
    else:
        base = f"single-source {beat} story"
    return f"{base}" + (f" ({terms})" if terms else "")


def lead_from_cluster(cluster: NewsCluster, storyline=None) -> StoryLead:
    """Build a StoryLead from a NewsCluster (pure; unit-testable)."""

    text = f"{cluster.main_item.title} {cluster.cluster_summary} {' '.join(cluster.common_terms)}"
    beat = classify_beat(text)
    member_links = [m.link for m in cluster.items]
    return StoryLead(
        id=_lead_id(cluster.main_item.link, cluster.id),
        headline=cluster.main_item.title,
        beat=beat,
        angle_hypothesis=_angle_hypothesis(cluster, beat),
        priority=int(cluster.cluster_score),
        main_link=cluster.main_item.link,
        member_links=member_links,
        sources=list(cluster.sources),
        common_terms=list(cluster.common_terms),
        engagement_score=float(cluster.total_engagement_score),
        source_tier=int(cluster.main_item.source_tier),
        storyline_id=getattr(storyline, "id", None) if storyline else None,
        is_followup=storyline is not None,
    )


def select_story_leads(
    items: list[FeedItem],
    *,
    max_stories: int,
    logger=None,
    story_memory=None,
) -> list[StoryLead]:
    """Cluster items and return the top story leads for the reporter."""

    if not items:
        return []
    clusters = cluster_feed_items(items, logger=logger)
    if not clusters:
        return []
    selected = select_top_clusters(clusters, top_k=max(1, max_stories), logger=logger)

    leads: list[StoryLead] = []
    for cluster in selected[:max_stories]:
        storyline = None
        if story_memory is not None:
            storyline = story_memory.match(cluster.common_terms, classify_beat(cluster.main_item.title))
        leads.append(lead_from_cluster(cluster, storyline=storyline))
    if logger:
        logger.info("News desk selected %d leads from %d clusters", len(leads), len(clusters))
    return leads
