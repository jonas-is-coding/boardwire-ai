from datetime import datetime, timezone

from src.clustering import cluster_feed_items
from src.models import FeedItem


def _item(source: str, title: str, link: str, summary: str = "") -> FeedItem:
    return FeedItem(
        source=source,
        title=title,
        link=link,
        summary=summary,
        published_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        source_tier=2,
        engagement_score=100.0,
    )


def _cluster_id_by_link(clusters, link: str) -> str:
    for cluster in clusters:
        if any(item.link == link for item in cluster.items):
            return cluster.id
    raise AssertionError(f"No cluster found for link: {link}")


def test_release_same_version_different_projects_do_not_cluster_together() -> None:
    items = [
        _item(
            source="LangChain Releases",
            title="langchain-ai/langchain v0.30.0-rc21",
            link="https://github.com/langchain-ai/langchain/releases/tag/v0.30.0-rc21",
            summary="Release v0.30.0-rc21",
        ),
        _item(
            source="Ollama Releases",
            title="ollama/ollama v0.30.0-rc21",
            link="https://github.com/ollama/ollama/releases/tag/v0.30.0-rc21",
            summary="Release v0.30.0-rc21",
        ),
        _item(
            source="vLLM Releases",
            title="vllm-project/vllm v0.30.0-rc21",
            link="https://github.com/vllm-project/vllm/releases/tag/v0.30.0-rc21",
            summary="Release v0.30.0-rc21",
        ),
    ]

    clusters = cluster_feed_items(items)

    langchain_cluster = _cluster_id_by_link(clusters, items[0].link)
    ollama_cluster = _cluster_id_by_link(clusters, items[1].link)
    vllm_cluster = _cluster_id_by_link(clusters, items[2].link)

    assert langchain_cluster != ollama_cluster
    assert langchain_cluster != vllm_cluster
    assert ollama_cluster != vllm_cluster


def test_same_owner_repo_items_cluster_together() -> None:
    items = [
        _item(
            source="LangChain Releases",
            title="langchain-ai/langchain v0.30.0-rc21",
            link="https://github.com/langchain-ai/langchain/releases/tag/v0.30.0-rc21",
            summary="Release v0.30.0-rc21",
        ),
        _item(
            source="GitHub",
            title="langchain-ai/langchain v0.30.0-rc22",
            link="https://github.com/langchain-ai/langchain/releases/tag/v0.30.0-rc22",
            summary="Release v0.30.0-rc22",
        ),
    ]

    clusters = cluster_feed_items(items)

    assert len(clusters) == 1
    assert len(clusters[0].items) == 2
