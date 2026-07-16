from __future__ import annotations

from src.quality.gates import (
    check_engagement_metadata_leak,
    check_midword_truncation,
    check_ungrounded_fact,
    validate_composed_post,
)


# --- engagement-metadata leak (HN dumps) -----------------------------------

def test_hn_points_and_comments_blocked() -> None:
    assert check_engagement_metadata_leak("Recall provides storage with 58 comments and 77 points on HN.") is not None
    assert check_engagement_metadata_leak("Migration guide has 58 comments and 85 points on HackerNews.") is not None
    assert check_engagement_metadata_leak("Adds MCP support with 104 points and 35 comm") is not None


def test_truncated_comm_fragment_blocked() -> None:
    assert check_engagement_metadata_leak("...isolation with 104 points and 35 comm") is not None
    assert check_engagement_metadata_leak("GLM 5.2 wins, with 57 points and 20 comments on") is not None


def test_github_star_counts_allowed() -> None:
    # Intentional star counts must NOT be blocked (Task 2.1).
    assert check_engagement_metadata_leak("Agentmemory ships persistent state with +607 stars today.") is None
    assert check_engagement_metadata_leak("Codegraph trends with +1121 stars on GitHub.") is None


def test_clean_copy_passes_engagement_check() -> None:
    assert check_engagement_metadata_leak("Mistral open-sources a 70B model under Apache 2.0.") is None
    assert check_engagement_metadata_leak("Benchmark shows 40% faster inference.") is None


# --- mid-word truncation guard ---------------------------------------------

def test_midword_truncation_flagged() -> None:
    assert check_midword_truncation("Claude Code adds warnings from Anthrop", has_link=False) is not None
    assert check_midword_truncation("Recall provides storage with 35 comm", has_link=False) is not None


def test_clean_endings_pass() -> None:
    assert check_midword_truncation("A complete sentence ends here.", has_link=False) is None
    assert check_midword_truncation("Is this the future of agents?", has_link=False) is None
    assert check_midword_truncation("A shortened fact line…", has_link=False) is None


def test_hashtag_line_is_valid_ending() -> None:
    body = "Hook line here.\n\nA supporting fact line.\n\n#AI #MCP #DevTools"
    assert check_midword_truncation(body, has_link=True) is None


def test_url_ending_is_valid() -> None:
    assert check_midword_truncation("See it here https://example.com/x", has_link=False) is None


# --- groundedness of the fact line -----------------------------------------

def test_ungrounded_turns_into_template_blocked() -> None:
    # The infamous false claim: source never said "recall" -> "executable code".
    reason = check_ungrounded_fact(
        "Openinterpreter turns recall into executable code.",
        source_title="Open Interpreter adds a plugin system",
        source_summary="Open Interpreter now supports third-party plugins for tool use.",
    )
    assert reason is not None
    assert "turns" in reason.lower()


def test_turns_into_allowed_when_both_nouns_in_source() -> None:
    assert (
        check_ungrounded_fact(
            "Recall turns memory into persistent state.",
            source_title="Recall adds persistent memory",
            source_summary="Recall stores memory as persistent state for agents.",
        )
        is None
    )


def test_fact_with_number_is_grounded() -> None:
    assert (
        check_ungrounded_fact(
            "Cuts inference cost 40% on long contexts.",
            source_title="vLLM speedup",
            source_summary="Long-context inference is now cheaper.",
        )
        is None
    )


def test_fact_with_license_is_grounded() -> None:
    assert (
        check_ungrounded_fact(
            "Released under Apache license for anyone to run.",
            source_title="New model",
            source_summary="A permissive release.",
        )
        is None
    )


def test_fact_with_source_traceable_token_is_grounded() -> None:
    assert (
        check_ungrounded_fact(
            "Agentmemory ships persistent state for coding agents.",
            source_title="Agentmemory release",
            source_summary="Agentmemory provides persistent state.",
        )
        is None
    )


def test_ungrounded_abstraction_blocked() -> None:
    reason = check_ungrounded_fact(
        "This changes how everyone builds software forever.",
        source_title="Small CLI tool released",
        source_summary="A minor utility for formatting logs.",
    )
    assert reason is not None


# --- orchestrator ----------------------------------------------------------

def test_validate_composed_post_aggregates_reasons() -> None:
    reasons = validate_composed_post(
        "Recall stores data with 58 comments and 77 points on HN with 90 score",
        fact_line="Recall stores data",
        source_title="Recall",
        source_summary="Recall stores data locally",
        has_link=False,
    )
    # Should catch both the internal-score leak and the HN engagement dump.
    assert len(reasons) >= 2


def test_validate_composed_post_clean_passes() -> None:
    body = "Recall ships local memory.\n\nApache 2.0, runs fully offline.\n\n#AI #LocalLLM"
    reasons = validate_composed_post(
        body,
        fact_line="Apache 2.0, runs fully offline.",
        source_title="Recall adds local memory",
        source_summary="Recall provides fully-local storage under Apache 2.0.",
        has_link=True,
    )
    assert reasons == []
