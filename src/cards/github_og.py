"""GitHub Open Graph card variant.

For GitHub-sourced items we A/B the editorial card against GitHub's own
repository preview image (`opengraph.githubassets.com`). The first path
segment is a cache-busting key — any value works — so we verify the endpoint
actually returns an image before using it, and fall back to the editorial card
on any failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests

_OG_BASE = "https://opengraph.githubassets.com"
# Arbitrary cache key (the segment is a cache buster, any value is accepted).
_CACHE_KEY = "1"


def github_og_url(owner: str, repo: str) -> str:
    return f"{_OG_BASE}/{_CACHE_KEY}/{owner}/{repo}"


def fetch_github_og_image(
    owner: str,
    repo: str,
    output_path: Path,
    logger=None,
    timeout: int = 20,
) -> Optional[Path]:
    """Fetch the repo's GitHub OG preview image to output_path.

    Returns the path on success, or None (caller falls back to the editorial
    card) when the endpoint does not return HTTP 200 with an image/* body.
    """
    if not owner or not repo:
        return None
    url = github_og_url(owner, repo)
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        if logger:
            logger.warning("GitHub OG fetch error for %s/%s: %s", owner, repo, exc)
        return None

    if resp.status_code != 200:
        if logger:
            logger.info("GitHub OG fetch %s/%s returned %d; using editorial card", owner, repo, resp.status_code)
        return None

    content_type = str(resp.headers.get("Content-Type", "")).lower()
    if not content_type.startswith("image/"):
        if logger:
            logger.info("GitHub OG %s/%s not an image (%s); using editorial card", owner, repo, content_type or "unknown")
        return None

    content = resp.content
    if not content:
        return None

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
    except OSError as exc:
        if logger:
            logger.warning("Could not write GitHub OG image for %s/%s: %s", owner, repo, exc)
        return None
    return output_path
