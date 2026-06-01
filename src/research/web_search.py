"""Optional web search for background and corroboration.

The cluster already gives the reporter cross-source coverage of the *same*
story. Web search is the extra step a real journalist takes: find background,
prior reporting, and independent reactions beyond the feeds we ingest.

Pluggable by ``BOARDWIRE_WEB_SEARCH_PROVIDER``:
  - ``none``   (default) → no-op, returns []
  - ``gemini``           → Gemini Google-Search grounding

Best-effort by design: any failure returns an empty list rather than breaking a
run. Tests inject a fake ``search`` callable, so no network is required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(slots=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str = ""


def web_search_enabled() -> bool:
    return _provider() != "none"


def _provider() -> str:
    return os.getenv("BOARDWIRE_WEB_SEARCH_PROVIDER", "none").strip().lower() or "none"


def search_web(query: str, *, max_results: int = 5, logger=None) -> list[WebSearchResult]:
    """Run a web search using the configured provider. Never raises."""

    provider = _provider()
    if provider == "none" or not query.strip():
        return []
    if provider == "gemini":
        try:
            return _gemini_grounded_search(query, max_results=max_results, logger=logger)
        except Exception as exc:  # noqa: BLE001
            if logger:
                logger.warning("Web search (gemini) failed: %s", exc)
            return []
    if logger:
        logger.warning("Unknown web search provider: %s", provider)
    return []


def _gemini_api_key() -> str | None:
    for env in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"):
        key = os.getenv(env, "").strip()
        if key:
            return key
    return None


def _gemini_grounded_search(query: str, *, max_results: int, logger=None) -> list[WebSearchResult]:
    key = _gemini_api_key()
    if not key:
        return []
    model = os.getenv("BOARDWIRE_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Find recent, credible reporting and background for this AI/tech story. "
                            f"Query: {query}\n"
                            "Summarise what independent sources say in 3-4 sentences."
                        )
                    }
                ]
            }
        ],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }
    response = requests.post(url, json=body, timeout=30)
    if response.status_code >= 400:
        if logger:
            logger.warning("Gemini grounding error %s: %s", response.status_code, response.text[:160])
        return []
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return []
    metadata = candidates[0].get("groundingMetadata", {}) or {}
    chunks = metadata.get("groundingChunks", []) or []
    results: list[WebSearchResult] = []
    seen: set[str] = set()
    for chunk in chunks:
        web = chunk.get("web") or {}
        uri = str(web.get("uri", "")).strip()
        title = str(web.get("title", "")).strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        results.append(WebSearchResult(title=title or uri, url=uri))
        if len(results) >= max_results:
            break
    return results
