"""Newsroom configuration, read from environment.

All newsroom behaviour is opt-in. With no env set, ``enabled`` is False and the
rest of Boardwire is completely unaffected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class NewsroomConfig:
    enabled: bool
    max_stories: int          # how many top leads to research in depth per run
    fetch_fulltext: bool      # download & read article bodies
    max_fetch_per_story: int  # cap source fetches per story (latency/cost guard)
    web_search: bool          # allow web search for background
    web_results: int          # web results per story when enabled

    @property
    def fetch_char_cap(self) -> int:
        return _int("BOARDWIRE_NEWSROOM_FETCH_CHARS", 8000)


def load_newsroom_config() -> NewsroomConfig:
    return NewsroomConfig(
        enabled=_flag("BOARDWIRE_ENABLE_NEWSROOM", False),
        max_stories=max(1, _int("BOARDWIRE_NEWSROOM_MAX_STORIES", 2)),
        fetch_fulltext=_flag("BOARDWIRE_NEWSROOM_FETCH_FULLTEXT", True),
        max_fetch_per_story=max(1, _int("BOARDWIRE_NEWSROOM_MAX_FETCH", 5)),
        web_search=_flag("BOARDWIRE_NEWSROOM_WEB_SEARCH", False),
        web_results=max(1, _int("BOARDWIRE_NEWSROOM_WEB_RESULTS", 4)),
    )
