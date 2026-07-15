from __future__ import annotations

from src.hashtags import HashtagConfig, load_hashtag_config, select_hashtags

_CONFIG = HashtagConfig(
    broad=["#AI", "#OpenSource", "#LLM", "#TechNews", "#MachineLearning"],
    specific={
        "claude_code": ["#ClaudeCode", "#Anthropic"],
        "mcp": ["#MCP"],
        "ollama_local": ["#Ollama", "#LocalLLM"],
        "models_weights": ["#OpenWeights", "#HuggingFace"],
        "agents": ["#AIAgents"],
        "security": ["#InfoSec"],
        "devtools": ["#DevTools"],
    },
    max_per_post=3,
)


def test_loads_repo_config() -> None:
    config = load_hashtag_config()
    assert "#AI" in config.broad
    assert config.specific["mcp"] == ["#MCP"]
    assert config.max_per_post == 3


def test_always_one_broad_plus_specific() -> None:
    tags = select_hashtags(
        "Claude Code v3 ships MCP sandboxing",
        summary="Anthropic adds sandbox support",
        source="Anthropic Releases",
        config=_CONFIG,
    )
    assert 2 <= len(tags) <= 3
    broad_set = {t.lower() for t in _CONFIG.broad}
    assert sum(1 for t in tags if t.lower() in broad_set) >= 1
    assert tags[0].lower() in broad_set
    assert "#ClaudeCode" in tags


def test_deterministic_same_inputs_same_tags() -> None:
    args = dict(title="Ollama runs local LLM inference", summary="", source="HN", config=_CONFIG)
    assert select_hashtags(**args) == select_hashtags(**args)


def test_llm_candidates_validated_against_config() -> None:
    tags = select_hashtags(
        "Some vendor thing happened",
        summary="a story with no obvious category keywords in it",
        source="Blog",
        llm_candidates=["#Mistral7B", "#InventedTag", "#InfoSec"],
        config=_CONFIG,
    )
    # Invented / non-config tags are dropped; validated candidate survives.
    assert "#Mistral7B" not in tags
    assert "#InventedTag" not in tags
    assert "#InfoSec" in tags


def test_security_item_gets_infosec() -> None:
    tags = select_hashtags(
        "Cursor 0day exposes dev repos to remote execution",
        summary="RCE vulnerability, data exfiltration",
        source="Mindgard",
        config=_CONFIG,
    )
    assert "#InfoSec" in tags
    assert len(tags) <= 3


def test_fallback_when_nothing_matches() -> None:
    tags = select_hashtags("Quarterly business outlook", summary="", source="Biz", config=_CONFIG)
    # Still at least two tags so custom feeds can pick the post up.
    assert len(tags) >= 2
    assert len(set(t.lower() for t in tags)) == len(tags)


def test_max_per_post_respected() -> None:
    tags = select_hashtags(
        "Claude Code MCP agent runs Ollama locally with open weights CLI security",
        summary="everything matches",
        source="GitHub",
        config=_CONFIG,
    )
    assert len(tags) <= _CONFIG.max_per_post
