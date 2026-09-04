"""Bluesky rich-text facets that the AT Protocol does NOT derive for you.

The Bluesky app parses ``#tags``, links and mentions client-side and stores
them as ``facets`` on the post record. A record created through the API with
plain text carries none of that: ``#OpenSource`` renders as inert text, is not
clickable, and is invisible to the hashtag index that custom feeds and the
``tag`` search filter use. Boardwire's whole discovery strategy (1 broad +
1-2 specific tags per post, see ``src/hashtags.py``) therefore did nothing on
the live account until this module existed.

Rules mirror the official ``@atproto/api`` ``detectFacets``: a tag starts at
the beginning of the text or after whitespace, begins with ``#`` followed by
a non-digit, runs to the next whitespace, loses trailing punctuation, and is
at most 64 characters long (66 with the ``#``). Facet indices are UTF-8 byte
offsets.

``langs`` is the other field the app always sets and the API leaves empty. A
post without a language is excluded by every language-filtered feed, the
Discover feed included, so every Boardwire post declares one.
"""

from __future__ import annotations

import os
import re
import unicodedata

TAG_FACET_TYPE = "app.bsky.richtext.facet#tag"
LINK_FACET_TYPE = "app.bsky.richtext.facet#link"

# Max tag length in the app.bsky.richtext.facet#tag lexicon (graphemes; the
# official client counts UTF-16 units, a stricter-or-equal bound here is fine).
MAX_TAG_LENGTH = 64
# The post record allows at most 3 language codes.
MAX_LANGS = 3
DEFAULT_POST_LANG = "en"

# "#" at text start or after whitespace, first char not a digit, then anything
# up to the next whitespace. Trailing punctuation is stripped afterwards.
_TAG_RE = re.compile(r"(?:^|(?<=\s))#([^\d\s#][^\s]*)")


def byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _strip_trailing_punctuation(value: str) -> str:
    end = len(value)
    while end > 0 and unicodedata.category(value[end - 1]).startswith("P"):
        end -= 1
    return value[:end]


def tag_facets(text: str) -> list[dict]:
    """``app.bsky.richtext.facet#tag`` facets for every hashtag in ``text``."""
    facets: list[dict] = []
    for match in _TAG_RE.finditer(text or ""):
        tag = _strip_trailing_punctuation(match.group(1))
        if not tag or len(tag) > MAX_TAG_LENGTH:
            continue
        start = match.start()
        end = start + 1 + len(tag)  # "#" + tag
        facets.append(
            {
                "index": {"byteStart": byte_len(text[:start]), "byteEnd": byte_len(text[:end])},
                "features": [{"$type": TAG_FACET_TYPE, "tag": tag}],
            }
        )
    return facets


def merge_facets(*groups: list[dict]) -> list[dict]:
    """Combine facet lists into one, ordered by byteStart, dropping any facet
    that overlaps an earlier one (a tag inside a link range must not win)."""
    candidates = [f for group in groups for f in (group or []) if isinstance(f, dict)]
    candidates.sort(key=lambda f: (int(f["index"]["byteStart"]), int(f["index"]["byteEnd"])))
    merged: list[dict] = []
    last_end = -1
    for facet in candidates:
        start = int(facet["index"]["byteStart"])
        end = int(facet["index"]["byteEnd"])
        if start < last_end or end <= start:
            continue
        merged.append(facet)
        last_end = end
    return merged


def post_langs(raw: str | None = None) -> list[str]:
    """Language codes for the ``langs`` field. ``BOARDWIRE_POST_LANGS`` is a
    comma-separated list (default ``en``); never empty, at most three."""
    value = raw if raw is not None else os.getenv("BOARDWIRE_POST_LANGS", "")
    langs: list[str] = []
    for part in str(value or "").split(","):
        code = part.strip()
        if code and code not in langs:
            langs.append(code)
    if not langs:
        langs = [DEFAULT_POST_LANG]
    return langs[:MAX_LANGS]
