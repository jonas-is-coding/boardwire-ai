from src.llm import prompts


def test_default_uses_builder_prompts(monkeypatch):
    monkeypatch.delenv("BOARDWIRE_CONSTRUCTIVE_MODE", raising=False)
    # Config default is constructive_mode=false, so builder prompts are used.
    assert prompts.get_system_prompt() is prompts.SYSTEM_PROMPT
    assert prompts.get_ranking_system_prompt() is prompts.RANKING_SYSTEM_PROMPT


def test_constructive_mode_switches_prompts(monkeypatch):
    monkeypatch.setenv("BOARDWIRE_CONSTRUCTIVE_MODE", "true")
    assert prompts.get_system_prompt() is prompts.CONSTRUCTIVE_SYSTEM_PROMPT
    assert prompts.get_ranking_system_prompt() is prompts.CONSTRUCTIVE_RANKING_SYSTEM_PROMPT
    # The constructive board carries the Integrity truth-guard role.
    assert "Integrity" in prompts.CONSTRUCTIVE_SYSTEM_PROMPT
    assert "Optimist" in prompts.CONSTRUCTIVE_SYSTEM_PROMPT


def test_constructive_off_reverts(monkeypatch):
    monkeypatch.setenv("BOARDWIRE_CONSTRUCTIVE_MODE", "false")
    assert prompts.get_system_prompt() is prompts.SYSTEM_PROMPT
