"""Profile record + pinned intro thread.

Positioning decision: the bio and the pinned thread explain the *engineering
project* (the pipeline), not the news product — the news is the output. Both
texts live in ``config/identity.json`` and are validated here against the AT
Protocol limits before anything is written.

Profile writes always **merge onto the live record**: a naive overwrite of
``app.bsky.actor.profile/self`` drops the avatar and banner blob references
(and any pinned post), so the record is read first and only ``displayName``,
``description`` and ``pinnedPost`` are replaced.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from logging import Logger
from pathlib import Path

from src.composer import byte_len
from src.config import IDENTITY_CONFIG_PATH
from src.growth.client import POST_COLLECTION, PROFILE_COLLECTION, GrowthClient, GrowthClientError, utc_now_iso
from src.growth.ledger import GrowthLedger
from src.publisher.richtext import merge_facets, post_langs, tag_facets
from src.storage.json_store import JsonStore

# app.bsky.actor.profile / app.bsky.feed.post lexicon limits.
MAX_DISPLAY_NAME_GRAPHEMES = 64
MAX_DESCRIPTION_GRAPHEMES = 256
MAX_DESCRIPTION_BYTES = 2560
MAX_POST_GRAPHEMES = 300
MAX_POST_BYTES = 3000
MAX_THREAD_POSTS = 12

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_TRAILING_PUNCTUATION = ".,;:!?)]}\"'"


def grapheme_len(text: str) -> int:
    """Conservative grapheme count: NFC code points. Multi-code-point graphemes
    (flags, ZWJ emoji) are over-counted, never under-counted."""
    return len(unicodedata.normalize("NFC", text))


@dataclass(slots=True)
class Identity:
    display_name: str
    description: str
    intro_thread: list[str] = field(default_factory=list)

    def thread_hash(self) -> str:
        digest = hashlib.sha1()
        for text in self.intro_thread:
            digest.update(text.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()[:16]


def validate_identity(identity: Identity) -> list[str]:
    problems: list[str] = []
    if not identity.display_name.strip():
        problems.append("display_name is empty")
    elif grapheme_len(identity.display_name) > MAX_DISPLAY_NAME_GRAPHEMES:
        problems.append(
            f"display_name is {grapheme_len(identity.display_name)} graphemes (max {MAX_DISPLAY_NAME_GRAPHEMES})"
        )
    if not identity.description.strip():
        problems.append("description is empty")
    elif grapheme_len(identity.description) > MAX_DESCRIPTION_GRAPHEMES:
        problems.append(
            f"description is {grapheme_len(identity.description)} graphemes (max {MAX_DESCRIPTION_GRAPHEMES})"
        )
    elif byte_len(identity.description) > MAX_DESCRIPTION_BYTES:
        problems.append(f"description is {byte_len(identity.description)} bytes (max {MAX_DESCRIPTION_BYTES})")
    if not identity.intro_thread:
        problems.append("intro_thread has no posts")
    elif len(identity.intro_thread) > MAX_THREAD_POSTS:
        problems.append(f"intro_thread has {len(identity.intro_thread)} posts (max {MAX_THREAD_POSTS})")
    for idx, text in enumerate(identity.intro_thread, start=1):
        if not text.strip():
            problems.append(f"intro_thread[{idx}] is empty")
            continue
        if grapheme_len(text) > MAX_POST_GRAPHEMES:
            problems.append(f"intro_thread[{idx}] is {grapheme_len(text)} graphemes (max {MAX_POST_GRAPHEMES})")
        if byte_len(text) > MAX_POST_BYTES:
            problems.append(f"intro_thread[{idx}] is {byte_len(text)} bytes (max {MAX_POST_BYTES})")
    return problems


def load_identity(path: Path | None = None) -> Identity:
    source = path or IDENTITY_CONFIG_PATH
    raw = JsonStore.load(source, default=None)
    if not isinstance(raw, dict):
        raise ValueError(f"identity config missing or malformed: {source}")
    thread_raw = raw.get("intro_thread") or []
    texts: list[str] = []
    if isinstance(thread_raw, list):
        for item in thread_raw:
            text = item.get("text") if isinstance(item, dict) else item
            texts.append(str(text or "").strip())
    identity = Identity(
        display_name=str(raw.get("display_name") or "").strip(),
        description=str(raw.get("description") or "").strip(),
        intro_thread=texts,
    )
    problems = validate_identity(identity)
    if problems:
        raise ValueError(f"{source.name} invalid:\n- " + "\n- ".join(problems))
    return identity


# ---------------------------------------------------------------------------
# post records
# ---------------------------------------------------------------------------


def link_facets(text: str) -> list[dict]:
    """Link facets (UTF-8 byte offsets) for every URL in the text."""
    facets: list[dict] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0)
        end = match.end()
        while url and url[-1] in _TRAILING_PUNCTUATION:
            url = url[:-1]
            end -= 1
        if not url:
            continue
        facets.append(
            {
                "index": {"byteStart": byte_len(text[: match.start()]), "byteEnd": byte_len(text[:end])},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
            }
        )
    return facets


def build_post_record(text: str, *, created_at: str, reply: dict | None = None) -> dict:
    """A feed post record with link + hashtag facets and a language, exactly
    the fields the official app sets and the raw API leaves empty."""
    record: dict = {"$type": "app.bsky.feed.post", "text": text, "createdAt": created_at, "langs": post_langs()}
    facets = merge_facets(link_facets(text), tag_facets(text))
    if facets:
        record["facets"] = facets
    if reply:
        record["reply"] = reply
    return record


def _reply_ref(root: dict, parent: dict) -> dict:
    return {
        "root": {"uri": root["uri"], "cid": root["cid"]},
        "parent": {"uri": parent["uri"], "cid": parent["cid"]},
    }


# ---------------------------------------------------------------------------
# profile record
# ---------------------------------------------------------------------------

_MANAGED_PROFILE_KEYS = {"displayName", "description"}


@dataclass(slots=True)
class ProfileUpdateResult:
    changed: bool
    dry_run: bool
    before: dict
    after: dict
    preserved_keys: list[str] = field(default_factory=list)


def _load_profile_record(client: GrowthClient) -> tuple[dict, str | None]:
    existing = client.get_record(PROFILE_COLLECTION, "self")
    if not existing:
        return {}, None
    value = existing.get("value")
    cid = existing.get("cid")
    return (dict(value) if isinstance(value, dict) else {}), (str(cid) if cid else None)


def _merged_profile(value: dict, **updates: object) -> dict:
    merged = dict(value)
    merged["$type"] = PROFILE_COLLECTION
    merged.update(updates)
    return merged


def update_profile(client: GrowthClient, identity: Identity, *, dry_run: bool, logger: Logger) -> ProfileUpdateResult:
    value, cid = _load_profile_record(client)
    before = {key: value.get(key) for key in sorted(_MANAGED_PROFILE_KEYS)}
    after = {"description": identity.description, "displayName": identity.display_name}
    preserved = sorted(key for key in value if key not in _MANAGED_PROFILE_KEYS and key != "$type")
    if before == after:
        logger.info("Profile already up to date (display name + bio unchanged)")
        return ProfileUpdateResult(changed=False, dry_run=dry_run, before=before, after=after, preserved_keys=preserved)

    merged = _merged_profile(value, displayName=identity.display_name, description=identity.description)
    if dry_run:
        logger.info("[dry-run] would update profile record; preserving %s", ", ".join(preserved) or "nothing (no record yet)")
        logger.info("[dry-run] displayName: %r -> %r", before["displayName"], after["displayName"])
        logger.info("[dry-run] description:\n%s", identity.description)
        return ProfileUpdateResult(changed=True, dry_run=True, before=before, after=after, preserved_keys=preserved)

    client.put_record(PROFILE_COLLECTION, "self", merged, swap_record=cid)
    logger.info("Profile updated (display name + bio); preserved %s", ", ".join(preserved) or "nothing (new record)")
    return ProfileUpdateResult(changed=True, dry_run=False, before=before, after=after, preserved_keys=preserved)


# ---------------------------------------------------------------------------
# pinned intro thread
# ---------------------------------------------------------------------------


def _find_existing_post(client: GrowthClient, text: str, root_uri: str | None) -> dict | None:
    """An already-created thread post in our own repo: same text and, for
    replies, the same thread root. Covers the ambiguous write — createRecord
    reached the PDS but the response was lost — so a retry adopts the record
    instead of posting it twice."""
    try:
        records = client.list_records(POST_COLLECTION, limit=50)
    except GrowthClientError:
        return None
    for record in records:
        value = record.get("value") if isinstance(record.get("value"), dict) else {}
        if value.get("text") != text:
            continue
        reply = value.get("reply") if isinstance(value.get("reply"), dict) else None
        if root_uri is None:
            if reply:
                continue  # looking for a root post, this one is a reply
        else:
            record_root = str(((reply or {}).get("root") or {}).get("uri") or "")
            if record_root != root_uri:
                continue
        uri, cid = record.get("uri"), record.get("cid")
        if uri and cid:
            return {"uri": str(uri), "cid": str(cid)}
    return None


@dataclass(slots=True)
class PinResult:
    status: str                      # skipped | dry_run | pinned
    root_uri: str | None = None
    uris: list[str] = field(default_factory=list)
    posted_now: int = 0


def pin_intro_thread(
    client: GrowthClient,
    identity: Identity,
    ledger: GrowthLedger,
    *,
    dry_run: bool,
    logger: Logger,
    now: datetime | None = None,
) -> PinResult:
    """Post the intro thread (resume-safe) and pin its root post.

    Idempotent on the thread content hash: an unchanged thread that is already
    pinned is a no-op; a run that died mid-thread continues from the last post
    it recorded instead of posting the thread twice. A *changed* thread is
    posted again and re-pinned — the old thread stays up (no delete path).
    """
    thread_hash = identity.thread_hash()
    state = ledger.pinned_thread or {}
    same_thread = state.get("hash") == thread_hash
    posted: list[dict] = [p for p in (state.get("posts") or []) if isinstance(p, dict)] if same_thread else []

    if same_thread and state.get("pinned") and len(posted) == len(identity.intro_thread):
        logger.info("Intro thread already posted and pinned: %s", state.get("root_uri"))
        return PinResult(status="skipped", root_uri=state.get("root_uri"), uris=[p["uri"] for p in posted])

    if dry_run:
        for idx, text in enumerate(identity.intro_thread, start=1):
            marker = "(already posted)" if idx <= len(posted) else f"({grapheme_len(text)} graphemes)"
            logger.info("[dry-run] thread post %d/%d %s:\n%s", idx, len(identity.intro_thread), marker, text)
        logger.info("[dry-run] would pin the root post on the profile record")
        return PinResult(status="dry_run", root_uri=posted[0]["uri"] if posted else None, uris=[p["uri"] for p in posted])

    posted_now = 0
    for idx in range(len(posted), len(identity.intro_thread)):
        text = identity.intro_thread[idx]
        root_uri = posted[0]["uri"] if posted else None
        existing = _find_existing_post(client, text, root_uri)
        if existing:
            logger.info("Intro thread %d/%d already exists on the PDS, adopting %s", idx + 1, len(identity.intro_thread), existing["uri"])
            response: dict = existing
        else:
            reply = _reply_ref(posted[0], posted[-1]) if posted else None
            record = build_post_record(text, created_at=utc_now_iso(now), reply=reply)
            try:
                response = client.create_post(record)
            except GrowthClientError as exc:
                if exc.status is not None:
                    raise  # a definite rejection; nothing was created
                # Transport error: the write may have landed. Look before retrying.
                existing = _find_existing_post(client, text, root_uri)
                if not existing:
                    raise
                logger.warning("createRecord response lost for intro thread %d/%d; found %s on the PDS", idx + 1, len(identity.intro_thread), existing["uri"])
                response = existing
            posted_now += 1
        uri, cid = response.get("uri"), response.get("cid")
        if not uri or not cid:
            raise GrowthClientError("createRecord response missing uri/cid for intro thread post")
        posted.append({"uri": str(uri), "cid": str(cid)})
        ledger.pinned_thread = {
            "hash": thread_hash,
            "posts": posted,
            "root_uri": posted[0]["uri"],
            "root_cid": posted[0]["cid"],
            "pinned": False,
            "posted_at": utc_now_iso(now),
        }
        ledger.save()  # after every post: a failed run resumes instead of double-posting
        logger.info("Posted intro thread %d/%d: %s", idx + 1, len(identity.intro_thread), uri)

    root = posted[0]
    value, cid = _load_profile_record(client)
    merged = _merged_profile(value, pinnedPost={"uri": root["uri"], "cid": root["cid"]})
    client.put_record(PROFILE_COLLECTION, "self", merged, swap_record=cid)

    state = dict(ledger.pinned_thread or {})
    state.update({"hash": thread_hash, "posts": posted, "root_uri": root["uri"], "root_cid": root["cid"]})
    state["pinned"] = True
    state["pinned_at"] = utc_now_iso(now)
    ledger.pinned_thread = state
    ledger.save()
    logger.info("Pinned intro thread root %s", root["uri"])
    return PinResult(status="pinned", root_uri=root["uri"], uris=[p["uri"] for p in posted], posted_now=posted_now)
