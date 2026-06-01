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
class StoryLead:
    """A story the news desk decides is worth pursuing.

    A lead is a *cluster* of related items (cross-source) plus an editorial
    framing — the beat it belongs to, a working angle, and a priority. It is
    the unit a Reporter researches in depth.
    """

    id: str
    headline: str
    beat: str
    angle_hypothesis: str
    priority: int
    main_link: str
    member_links: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    common_terms: list[str] = field(default_factory=list)
    engagement_score: float = 0.0
    source_tier: int = 3
    storyline_id: str | None = None
    is_followup: bool = False


@dataclass(slots=True)
class Claim:
    """A single factual assertion extracted from the research."""

    text: str
    support: str = "unverified"  # verified | single_source | unverified | conflicting
    source_links: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResearchDossier:
    """The Reporter's deep-research output for one StoryLead.

    Synthesised from the full text of every source in the cluster (plus any
    optional web search), not just an RSS summary. This is what the Editor
    turns into the actual outputs (short post / article / thread).
    """

    lead_id: str
    headline: str
    summary: str
    beat: str
    angle: str
    key_facts: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    background: str = ""
    open_questions: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    storyline_id: str | None = None
    is_followup: bool = False
    used_llm: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@dataclass(slots=True)
class Storyline:
    """A running storyline tracked across multiple runs (for follow-ups)."""

    id: str
    title: str
    beat: str
    common_terms: list[str] = field(default_factory=list)
    update_links: list[str] = field(default_factory=list)
    status: str = "active"  # active | dormant
    first_seen: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    last_update: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


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
