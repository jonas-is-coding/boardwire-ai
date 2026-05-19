from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Source:
    name: str
    url: str
    enabled: bool = True
    fallback_urls: list[str] | None = None
    tier: int = 3


@dataclass(slots=True)
class FeedItem:
    source: str
    title: str
    link: str
    summary: str
    published_at: datetime
    source_tier: int = 3
    engagement_score: float = 0.0


@dataclass(slots=True)
class Persona:
    name: str
    role: str


@dataclass(slots=True)
class EvaluationResult:
    should_post: bool
    score: int
    reason: str


@dataclass(slots=True)
class DraftPost:
    title: str
    link: str
    source: str
    score: int
    should_post: bool
    reason: str
    post_text: str
    source_angle: str = ""
    source_tier: int = 3
    engagement_score: float = 0.0
    local_newsworthiness_score: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
