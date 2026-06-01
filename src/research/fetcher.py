"""Article full-text fetching.

The rest of Boardwire only ever sees ``title + summary[:800]``. A real reporter
reads the whole piece. This module downloads a URL and extracts the readable
body text using only the standard library (no extra dependencies), so it stays
cheap and works in CI.

The HTML→text extraction is intentionally simple and robust rather than
perfect: it strips boilerplate tags (script/style/nav/header/footer/aside),
keeps block structure as newlines, and collapses whitespace. The goal is to
give an LLM clean, readable context — not pixel-perfect article parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

import requests

_DEFAULT_TIMEOUT = 15
_DEFAULT_MAX_BYTES = 2_000_000
_DEFAULT_MAX_CHARS = 8_000
_USER_AGENT = "BoardwireBot/1.0 (+https://github.com/jonas-is-coding/boardwire-ai)"

# Tags whose text content is never part of the article body.
_SKIP_TAGS = {"script", "style", "head", "noscript", "nav", "header", "footer", "aside", "form", "svg"}
# Block-level tags that should produce a line break in the extracted text.
_BLOCK_TAGS = {
    "p", "div", "section", "article", "br", "li", "ul", "ol", "tr",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "figcaption",
}


@dataclass(slots=True)
class FetchedDoc:
    url: str
    ok: bool
    status: int = 0
    title: str = ""
    text: str = ""
    error: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def word_count(self) -> int:
        return len(self.text.split()) if self.text else 0


class _ArticleTextExtractor(HTMLParser):
    """Collects readable text and the document <title> from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        # Title lives inside <head> (a skipped tag), so capture it first.
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._skip_depth > 0:
            return
        if data.strip():
            self.chunks.append(data)

    @property
    def title(self) -> str:
        return _collapse_inline("".join(self.title_parts))

    @property
    def text(self) -> str:
        raw = "".join(self.chunks)
        # Collapse runs of blank lines, trim trailing spaces per line.
        lines = [_collapse_inline(line) for line in raw.split("\n")]
        lines = [line for line in lines if line]
        return "\n".join(lines).strip()


def _collapse_inline(text: str) -> str:
    return re.sub(r"[ \t\f\v]+", " ", unescape(text)).strip()


def extract_text_from_html(html: str, *, max_chars: int = _DEFAULT_MAX_CHARS) -> tuple[str, str]:
    """Return ``(title, body_text)`` extracted from an HTML string.

    Pure function with no network access — the unit-testable core of the
    fetcher.
    """

    parser = _ArticleTextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - never let a malformed page crash a run
        pass
    text = parser.text
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    return parser.title, text


def fetch_fulltext(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    max_chars: int = _DEFAULT_MAX_CHARS,
    session: requests.Session | None = None,
    logger=None,
) -> FetchedDoc:
    """Download ``url`` and extract its readable article text.

    Never raises — failures are returned as ``FetchedDoc(ok=False, error=...)``
    so the reporter can degrade gracefully on a dead link.
    """

    if not url or not url.startswith(("http://", "https://")):
        return FetchedDoc(url=url, ok=False, error="invalid url")

    get = (session or requests).get
    try:
        response = get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            stream=True,
        )
    except requests.RequestException as exc:
        if logger:
            logger.warning("Fetch failed for %s: %s", url, exc)
        return FetchedDoc(url=url, ok=False, error=str(exc)[:200])

    status = response.status_code
    content_type = response.headers.get("Content-Type", "")
    if status >= 400:
        response.close()
        return FetchedDoc(url=url, ok=False, status=status, error=f"http {status}")
    if "html" not in content_type and "xml" not in content_type and content_type:
        response.close()
        return FetchedDoc(url=url, ok=False, status=status, error=f"non-html content-type: {content_type[:60]}")

    raw = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=16_384):
            if not chunk:
                continue
            raw.extend(chunk)
            if len(raw) >= max_bytes:
                break
    except requests.RequestException as exc:
        return FetchedDoc(url=url, ok=False, status=status, error=str(exc)[:200])
    finally:
        response.close()

    encoding = response.encoding or "utf-8"
    try:
        html = raw.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        html = raw.decode("utf-8", errors="replace")

    title, text = extract_text_from_html(html, max_chars=max_chars)
    if not text:
        return FetchedDoc(url=url, ok=False, status=status, title=title, error="no readable text")
    return FetchedDoc(url=url, ok=True, status=status, title=title, text=text)


def fetch_many(
    urls: list[str],
    *,
    limit: int | None = None,
    logger=None,
    **kwargs,
) -> list[FetchedDoc]:
    """Fetch a list of URLs (de-duplicated, order-preserving)."""

    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    if limit is not None:
        ordered = ordered[:limit]

    session = requests.Session()
    try:
        return [fetch_fulltext(url, session=session, logger=logger, **kwargs) for url in ordered]
    finally:
        session.close()
