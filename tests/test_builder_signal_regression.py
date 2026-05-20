from datetime import datetime, timezone

from src.main import is_meaningful_release, score_newsworthiness
from src.models import FeedItem
from src.quality.gates import QualityConfig, check_quality


def _item(
    *,
    source: str,
    title: str,
    link: str,
    summary: str,
    source_tier: int = 1,
    engagement_score: float = 0.0,
) -> FeedItem:
    return FeedItem(
        source=source,
        title=title,
        link=link,
        summary=summary,
        published_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        source_tier=source_tier,
        engagement_score=engagement_score,
    )


def test_patch_release_without_concrete_feature_does_not_score_high() -> None:
    item = _item(
        source="Claude Code Releases",
        title="Anthropic ships Claude Code v2.1.141",
        link="https://github.com/anthropics/claude-code/releases/tag/v2.1.141",
        summary="Claims improved performance and minor fixes.",
    )

    assert not is_meaningful_release(item)
    assert score_newsworthiness(item) < 60


def test_patch_release_with_official_plugin_ecosystem_scores_high() -> None:
    item = _item(
        source="Claude Code Releases",
        title="Anthropic ships Claude Code v2.1.141",
        link="https://github.com/anthropics/claude-code/releases/tag/v2.1.141",
        summary="Adds an official plugin ecosystem for Claude Code extensions.",
    )

    assert is_meaningful_release(item)
    assert score_newsworthiness(item) >= 60


def test_github_trending_cli_repo_with_1000_stars_scores_high() -> None:
    item = _item(
        source="GitHub Trending",
        title="builder-labs/agent-cli — CLI coding assistant for local-first workflows",
        link="https://github.com/builder-labs/agent-cli",
        summary="Trending on GitHub today: +1000 stars. CLI devtool for coding assistants.",
        source_tier=2,
        engagement_score=1000.0,
    )

    assert score_newsworthiness(item) >= 60


def test_boring_generated_release_post_is_rejected() -> None:
    config = QualityConfig(
        max_post_length=280,
        min_llm_score=0,
        min_rule_score=0,
        max_defer_count=3,
        duplicate_lookback_hours=168,
        fixture_duplicate_lookback_hours=1,
        banned_phrases=[],
        generic_phrases=[],
    )

    result = check_quality(
        post="Claude Code ships version v2.1.141 and claims improved performance.",
        source_link="https://github.com/anthropics/claude-code/releases/tag/v2.1.141",
        score=80,
        is_llm_mode=True,
        config=config,
        history_posts=[],
        context="review",
    )

    assert not result.passed
    assert any("Boring release" in reason for reason in result.reasons)
