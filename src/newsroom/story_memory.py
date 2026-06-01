"""Persistent storyline memory for follow-ups.

A real newsroom remembers what it has been covering. This stores running
storylines in ``data/stories.json`` and matches a new lead to an existing
storyline by term overlap, so the reporter/editor can frame a development as an
*update* rather than an isolated post.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.models import StoryLead, Storyline
from src.storage.json_store import JsonStore

# Minimum Jaccard-style overlap of common terms to consider two stories the
# same running storyline.
_MATCH_THRESHOLD = 0.34


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_terms(terms: list[str]) -> set[str]:
    return {t.strip().lower() for t in terms if t and len(t.strip()) > 2}


class StoryMemory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._storylines: list[Storyline] = []
        for raw in JsonStore.load(path, default=[]):
            try:
                self._storylines.append(Storyline(**raw))
            except TypeError:
                continue

    @property
    def storylines(self) -> list[Storyline]:
        return list(self._storylines)

    def match(self, common_terms: list[str], beat: str) -> Storyline | None:
        """Return the best-matching active storyline for these terms, if any."""

        candidate = _norm_terms(common_terms)
        if not candidate:
            return None
        best: Storyline | None = None
        best_score = 0.0
        for line in self._storylines:
            if line.beat != beat:
                continue
            existing = _norm_terms(line.common_terms)
            if not existing:
                continue
            overlap = len(candidate & existing) / len(candidate | existing)
            if overlap > best_score:
                best_score = overlap
                best = line
        return best if best_score >= _MATCH_THRESHOLD else None

    def record(self, lead: StoryLead) -> Storyline:
        """Create or update the storyline for a researched lead."""

        existing = None
        if lead.storyline_id:
            existing = next((s for s in self._storylines if s.id == lead.storyline_id), None)
        if existing is None:
            existing = self.match(lead.common_terms, lead.beat)

        if existing is None:
            line = Storyline(
                id=f"story_{lead.id.removeprefix('lead_')}",
                title=lead.headline,
                beat=lead.beat,
                common_terms=list(lead.common_terms),
                update_links=[lead.main_link],
            )
            self._storylines.append(line)
            return line

        # Merge the new development into the existing storyline.
        if lead.main_link not in existing.update_links:
            existing.update_links.append(lead.main_link)
        merged = list(dict.fromkeys([*existing.common_terms, *lead.common_terms]))[:12]
        existing.common_terms = merged
        existing.last_update = _now()
        existing.status = "active"
        return existing

    def save(self) -> None:
        from dataclasses import asdict

        JsonStore.save(self.path, [asdict(line) for line in self._storylines])
