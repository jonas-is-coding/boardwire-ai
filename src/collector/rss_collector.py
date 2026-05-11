from __future__ import annotations

from datetime import datetime, timezone
from logging import Logger
from typing import Iterable

import feedparser
from dateutil import parser as date_parser
import requests

from src.models import FeedItem, Source

DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_USER_AGENT = "BoardwireAI/0.1 (+https://github.com/)"


def _parse_published(entry: feedparser.FeedParserDict) -> datetime:
    candidates = [
        entry.get("published"),
        entry.get("updated"),
        entry.get("created"),
    ]
    for value in candidates:
        if not value:
            continue
        try:
            dt = date_parser.parse(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
    return datetime.now(tz=timezone.utc)


def _pick_link(entry: feedparser.FeedParserDict) -> str:
    link = (entry.get("link") or "").strip()
    if link:
        return link

    for alt in entry.get("links", []):
        href = (alt.get("href") or "").strip()
        if href:
            return href
    return ""


def _fetch_feed(url: str) -> feedparser.FeedParserDict:
    response = requests.get(
        url,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    response.raise_for_status()
    return feedparser.parse(response.content)


def fetch_from_source(source: Source, logger: Logger | None = None) -> tuple[list[FeedItem], str | None]:
    urls = [source.url, *(source.fallback_urls or [])]
    errors: list[str] = []
    parsed: feedparser.FeedParserDict | None = None
    used_url: str | None = None

    for url in urls:
        try:
            parsed = _fetch_feed(url)
            used_url = url
            break
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")

    if parsed is None:
        reason = "; ".join(errors) if errors else "unknown fetch error"
        if logger:
            logger.warning("Failed source %s: %s", source.name, reason)
        return [], reason

    items: list[FeedItem] = []
    seen_links: set[str] = set()
    for entry in parsed.entries:
        link = _pick_link(entry)
        title = (entry.get("title") or "Untitled").strip()
        summary = (entry.get("summary") or entry.get("description") or title).strip()
        if not link:
            continue
        if link in seen_links:
            continue
        seen_links.add(link)

        items.append(
            FeedItem(
                source=source.name,
                title=title,
                link=link,
                summary=summary,
                published_at=_parse_published(entry),
            )
        )

    if logger:
        logger.info("Fetched %d items from %s", len(items), source.name)
    if getattr(parsed, "bozo", False) and logger:
        logger.warning("Feed parse warning for %s (%s): %s", source.name, used_url, parsed.get("bozo_exception"))

    return items, None


def fetch_all(sources: Iterable[Source], logger: Logger | None = None) -> tuple[list[FeedItem], dict[str, dict[str, object]]]:
    collected: list[FeedItem] = []
    source_report: dict[str, dict[str, object]] = {}
    global_seen_links: set[str] = set()

    for source in sources:
        if not source.enabled:
            continue

        items, error = fetch_from_source(source, logger=logger)
        deduped_for_global: list[FeedItem] = []
        for item in items:
            if item.link in global_seen_links:
                continue
            global_seen_links.add(item.link)
            deduped_for_global.append(item)

        collected.extend(deduped_for_global)
        newest_titles = [item.title for item in sorted(items, key=lambda x: x.published_at, reverse=True)[:3]]
        source_report[source.name] = {
            "count": len(items),
            "error": error,
            "newest_titles": newest_titles,
        }

    return collected, source_report
