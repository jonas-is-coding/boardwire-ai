from __future__ import annotations

from pathlib import Path
import time
from urllib.parse import quote

import requests


def compose_text_with_link(post: str, source_link: str | None, limit: int) -> str:
    """Return the post text with the source URL appended, trimmed to ``limit`` chars.

    The body is trimmed when needed — never the URL — so the link stays intact.
    URLs are auto-linked by Mastodon/Threads, so no rich-text facets are needed.
    """
    base = post.rstrip()
    if not source_link:
        return base[:limit]

    url = source_link.strip()
    suffix = f"\n\n🔗 {url}"
    budget = limit - len(suffix)
    if budget < 0:
        return url[:limit]
    if len(base) > budget:
        base = base[:budget].rstrip()
    return f"{base}{suffix}" if base else url


def public_image_url(image_path: str, base_url: str) -> str:
    """Map a local card image path to its public URL under ``base_url``.

    Meta's Instagram and Threads APIs fetch images by URL rather than accepting
    a binary upload, so the card must already be reachable on the public web.
    We assume cards are served under ``base_url`` by their filename (matching how
    boardwire-web serves the ``generated/cards`` directory).
    """
    name = Path(image_path).name
    return f"{base_url.rstrip('/')}/{quote(name)}"


def request_with_retry(
    method: str,
    url: str,
    *,
    attempts: int = 3,
    delay_seconds: int = 2,
    **kwargs,
) -> requests.Response:
    """Issue an HTTP request, retrying only on timeouts with a fixed backoff."""
    last_error: Exception | None = None
    for idx in range(attempts):
        try:
            return requests.request(method, url, **kwargs)
        except requests.Timeout as exc:
            last_error = exc
            if idx == attempts - 1:
                raise
            time.sleep(delay_seconds)
    if last_error:
        raise last_error
    raise requests.RequestException("Unexpected retry failure")
