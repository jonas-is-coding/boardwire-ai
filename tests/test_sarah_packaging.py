from __future__ import annotations

import logging

from src.notifications import persona_voice as voice


def _valid_json() -> str:
    return (
        '{"title": "Agent memory becomes infrastructure.", '
        '"subtitle": "Agentmemory ships a 4-tier pipeline with MCP support.", '
        '"description": "Runs fully local, zero external API calls.", '
        '"hashtags": ["#AI", "#AIAgents"], '
        '"question": "", "card_stat": "607", "card_claim": "Memory becomes a shared layer", '
        '"card_context": "MIT license"}'
    )


def _kwargs(**overrides) -> dict:
    base = dict(
        title="Agent memory becomes infrastructure",
        source="GitHub Trending",
        reason="clear builder utility",
        score=80,
        claire_note="",
        chloe_note="",
        post_text="",
        summary="Agentmemory persists state across sessions",
    )
    base.update(overrides)
    return base


def test_sarah_max_output_tokens_has_headroom_for_8_field_schema() -> None:
    # Historically 420, sized for a 4-field schema (title/subtitle/description/
    # hashtags). The schema now has 8 fields (+question, card_stat, card_claim,
    # card_context); 420 silently truncated responses mid-JSON with no error.
    assert voice._SARAH_MAX_OUTPUT_TOKENS >= 700


def test_provider_chain_called_with_expanded_token_budget(monkeypatch) -> None:
    captured = {}

    def fake_chain(system, user, max_output_tokens=420):
        captured["max_output_tokens"] = max_output_tokens
        return _valid_json()

    monkeypatch.setattr(voice.sarah_generation, "generate_with_provider_chain", fake_chain)
    pkg = voice.sarah_build_publish_package(**_kwargs())

    assert pkg is not None
    assert captured["max_output_tokens"] == voice._SARAH_MAX_OUTPUT_TOKENS
    assert captured["max_output_tokens"] >= 700


def test_truncated_json_returns_none_and_logs_diagnostic(monkeypatch, caplog) -> None:
    # A response cut off mid-JSON (the exact failure mode of a too-small
    # max_output_tokens) must fail gracefully with a diagnosable log line,
    # not silently disappear.
    truncated = '{"title": "Agent memory becomes infrastructure.", "subtitle": "Agentmemory ships a 4-ti'
    monkeypatch.setattr(voice.sarah_generation, "generate_with_provider_chain", lambda *a, **k: truncated)

    with caplog.at_level(logging.WARNING, logger="boardwire.persona_voice"):
        pkg = voice.sarah_build_publish_package(**_kwargs())

    assert pkg is None
    assert any("unparseable JSON" in r.message for r in caplog.records)


def test_no_provider_content_logs_diagnostic(monkeypatch, caplog) -> None:
    monkeypatch.setattr(voice.sarah_generation, "generate_with_provider_chain", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="boardwire.persona_voice"):
        pkg = voice.sarah_build_publish_package(**_kwargs())

    assert pkg is None
    assert any("no raw content" in r.message for r in caplog.records)


def test_missing_required_field_logs_diagnostic(monkeypatch, caplog) -> None:
    # Valid JSON, but missing a required field (subtitle) — must be
    # distinguishable in logs from "no content" / "unparseable JSON".
    incomplete = '{"title": "A headline.", "subtitle": "", "description": "d", "hashtags": ["#AI", "#MCP"]}'
    monkeypatch.setattr(voice.sarah_generation, "generate_with_provider_chain", lambda *a, **k: incomplete)

    with caplog.at_level(logging.WARNING, logger="boardwire.persona_voice"):
        pkg = voice.sarah_build_publish_package(**_kwargs())

    assert pkg is None
    assert any("required fields missing" in r.message for r in caplog.records)


def test_valid_package_still_works(monkeypatch) -> None:
    monkeypatch.setattr(voice.sarah_generation, "generate_with_provider_chain", lambda *a, **k: _valid_json())
    pkg = voice.sarah_build_publish_package(**_kwargs())
    assert pkg is not None
    assert pkg["title"].startswith("Agent memory")
    assert 2 <= len(pkg["hashtags"]) <= 3
