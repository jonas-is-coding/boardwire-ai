"""Deterministic hashtag selection for custom-feed discovery on Bluesky.

Bluesky discovery happens largely through custom feeds that pick up posts by
hashtag/keyword rules. Tags therefore must (a) match feeds that actually
exist and (b) survive into the published text. This module owns (a): the LLM
may *suggest* hashtags, but the final selection is computed here in Python
from ``config/hashtags.json`` — anything not in that config is dropped.

Selection rule: always exactly 1 broad tag + 1-2 specific tags matched from
the item's title/summary/source via simple keyword mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.config import HASHTAGS_PATH
from src.storage.json_store import JsonStore

# Keyword mapping per specific category. Matched case-insensitively with word
# boundaries against "<title> <summary> <source>".
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "claude_code": ("claude code", "claude-code", "anthropic", "claude"),
    "mcp": ("mcp", "model context protocol"),
    "ollama_local": ("ollama", "local llm", "local model", "on-device", "on device", "llama.cpp", "runs locally", "local inference"),
    "models_weights": ("open weights", "open-weight", "open weight", "huggingface", "hugging face", "model weights", "quantization", "quantized", "fine-tune", "finetune"),
    "agents": ("agent", "agents", "agentic"),
    "security": ("security", "vulnerability", "cve", "0day", "0-day", "zero-day", "exploit", "rce", "infosec", "data exfiltration", "prompt injection"),
    "devtools": ("cli", "sdk", "ide", "devtool", "developer tool", "dev tool", "code review", "coding assistant", "copilot", "cursor"),
}

# Broad tag preference per signal, checked in order; first match wins so the
# choice is deterministic for a given item.
_BROAD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("#OpenSource", ("open source", "open-source", "open sources", "open-sourced", "github.com", "apache 2.0", "mit license", "open weights", "open-weight")),
    ("#LLM", ("llm", "language model", "model", "gpt", "claude", "gemini", "mistral", "llama", "weights", "inference", "token")),
    ("#MachineLearning", ("training", "dataset", "benchmark", "fine-tun", "machine learning", "neural")),
    ("#TechNews", ("release", "launch", "ships", "announce")),
)
_DEFAULT_BROAD = "#AI"


@dataclass(slots=True)
class HashtagConfig:
    broad: list[str] = field(default_factory=list)
    specific: dict[str, list[str]] = field(default_factory=dict)
    max_per_post: int = 3

    def all_tags_lower(self) -> set[str]:
        tags = {t.lower() for t in self.broad}
        for values in self.specific.values():
            tags.update(t.lower() for t in values)
        return tags


def load_hashtag_config(path: Path | None = None) -> HashtagConfig:
    raw = JsonStore.load(path or HASHTAGS_PATH, default={})
    if not isinstance(raw, dict):
        raw = {}
    broad = [str(t) for t in raw.get("broad", []) if str(t).strip()]
    specific_raw = raw.get("specific", {})
    specific: dict[str, list[str]] = {}
    if isinstance(specific_raw, dict):
        for key, values in specific_raw.items():
            if isinstance(values, list):
                specific[str(key)] = [str(t) for t in values if str(t).strip()]
    try:
        max_per_post = max(2, int(raw.get("max_per_post", 3)))
    except (TypeError, ValueError):
        max_per_post = 3
    return HashtagConfig(broad=broad, specific=specific, max_per_post=max_per_post)


def _contains_keyword(text: str, keyword: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _matched_categories(text: str) -> list[str]:
    matched: list[str] = []
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(_contains_keyword(text, k) for k in keywords):
            matched.append(category)
    return matched


def _pick_broad(text: str, config: HashtagConfig) -> str:
    available = {t.lower(): t for t in config.broad}
    for tag, keywords in _BROAD_RULES:
        if tag.lower() in available and any(k in text for k in keywords):
            return available[tag.lower()]
    if _DEFAULT_BROAD.lower() in available:
        return available[_DEFAULT_BROAD.lower()]
    return config.broad[0] if config.broad else _DEFAULT_BROAD


def select_hashtags(
    title: str,
    summary: str = "",
    source: str = "",
    llm_candidates: list[str] | None = None,
    config: HashtagConfig | None = None,
) -> list[str]:
    """Return the final hashtag list: 1 broad tag + 1-2 specific tags.

    Deterministic: same inputs produce the same tags. LLM-suggested tags are
    only used when they already exist in the config (validated candidates get
    priority within their slot); everything else is dropped.
    """
    config = config or load_hashtag_config()
    text = f"{title} {summary} {source}".lower()
    max_specific = max(1, config.max_per_post - 1)

    broad = _pick_broad(text, config)

    # Specific tags from deterministic keyword matching, in config order.
    keyword_specific: list[str] = []
    matched = set(_matched_categories(text))
    for category, tags in config.specific.items():
        if category in matched:
            keyword_specific.extend(tags)

    # Validated LLM candidates: keep only tags that exist in the config and
    # are specific tags (broad slot is always chosen deterministically).
    specific_by_lower: dict[str, str] = {}
    for tags in config.specific.values():
        for t in tags:
            specific_by_lower[t.lower()] = t
    validated_llm: list[str] = []
    for cand in llm_candidates or []:
        c = str(cand).strip()
        if not c.startswith("#"):
            c = f"#{c.lstrip('#')}"
        canonical = specific_by_lower.get(c.lower())
        if canonical:
            validated_llm.append(canonical)

    specific: list[str] = []
    for tag in keyword_specific + validated_llm:
        if tag.lower() != broad.lower() and tag not in specific:
            specific.append(tag)
        if len(specific) >= max_specific:
            break

    if not specific:
        # No specific match: fall back to a second broad tag so posts always
        # carry at least two feed-discoverable tags.
        for tag in config.broad:
            if tag.lower() != broad.lower():
                specific.append(tag)
                break

    return [broad] + specific[:max_specific]
