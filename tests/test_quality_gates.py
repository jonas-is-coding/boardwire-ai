from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.quality.gates import (
    QualityConfig,
    check_metadata_leak,
    check_quality,
    check_version_only_release,
    find_recent_release,
    is_version_dominant_title,
)


def _config(**overrides) -> QualityConfig:
    defaults = dict(
        max_post_length=280,
        min_llm_score=60,
        min_rule_score=5,
        max_defer_count=3,
        duplicate_lookback_hours=168,
        fixture_duplicate_lookback_hours=1,
        banned_phrases=[],
        generic_phrases=[],
    )
    defaults.update(overrides)
    return QualityConfig(**defaults)


# --- version-only block -----------------------------------------------------

def test_version_dominant_titles_detected() -> None:
    assert is_version_dominant_title("Claude Code v2.1.210") is True
    assert is_version_dominant_title("ollama v0.30.11") is True
    assert is_version_dominant_title("langchain v1.3.4") is True
    assert is_version_dominant_title("servers v2026.7.10") is True
    assert is_version_dominant_title("vLLM v0.30.11-rc2") is True


def test_headline_with_version_is_not_version_dominant() -> None:
    assert is_version_dominant_title("Claude Code v2.1.210 fixes critical subagent isolation bug") is False
    assert is_version_dominant_title("Mistral open-sources 70B model trained on 15T tokens") is False


def test_version_only_blocked_without_capability() -> None:
    reason = check_version_only_release("ollama v0.30.11", "Routine maintenance and stability fixes.")
    assert reason is not None
    assert "Version-only release" in reason


def test_version_only_allowed_with_capability_keyword() -> None:
    assert check_version_only_release("ollama v0.30.11", "Adds MCP server support and a new CLI flag.") is None
    assert check_version_only_release("Claude Code v2.1.210", "Ships plugin sandboxing.") is None


def test_version_only_allowed_with_numeric_claim() -> None:
    assert check_version_only_release("vllm v0.9.1", "Inference is 40% faster on long contexts.") is None
    assert check_version_only_release("vllm v0.9.1", "Achieves 3x throughput on H100.") is None


def test_check_quality_wires_version_gate() -> None:
    result = check_quality(
        post="Ollama ships a new release for local model developers because it matters.",
        source_link="https://github.com/ollama/ollama/releases/tag/v0.30.11",
        score=90,
        is_llm_mode=True,
        config=_config(),
        history_posts=[],
        item_title="ollama v0.30.11",
        item_summary="Routine bug fixes.",
    )
    assert result.passed is False
    assert any("Version-only release" in r for r in result.reasons)


# --- internal metadata leak -------------------------------------------------

def test_metadata_leak_score_phrase() -> None:
    assert check_metadata_leak("Claude Code fixes isolation bug, with 90 score.") is not None
    assert check_metadata_leak("Ranked 95 rank in our pipeline") is not None


def test_metadata_leak_field_names() -> None:
    assert check_metadata_leak("item source_tier is 1") is not None
    assert check_metadata_leak("engagement_score exploded") is not None


def test_metadata_leak_clean_posts_pass() -> None:
    assert check_metadata_leak("Benchmark: 90% pass rate on SWE-bench.") is None
    assert check_metadata_leak("Scores 90% on MMLU.") is None


def test_check_quality_rejects_leak() -> None:
    result = check_quality(
        post="Subagent isolation is now secure, with 90 score. Builders should update.",
        source_link="https://example.com/x",
        score=90,
        is_llm_mode=True,
        config=_config(),
        history_posts=[],
    )
    assert result.passed is False
    assert any("Internal metadata" in r for r in result.reasons)


# --- release dedupe ---------------------------------------------------------

def _release(project: str, version: str, days_ago: float) -> dict:
    published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "project": project,
        "version": version,
        "published_at": published.isoformat().replace("+00:00", "Z"),
    }


def test_release_dedupe_blocks_within_window() -> None:
    records = [_release("Ollama", "v0.30.11", days_ago=2)]
    assert find_recent_release(records, "Ollama", "v0.30.11") is not None
    # Case and v-prefix insensitive.
    assert find_recent_release(records, "ollama", "0.30.11") is not None


def test_release_dedupe_allows_after_window() -> None:
    records = [_release("Ollama", "v0.30.11", days_ago=20)]
    assert find_recent_release(records, "Ollama", "v0.30.11", window_days=14) is None


def test_release_dedupe_different_version_allowed() -> None:
    records = [_release("Ollama", "v0.30.11", days_ago=1)]
    assert find_recent_release(records, "Ollama", "v0.30.12") is None
    assert find_recent_release(records, "LangChain", "v0.30.11") is None
