"""Newsroom orchestrator.

Ties the stages together for one run:

    items → desk.select_story_leads → reporter.research → story_memory.record

Budget-aware: only the top ``max_stories`` leads get the full deep-research
treatment; everything else is left to the existing pipeline. Dossiers are
persisted to ``data/dossiers/<lead_id>.json`` and storylines updated for
follow-ups.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from src.config import DOSSIERS_DIR, STORIES_PATH
from src.llm.client import LLMConfig
from src.models import FeedItem, ResearchDossier
from src.newsroom.config import NewsroomConfig
from src.newsroom.desk import select_story_leads
from src.newsroom.llm_bridge import make_llm_json
from src.newsroom.reporter import Reporter
from src.newsroom.story_memory import StoryMemory
from src.storage.json_store import JsonStore


def run_newsroom_research(
    items: list[FeedItem],
    *,
    config: NewsroomConfig,
    llm_config: LLMConfig,
    logger,
    dossiers_dir: Path = DOSSIERS_DIR,
    stories_path: Path = STORIES_PATH,
) -> list[ResearchDossier]:
    """Run the desk → reporter pipeline and return the dossiers produced."""

    if not items:
        logger.info("Newsroom: no items to research")
        return []

    items_by_link = {item.link: item for item in items}
    memory = StoryMemory(stories_path)

    leads = select_story_leads(
        items,
        max_stories=config.max_stories,
        logger=logger,
        story_memory=memory,
    )
    if not leads:
        logger.info("Newsroom: desk produced no leads")
        return []

    llm_json = make_llm_json(llm_config, logger=logger)
    reporter = Reporter(llm_json=llm_json, logger=logger)

    dossiers: list[ResearchDossier] = []
    for lead in leads:
        followup = " (follow-up)" if lead.is_followup else ""
        logger.info("Newsroom researching lead [%s/%s]%s: %s", lead.beat, lead.priority, followup, lead.headline[:90])
        dossier = reporter.research(lead, config=config, items_by_link=items_by_link)
        dossiers.append(dossier)
        memory.record(lead)
        _persist_dossier(dossier, dossiers_dir, logger)

    memory.save()
    logger.info("Newsroom produced %d dossiers (%d via LLM)", len(dossiers), sum(1 for d in dossiers if d.used_llm))
    return dossiers


def _persist_dossier(dossier: ResearchDossier, dossiers_dir: Path, logger) -> None:
    try:
        JsonStore.save(dossiers_dir / f"{dossier.lead_id}.json", asdict(dossier))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist dossier %s: %s", dossier.lead_id, exc)
