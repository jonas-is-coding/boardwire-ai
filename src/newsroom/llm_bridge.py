"""Bridge the existing LLM clients to a simple ``llm_json`` callable.

The reporter (and later the fact-checker / editor) only needs:
``(system, user) -> dict``. This adapts whichever provider is configured —
respecting the shared Gemini call budget — and returns ``None`` when no LLM is
available so callers can fall back to a rule-based dossier.
"""

from __future__ import annotations

import logging
from typing import Callable

from src.llm.client import GeminiClient, LLMConfig, OpenAIClient
from src.llm.gemini_budget import try_consume_gemini_budget

LLMJson = Callable[[str, str], dict]


def make_llm_json(llm_config: LLMConfig, logger=None) -> LLMJson | None:
    """Return an ``llm_json(system, user)`` callable, or None if unavailable."""

    provider = (llm_config.provider or "none").lower()
    log = logger or logging.getLogger("boardwire.newsroom")

    if provider == "gemini" and llm_config.gemini_api_key:
        client = GeminiClient(llm_config.gemini_api_key, llm_config.gemini_model)

        def _gemini(system: str, user: str) -> dict:
            if not try_consume_gemini_budget("newsroom", log):
                raise RuntimeError("gemini budget exhausted")
            return client.generate_json(system, user)

        return _gemini

    if provider == "openai" and llm_config.openai_api_key:
        client = OpenAIClient(llm_config.openai_api_key, llm_config.openai_model)

        def _openai(system: str, user: str) -> dict:
            return client.generate_json(system, user)

        return _openai

    if logger:
        logger.info("Newsroom LLM unavailable (provider=%s); using extractive fallback", provider)
    return None
