"""Growth configuration: ``config/growth.json`` plus a few env overrides.

The growth package writes to the live Boardwire account (follow records, the
profile record, a pinned intro thread), so every knob is explicit and lives in
git. Nothing in this module touches the network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import GROWTH_CONFIG_PATH, GROWTH_LEDGER_PATH, PROJECT_ROOT
from src.storage.json_store import JsonStore

DEFAULT_KEYWORDS = [
    "Claude Code",
    "MCP server",
    "local LLM",
    "open weights",
    "Ollama",
    "AI agents",
]

# Bio / display-name fragments that mark accounts we never want in the graph.
DEFAULT_BLOCKED_KEYWORDS = [
    "crypto",
    "nft",
    "airdrop",
    "forex",
    "casino",
    "onlyfans",
    "giveaway",
    "follow back",
    "followback",
    "follow4follow",
    "f4f",
    "growth hacking",
]

DEFAULT_PACE_SECONDS = (20.0, 45.0)


def normalize_handle(value: Any) -> str:
    return str(value or "").strip().lstrip("@").lower()


def is_list_reference(value: str) -> bool:
    """``list_uris`` entries: an ``at://`` list or starter-pack URI, or the
    bsky.app URL of a starter pack / list (resolved at runtime)."""
    text = str(value or "").strip()
    return (
        text.startswith("at://")
        or text.startswith("https://bsky.app/starter-pack/")
        or (text.startswith("https://bsky.app/profile/") and "/lists/" in text)
    )


@dataclass(slots=True)
class DiscoveryWeights:
    """Per-channel weight added to a candidate's score each time a channel
    surfaces it.

    The score measures *graph relevance* — how strongly the niche we want to be
    part of already points at an account — and deliberately not follow-back
    likelihood.
    """

    seed_follows: float = 1.0     # accounts a seed chose to follow (curated by people we trust)
    seed_followers: float = 0.5   # accounts following a seed (interested, less curated)
    lists: float = 0.8            # starter packs / curated lists
    search: float = 0.4           # keyword search over profiles (noisiest channel)
    bio_keyword: float = 0.2      # per niche keyword found in the bio (capped at 3 hits)


@dataclass(slots=True)
class CandidateFilters:
    min_followers: int = 30
    max_followers: int = 50_000
    min_posts: int = 10
    max_follow_ratio: float = 4.0        # follows / followers; above this it is follow-spam
    max_days_since_post: int = 45        # dormant accounts never see the follow
    require_description: bool = True
    blocked_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_KEYWORDS))


@dataclass(slots=True)
class GrowthConfig:
    seed_handles: list[str] = field(default_factory=list)
    list_uris: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    weights: DiscoveryWeights = field(default_factory=DiscoveryWeights)
    filters: CandidateFilters = field(default_factory=CandidateFilters)
    follows_per_run: int = 12
    graph_depth_per_seed: int = 100   # follows AND followers read per seed
    max_search_results: int = 50      # per keyword
    max_list_members: int = 100       # per list
    max_hydrate: int = 300            # top raw candidates re-hydrated via getProfiles
    freshness_pool_factor: int = 3    # last-post check for follows_per_run x factor candidates
    seed_max_days_since_post: int = 90  # a seed silent for longer fails --growth-verify-seeds
    pace_seconds_min: float = DEFAULT_PACE_SECONDS[0]
    pace_seconds_max: float = DEFAULT_PACE_SECONDS[1]
    ledger_path: Path = GROWTH_LEDGER_PATH

    @property
    def freshness_pool(self) -> int:
        return max(self.follows_per_run, self.follows_per_run * max(1, self.freshness_pool_factor))


def _int(raw: dict, key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(raw.get(key, default)))
    except (TypeError, ValueError):
        return default


def _float(raw: dict, key: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(raw.get(key, default)))
    except (TypeError, ValueError):
        return default


def _bool(raw: dict, key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _str_list(raw: dict, key: str) -> list[str]:
    values = raw.get(key, [])
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _pace(raw: dict) -> tuple[float, float]:
    value = raw.get("pace_seconds")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return DEFAULT_PACE_SECONDS
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return DEFAULT_PACE_SECONDS
    low = max(0.0, low)
    high = max(low, high)
    return low, high


def load_growth_config(path: Path | None = None) -> GrowthConfig:
    raw = JsonStore.load(path or GROWTH_CONFIG_PATH, default={})
    if not isinstance(raw, dict):
        raw = {}
    weights_raw = raw.get("weights") if isinstance(raw.get("weights"), dict) else {}
    filters_raw = raw.get("filters") if isinstance(raw.get("filters"), dict) else {}

    seeds: list[str] = []
    for handle in _str_list(raw, "seed_handles"):
        normalized = normalize_handle(handle)
        if normalized and normalized not in seeds:
            seeds.append(normalized)

    weights = DiscoveryWeights(
        seed_follows=_float(weights_raw, "seed_follows", 1.0),
        seed_followers=_float(weights_raw, "seed_followers", 0.5),
        lists=_float(weights_raw, "lists", 0.8),
        search=_float(weights_raw, "search", 0.4),
        bio_keyword=_float(weights_raw, "bio_keyword", 0.2),
    )
    blocked = (
        _str_list(filters_raw, "blocked_keywords")
        if "blocked_keywords" in filters_raw
        else list(DEFAULT_BLOCKED_KEYWORDS)
    )
    filters = CandidateFilters(
        min_followers=_int(filters_raw, "min_followers", 30),
        max_followers=_int(filters_raw, "max_followers", 50_000, minimum=1),
        min_posts=_int(filters_raw, "min_posts", 10),
        max_follow_ratio=_float(filters_raw, "max_follow_ratio", 4.0, minimum=0.1),
        max_days_since_post=_int(filters_raw, "max_days_since_post", 45, minimum=1),
        require_description=_bool(filters_raw, "require_description", True),
        blocked_keywords=[k.lower() for k in blocked],
    )
    pace_min, pace_max = _pace(raw)

    follows_per_run = _int(raw, "follows_per_run", 12, minimum=1)
    follows_per_run = max(1, _env_int("BOARDWIRE_GROWTH_FOLLOWS_PER_RUN", follows_per_run))

    ledger_path = GROWTH_LEDGER_PATH
    ledger_raw = str(raw.get("ledger_path") or "").strip()
    if ledger_raw:
        candidate = Path(ledger_raw)
        ledger_path = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate

    return GrowthConfig(
        seed_handles=seeds,
        list_uris=[u for u in _str_list(raw, "list_uris") if is_list_reference(u)],
        keywords=_str_list(raw, "keywords") or list(DEFAULT_KEYWORDS),
        weights=weights,
        filters=filters,
        follows_per_run=follows_per_run,
        graph_depth_per_seed=_int(raw, "graph_depth_per_seed", 100, minimum=1),
        max_search_results=_int(raw, "max_search_results", 50, minimum=1),
        max_list_members=_int(raw, "max_list_members", 100, minimum=1),
        max_hydrate=_int(raw, "max_hydrate", 300, minimum=1),
        freshness_pool_factor=_int(raw, "freshness_pool_factor", 3, minimum=1),
        seed_max_days_since_post=_int(raw, "seed_max_days_since_post", 90, minimum=1),
        pace_seconds_min=pace_min,
        pace_seconds_max=pace_max,
        ledger_path=ledger_path,
    )
