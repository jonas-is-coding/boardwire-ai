from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from logging import Logger

import requests

from src.models import FeedItem

DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_USER_AGENT = "BoardwireAI/0.1 (+https://github.com/)"
SOURCE_NAME = "GitHub Trending"
SOURCE_TIER = 2

_AI_KEYWORDS = (
    "llm", "language model", "ai", "agent", "rag", "mcp",
    "transformer", "embedding", "diffusion", "fine-tun",
    "openai", "anthropic", "claude", "gemini", "ollama",
    "vllm", "huggingface", "hugging face", "langchain",
    "llamaindex", "fastembed", "qwen", "deepseek", "mistral",
    "inference engine", "vector database", "pytorch", "tensorflow",
    "machine learning", "neural", "gpt", "stable diffusion",
    "whisper", "copilot",
)

_REPO_LINK_RE = re.compile(r"^/([\w\.\-]+)/([\w\.\-]+)$")


class _TrendingParser(HTMLParser):
    """Defensive parser. Treats GitHub HTML changes as soft failures."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.repos: list[dict[str, object]] = []
        self._current: dict[str, object] | None = None
        self._in_h2_link = False
        self._in_description = False
        self._in_star_delta = False
        self._description_buffer: list[str] = []
        self._star_delta_buffer: list[str] = []
        self._description_div_depth = 0
        self._star_delta_span_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}

        if tag == "article" and "Box-row" in attr_dict.get("class", ""):
            self._current = {"owner": None, "repo": None, "description": "", "star_delta": 0}
            return

        if self._current is None:
            return

        if tag == "a" and not self._in_h2_link:
            href = attr_dict.get("href", "")
            match = _REPO_LINK_RE.match(href)
            if match and self._current.get("owner") is None:
                cls = attr_dict.get("class", "")
                if "Link" in cls or "lh-condensed" in cls or "text-bold" in cls:
                    self._current["owner"] = match.group(1)
                    self._current["repo"] = match.group(2)
                    self._in_h2_link = True

        if tag == "p":
            cls = attr_dict.get("class", "")
            if "col-9" in cls or "col-md-12" in cls:
                self._in_description = True
                self._description_buffer = []
                self._description_div_depth = 1

        if tag == "span" and self._current is not None:
            cls = attr_dict.get("class", "")
            if "float-sm-right" in cls or "star-delta" in cls:
                self._in_star_delta = True
                self._star_delta_buffer = []
                self._star_delta_span_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_h2_link:
            self._in_h2_link = False

        if tag == "p" and self._in_description:
            if self._description_div_depth > 0:
                self._description_div_depth -= 1
            if self._description_div_depth == 0:
                if self._current is not None:
                    self._current["description"] = " ".join(self._description_buffer).strip()
                self._in_description = False
                self._description_buffer = []

        if tag == "span" and self._in_star_delta:
            if self._star_delta_span_depth > 0:
                self._star_delta_span_depth -= 1
            if self._star_delta_span_depth == 0:
                raw = " ".join(self._star_delta_buffer).strip().lower()
                star_match = re.search(r"([\d,]+)\s+stars", raw)
                if star_match and self._current is not None:
                    self._current["star_delta"] = int(star_match.group(1).replace(",", ""))
                self._in_star_delta = False
                self._star_delta_buffer = []

        if tag == "article" and self._current is not None:
            if self._current.get("owner") and self._current.get("repo"):
                self.repos.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._in_description:
            self._description_buffer.append(data)
        if self._in_star_delta:
            self._star_delta_buffer.append(data)


def _matches_ai(name: str, description: str) -> bool:
    haystack = f"{name} {description}".lower()
    return any(kw in haystack for kw in _AI_KEYWORDS)


def fetch_github_trending(
    logger: Logger | None = None,
    since: str = "daily",
) -> tuple[list[FeedItem], dict[str, object]]:
    url = f"https://github.com/trending?since={since}"
    try:
        response = requests.get(
            url,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        if logger:
            logger.warning("GitHub Trending fetch failed: %s", exc)
        return [], {"count": 0, "error": str(exc)}

    parser = _TrendingParser()
    try:
        parser.feed(response.text)
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.warning("GitHub Trending parse failed: %s", exc)
        return [], {"count": 0, "error": f"parse: {exc}"}

    items: list[FeedItem] = []
    seen: set[str] = set()
    now = datetime.now(tz=timezone.utc)

    for repo in parser.repos:
        owner = str(repo.get("owner") or "")
        name = str(repo.get("repo") or "")
        description = str(repo.get("description") or "")
        star_delta = int(repo.get("star_delta") or 0)

        if not owner or not name:
            continue
        full_name = f"{owner}/{name}"
        if not _matches_ai(full_name, description):
            continue

        link = f"https://github.com/{full_name}"
        if link in seen:
            continue
        seen.add(link)

        title = f"{full_name}" if not description else f"{full_name} — {description}"
        summary = (
            f"Trending on GitHub today: +{star_delta} stars. {description}"
            if description
            else f"Trending on GitHub today: +{star_delta} stars."
        )

        items.append(
            FeedItem(
                source=SOURCE_NAME,
                title=title[:200],
                link=link,
                summary=summary,
                published_at=now,
                source_tier=SOURCE_TIER,
                engagement_score=float(star_delta),
            )
        )

    items.sort(key=lambda i: i.engagement_score, reverse=True)
    if logger:
        logger.info(
            "GitHub Trending: parsed %d repos, %d AI-relevant kept",
            len(parser.repos),
            len(items),
        )

    return items, {
        "count": len(items),
        "parsed_total": len(parser.repos),
        "error": None,
        "top_titles": [i.title for i in items[:3]],
    }
