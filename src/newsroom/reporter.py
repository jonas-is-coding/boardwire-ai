"""The reporter: deep multi-source research for one story lead.

Given a ``StoryLead``, the reporter:
  1. fetches the full text of every source in the cluster,
  2. optionally runs a web search for background,
  3. asks the LLM to synthesise a structured ``ResearchDossier``.

If no LLM is available it still returns a useful *extractive* dossier built
from the fetched text, so the stage degrades gracefully.
"""

from __future__ import annotations

from typing import Callable

from src.models import Claim, FeedItem, ResearchDossier, StoryLead
from src.newsroom.config import NewsroomConfig
from src.newsroom.prompts import REPORTER_SYSTEM_PROMPT, build_reporter_user_prompt
from src.research.fetcher import FetchedDoc, fetch_many
from src.research.web_search import search_web

_VALID_SUPPORT = {"verified", "single_source", "unverified", "conflicting"}


class Reporter:
    def __init__(
        self,
        *,
        llm_json: Callable[[str, str], dict] | None = None,
        fetcher: Callable[..., list[FetchedDoc]] | None = None,
        searcher: Callable[..., list] | None = None,
        logger=None,
    ) -> None:
        self._llm_json = llm_json
        self._fetch_many = fetcher or fetch_many
        self._search_web = searcher or search_web
        self._logger = logger

    def research(
        self,
        lead: StoryLead,
        *,
        config: NewsroomConfig,
        items_by_link: dict[str, FeedItem] | None = None,
    ) -> ResearchDossier:
        items_by_link = items_by_link or {}

        # 1. Gather full text of the cluster's sources (main link first).
        ordered_links = [lead.main_link, *[l for l in lead.member_links if l != lead.main_link]]
        docs: list[FetchedDoc] = []
        if config.fetch_fulltext:
            docs = self._fetch_many(
                ordered_links,
                limit=config.max_fetch_per_story,
                max_chars=config.fetch_char_cap,
                logger=self._logger,
            )
        sources = self._build_sources(lead, docs, items_by_link)

        # 2. Optional web search for background/corroboration.
        web_results: list[dict] = []
        if config.web_search:
            query = lead.headline if lead.headline else " ".join(lead.common_terms[:6])
            for r in self._search_web(query, max_results=config.web_results, logger=self._logger):
                web_results.append({"title": getattr(r, "title", ""), "url": getattr(r, "url", ""), "snippet": getattr(r, "snippet", "")})

        if self._logger:
            ok = sum(1 for d in docs if d.ok)
            self._logger.info(
                "Reporter '%s': %d/%d sources fetched, %d web results",
                lead.headline[:80], ok, len(docs), len(web_results),
            )

        # 3. Synthesise the dossier (LLM, with extractive fallback).
        if self._llm_json is not None and sources:
            try:
                return self._llm_dossier(lead, sources, web_results)
            except Exception as exc:  # noqa: BLE001
                if self._logger:
                    self._logger.warning("Reporter LLM failed (%s); using extractive fallback", exc)
        return self._extractive_dossier(lead, sources)

    # -- internals ---------------------------------------------------------

    def _build_sources(
        self,
        lead: StoryLead,
        docs: list[FetchedDoc],
        items_by_link: dict[str, FeedItem],
    ) -> list[dict]:
        doc_by_url = {d.url: d for d in docs}
        sources: list[dict] = []
        for link in [lead.main_link, *[l for l in lead.member_links if l != lead.main_link]]:
            item = items_by_link.get(link)
            doc = doc_by_url.get(link)
            text = doc.text if (doc and doc.ok) else ((item.summary if item else "") or "")
            if not text.strip():
                continue
            sources.append(
                {
                    "source": item.source if item else "",
                    "url": link,
                    "title": (doc.title if (doc and doc.title) else (item.title if item else lead.headline)),
                    "text": text,
                }
            )
        return sources

    def _llm_dossier(self, lead: StoryLead, sources: list[dict], web_results: list[dict]) -> ResearchDossier:
        storyline_ctx = {"title": lead.headline, "update_links": lead.member_links} if lead.is_followup else None
        user = build_reporter_user_prompt(
            headline=lead.headline,
            beat=lead.beat,
            angle_hypothesis=lead.angle_hypothesis,
            sources=sources,
            web_results=web_results or None,
            storyline=storyline_ctx,
        )
        data = self._llm_json(REPORTER_SYSTEM_PROMPT, user)
        return self._dossier_from_dict(lead, sources, data, used_llm=True)

    def _dossier_from_dict(
        self, lead: StoryLead, sources: list[dict], data: dict, *, used_llm: bool
    ) -> ResearchDossier:
        claims: list[Claim] = []
        for raw in (data.get("claims") or [])[:8]:
            if not isinstance(raw, dict):
                continue
            support = str(raw.get("support", "unverified")).strip().lower()
            claims.append(
                Claim(
                    text=str(raw.get("text", "")).strip(),
                    support=support if support in _VALID_SUPPORT else "unverified",
                    source_links=[str(u) for u in (raw.get("source_links") or []) if u][:5],
                )
            )

        def _strlist(key: str) -> list[str]:
            return [str(x).strip() for x in (data.get(key) or []) if str(x).strip()][:8]

        return ResearchDossier(
            lead_id=lead.id,
            headline=lead.headline,
            summary=str(data.get("summary", "")).strip(),
            beat=lead.beat,
            angle=str(data.get("angle", lead.angle_hypothesis)).strip() or lead.angle_hypothesis,
            key_facts=_strlist("key_facts"),
            claims=[c for c in claims if c.text],
            numbers=_strlist("numbers"),
            quotes=_strlist("quotes"),
            background=str(data.get("background", "")).strip(),
            open_questions=_strlist("open_questions"),
            source_urls=[s["url"] for s in sources],
            storyline_id=lead.storyline_id,
            is_followup=lead.is_followup,
            used_llm=used_llm,
        )

    def _extractive_dossier(self, lead: StoryLead, sources: list[dict]) -> ResearchDossier:
        """LLM-free fallback: still richer than a bare summary."""

        first_text = sources[0]["text"] if sources else ""
        # First couple of sentences as a crude summary.
        sentences = [s.strip() for s in first_text.replace("\n", " ").split(". ") if s.strip()]
        summary = ". ".join(sentences[:2])
        if summary and not summary.endswith("."):
            summary += "."
        key_facts = [s for s in sentences[:5] if len(s) > 25][:5]
        support = "verified" if len(sources) >= 2 else "single_source"
        claims = [Claim(text=lead.headline, support=support, source_links=[s["url"] for s in sources])]
        return ResearchDossier(
            lead_id=lead.id,
            headline=lead.headline,
            summary=summary or lead.headline,
            beat=lead.beat,
            angle=lead.angle_hypothesis,
            key_facts=key_facts,
            claims=claims,
            source_urls=[s["url"] for s in sources],
            background=f"Covered by {len(sources)} source(s): {', '.join(s['source'] for s in sources if s['source'])}".strip(),
            storyline_id=lead.storyline_id,
            is_followup=lead.is_followup,
            used_llm=False,
        )
