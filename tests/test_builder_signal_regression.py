import logging
from datetime import datetime, timezone

from src.board import llm_evaluator
from src.llm import gemini_budget
from src.llm.client import LLMConfig, LLMError
from src.main import _sarah_fallback_budget, is_meaningful_release, score_newsworthiness
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


def _quality_config() -> QualityConfig:
    return QualityConfig(
        max_post_length=280,
        min_llm_score=0,
        min_rule_score=0,
        max_defer_count=3,
        duplicate_lookback_hours=168,
        fixture_duplicate_lookback_hours=1,
        banned_phrases=[],
        generic_phrases=[],
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


def test_academic_research_skills_repo_scores_below_publish_threshold() -> None:
    item = _item(
        source="GitHub Trending",
        title="Imbad0202/academic-research-skills — Academic Research Skills for Claude Code",
        link="https://github.com/Imbad0202/academic-research-skills",
        summary="Trending on GitHub today: +3184 stars. research -> write -> review methodology.",
        source_tier=2,
        engagement_score=3184.0,
    )

    assert score_newsworthiness(item) < 60


def test_generic_agent_workflow_repo_does_not_get_builder_breakout() -> None:
    item = _item(
        source="GitHub Trending",
        title="example/agent-workflow-framework — Agent workflow methodology for software teams",
        link="https://github.com/example/agent-workflow-framework",
        summary="Trending on GitHub today: +900 stars. Framework and methodology for agent workflows.",
        source_tier=2,
        engagement_score=900.0,
    )

    assert score_newsworthiness(item) < 60


def test_ai_engineering_from_scratch_repo_scores_below_publish_threshold() -> None:
    item = _item(
        source="GitHub Trending",
        title="rohitg00/ai-engineering-from-scratch — Learn AI engineering from scratch",
        link="https://github.com/rohitg00/ai-engineering-from-scratch",
        summary="Trending on GitHub today: +1200 stars. Lessons and tutorial methodology.",
        source_tier=2,
        engagement_score=1200.0,
    )

    assert score_newsworthiness(item) < 60


def test_educational_repo_can_score_high_only_with_strong_artifact_and_high_engagement() -> None:
    item = _item(
        source="GitHub Trending",
        title="rohitg00/ai-engineering-from-scratch — Learn AI engineering from scratch",
        link="https://github.com/rohitg00/ai-engineering-from-scratch",
        summary="Trending on GitHub today: +1800 stars. Includes a local runtime CLI for inference experiments.",
        source_tier=2,
        engagement_score=1800.0,
    )

    assert score_newsworthiness(item) >= 60


def test_cli_repo_with_concrete_token_reduction_scores_high() -> None:
    item = _item(
        source="GitHub Trending",
        title="rtk-ai/rtk — CLI proxy that reduces LLM token usage by 60%",
        link="https://github.com/rtk-ai/rtk",
        summary="Trending on GitHub today: +667 stars. Fewer tokens on common dev commands.",
        source_tier=2,
        engagement_score=667.0,
    )

    assert score_newsworthiness(item) >= 60


def test_gemini_503_does_not_exhaust_run_budget(monkeypatch, caplog) -> None:
    class UnavailableGeminiClient:
        def __init__(self, api_key: str, model: str) -> None:
            self.api_key = api_key
            self.model = model

        def rank_candidates(self, items: list[FeedItem], top_k: int) -> list[dict]:
            raise LLMError("Gemini ranking error 503: temporarily unavailable")

    monkeypatch.setattr(gemini_budget, "_BUDGET_TOTAL", 2)
    monkeypatch.setattr(gemini_budget, "_BUDGET_USED", 0)
    monkeypatch.setattr(llm_evaluator, "GeminiClient", UnavailableGeminiClient)
    config = LLMConfig(
        provider="gemini",
        openai_model="unused",
        gemini_model="gemini-test",
        openai_api_key=None,
        gemini_api_key="test-key",
        max_items=3,
    )
    item = _item(
        source="GitHub Trending",
        title="builder-labs/agent-cli — CLI for coding agents",
        link="https://github.com/builder-labs/agent-cli",
        summary="Trending on GitHub today: +1000 stars. CLI devtool.",
        source_tier=2,
        engagement_score=1000.0,
    )

    with caplog.at_level(logging.WARNING):
        result = llm_evaluator.rank_candidates_with_llm([item], 1, config, logging.getLogger("test"))

    assert result is None
    # A transient 503 only consumes the single call's budget unit (1 of 2) and
    # falls back for this stage — it must NOT zero out the whole run budget, so
    # later stages can still attempt Gemini.
    assert gemini_budget.remaining_gemini_budget() == 1
    assert "Gemini provider temporarily unavailable; using fallback for ranking" in caplog.text


def test_boring_generated_release_post_is_rejected() -> None:
    result = check_quality(
        post="Claude Code ships version v2.1.141 and claims improved performance.",
        source_link="https://github.com/anthropics/claude-code/releases/tag/v2.1.141",
        score=80,
        is_llm_mode=True,
        config=_quality_config(),
        history_posts=[],
        context="review",
    )

    assert not result.passed
    assert any("Boring release" in reason for reason in result.reasons)


def test_sarah_style_post_without_builder_implication_is_rejected() -> None:
    result = check_quality(
        post=(
            "Agentmemory library ships persistent memory for AI coding agents.\n\n"
            "Outperforms others on real-world benchmarks with +1121 stars on GitHub."
        ),
        source_link="https://github.com/rohitg00/agentmemory",
        score=80,
        is_llm_mode=True,
        config=_quality_config(),
        history_posts=[],
        context="review",
    )

    assert not result.passed
    assert any("builder implication" in reason for reason in result.reasons)


def test_sarah_style_post_with_thesis_and_builder_implication_is_accepted() -> None:
    result = check_quality(
        post=(
            "Coding agents are getting memory as a core primitive, not a plugin.\n\n"
            "Agentmemory turns recall into infrastructure for coding-agent workflows, with +1121 GitHub stars today."
        ),
        source_link="https://github.com/rohitg00/agentmemory",
        score=80,
        is_llm_mode=True,
        config=_quality_config(),
        history_posts=[],
        context="review",
    )

    assert result.passed


def test_sarah_fallback_budget_default_allows_at_least_three_attempts(monkeypatch) -> None:
    monkeypatch.delenv("BOARDWIRE_SARAH_FALLBACK_BUDGET", raising=False)

    assert _sarah_fallback_budget(high_score_candidates=5) >= 3
