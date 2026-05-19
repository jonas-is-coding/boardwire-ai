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


def test_langchain_package_and_vllm_release_do_not_cluster() -> None:
    items = [
        _item(
            source="Python Packages",
            title="langchain==1.3.1",
            link="https://pypi.org/project/langchain/1.3.1/",
            summary="LangChain package release 1.3.1",
        ),
        _item(
            source="vLLM Releases",
            title="vllm-project/vllm v1.3.1",
            link="https://github.com/vllm-project/vllm/releases/tag/v1.3.1",
            summary="Release v1.3.1",
        ),
    ]

    clusters = cluster_feed_items(items)
    assert len(clusters) == 2


def test_anthropic_python_sdk_release_clusters_with_same_project() -> None:
    items = [
        _item(
            source="Anthropic SDK Releases",
            title="Anthropic Python SDK v0.101.0",
            link="https://github.com/anthropics/anthropic-sdk-python/releases/tag/v0.101.0",
            summary="Release v0.101.0",
        ),
        _item(
            source="GitHub",
            title="anthropics/anthropic-sdk-python v0.101.0",
            link="https://github.com/anthropics/anthropic-sdk-python/releases/tag/v0.101.0",
            summary="Anthropic SDK release v0.101.0",
        ),
    ]

    clusters = cluster_feed_items(items)
    assert len(clusters) == 1
    assert len(clusters[0].items) == 2
