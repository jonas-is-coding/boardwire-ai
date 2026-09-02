from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.composer import byte_len
from src.growth.client import GrowthClientError
from src.growth.ledger import GrowthLedger
from src.growth.profile import (
    MAX_POST_GRAPHEMES,
    Identity,
    build_post_record,
    grapheme_len,
    link_facets,
    load_identity,
    pin_intro_thread,
    update_profile,
    validate_identity,
)

_LOGGER = logging.getLogger("test")
_NOW = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)
_AVATAR = {"$type": "blob", "ref": {"$link": "bafy-avatar"}, "mimeType": "image/png", "size": 1}
_BANNER = {"$type": "blob", "ref": {"$link": "bafy-banner"}, "mimeType": "image/png", "size": 1}


class FakeClient:
    def __init__(self, profile_value: dict | None = None, *, cid: str = "cid-old", fail_post_at: int | None = None) -> None:
        self.records: dict[str, tuple[dict, str]] = {}
        if profile_value is not None:
            self.records["self"] = ({"$type": "app.bsky.actor.profile", **profile_value}, cid)
        self.puts: list[dict] = []
        self.posts: list[dict] = []
        self.fail_post_at = fail_post_at
        self.did = "did:plc:me"

    def get_record(self, collection: str, rkey: str, repo: str | None = None) -> dict | None:
        if rkey not in self.records:
            return None
        value, cid = self.records[rkey]
        return {"uri": f"at://did:plc:me/{collection}/{rkey}", "cid": cid, "value": value}

    def put_record(self, collection: str, rkey: str, record: dict, swap_record: str | None = None) -> dict:
        self.puts.append({"collection": collection, "rkey": rkey, "record": record, "swap": swap_record})
        cid = f"cid-put-{len(self.puts)}"
        self.records[rkey] = (record, cid)
        return {"uri": f"at://did:plc:me/{collection}/{rkey}", "cid": cid}

    def create_post(self, record: dict) -> dict:
        n = len(self.posts) + 1
        if self.fail_post_at == n:
            raise GrowthClientError("pds down", status=502)
        self.posts.append(record)
        return {"uri": f"at://did:plc:me/app.bsky.feed.post/{n}", "cid": f"cid-post-{n}"}


def _identity(thread: list[str] | None = None) -> Identity:
    return Identity(
        display_name="Boardwire",
        description="AI news, built in the open.",
        intro_thread=thread or ["Post one 🧵 1/3", "Post two https://github.com/jonas-is-coding/boardwire-ai. 2/3", "Post three 3/3"],
    )


def _ledger(tmp_path: Path) -> GrowthLedger:
    return GrowthLedger.load(tmp_path / "ledger.json")


# --- identity ----------------------------------------------------------------


def test_repo_identity_config_is_valid() -> None:
    identity = load_identity()
    assert identity.display_name
    assert len(identity.intro_thread) == 6
    assert all(grapheme_len(t) <= MAX_POST_GRAPHEMES for t in identity.intro_thread)
    assert "github.com/jonas-is-coding/boardwire-ai" in identity.intro_thread[-1]


def test_validate_identity_reports_every_limit() -> None:
    problems = validate_identity(Identity(display_name="x" * 65, description="y" * 257, intro_thread=["", "z" * 301]))
    joined = "\n".join(problems)
    assert "display_name is 65 graphemes" in joined
    assert "description is 257 graphemes" in joined
    assert "intro_thread[1] is empty" in joined
    assert "intro_thread[2] is 301 graphemes" in joined


def test_load_identity_raises_on_invalid_file(tmp_path) -> None:
    path = tmp_path / "identity.json"
    path.write_text(json.dumps({"display_name": "ok", "description": "d" * 300, "intro_thread": ["fine"]}))
    with pytest.raises(ValueError) as exc:
        load_identity(path)
    assert "description is 300 graphemes" in str(exc.value)
    with pytest.raises(ValueError):
        load_identity(tmp_path / "missing.json")


def test_load_identity_accepts_dict_thread_items(tmp_path) -> None:
    path = tmp_path / "identity.json"
    path.write_text(json.dumps({"display_name": "ok", "description": "bio", "intro_thread": [{"text": " one "}, "two"]}))
    assert load_identity(path).intro_thread == ["one", "two"]


# --- post records ------------------------------------------------------------


def test_link_facets_use_byte_offsets_and_strip_trailing_punctuation() -> None:
    text = "🧵 see https://example.com/x. now"
    facets = link_facets(text)
    assert len(facets) == 1
    url = "https://example.com/x"
    assert facets[0]["features"][0]["uri"] == url
    start = byte_len("🧵 see ")
    assert facets[0]["index"] == {"byteStart": start, "byteEnd": start + byte_len(url)}
    assert text.encode("utf-8")[start : start + byte_len(url)].decode() == url


def test_build_post_record_sets_reply_and_facets() -> None:
    record = build_post_record("hi https://a.b/c", created_at="2026-09-02T09:00:00Z", reply={"root": {}, "parent": {}})
    assert record["$type"] == "app.bsky.feed.post"
    assert record["reply"] == {"root": {}, "parent": {}}
    assert record["facets"][0]["features"][0]["uri"] == "https://a.b/c"
    assert "facets" not in build_post_record("plain", created_at="t")


# --- profile record ----------------------------------------------------------


def test_update_profile_merges_onto_live_record_and_preserves_blobs() -> None:
    live = {
        "displayName": "old name",
        "description": "old bio",
        "avatar": _AVATAR,
        "banner": _BANNER,
        "pinnedPost": {"uri": "at://p", "cid": "c"},
        "labels": {"$type": "com.atproto.label.defs#selfLabels", "values": []},
    }
    client = FakeClient(live, cid="cid-live")
    result = update_profile(client, _identity(), dry_run=False, logger=_LOGGER)

    assert result.changed and not result.dry_run
    assert result.preserved_keys == ["avatar", "banner", "labels", "pinnedPost"]
    assert len(client.puts) == 1
    put = client.puts[0]
    assert put["rkey"] == "self" and put["swap"] == "cid-live"
    record = put["record"]
    assert record["displayName"] == "Boardwire"
    assert record["description"] == "AI news, built in the open."
    assert record["avatar"] == _AVATAR and record["banner"] == _BANNER
    assert record["pinnedPost"] == {"uri": "at://p", "cid": "c"}
    assert record["$type"] == "app.bsky.actor.profile"


def test_update_profile_is_noop_when_unchanged() -> None:
    client = FakeClient({"displayName": "Boardwire", "description": "AI news, built in the open.", "avatar": _AVATAR})
    result = update_profile(client, _identity(), dry_run=False, logger=_LOGGER)
    assert not result.changed
    assert client.puts == []


def test_update_profile_dry_run_writes_nothing() -> None:
    client = FakeClient({"displayName": "old", "description": "old", "avatar": _AVATAR})
    result = update_profile(client, _identity(), dry_run=True, logger=_LOGGER)
    assert result.changed and result.dry_run
    assert client.puts == []


def test_update_profile_creates_record_when_missing() -> None:
    client = FakeClient(None)
    update_profile(client, _identity(), dry_run=False, logger=_LOGGER)
    assert client.puts[0]["swap"] is None
    assert client.puts[0]["record"]["$type"] == "app.bsky.actor.profile"


# --- pinned thread -----------------------------------------------------------


def test_pin_thread_chains_replies_pins_root_and_is_idempotent(tmp_path) -> None:
    client = FakeClient({"displayName": "Boardwire", "avatar": _AVATAR}, cid="cid-live")
    ledger = _ledger(tmp_path)
    identity = _identity()

    result = pin_intro_thread(client, identity, ledger, dry_run=False, logger=_LOGGER, now=_NOW)

    assert result.status == "pinned" and result.posted_now == 3
    assert result.root_uri == "at://did:plc:me/app.bsky.feed.post/1"
    assert len(client.posts) == 3
    assert "reply" not in client.posts[0]
    assert client.posts[1]["reply"] == {
        "root": {"uri": "at://did:plc:me/app.bsky.feed.post/1", "cid": "cid-post-1"},
        "parent": {"uri": "at://did:plc:me/app.bsky.feed.post/1", "cid": "cid-post-1"},
    }
    assert client.posts[2]["reply"]["parent"] == {"uri": "at://did:plc:me/app.bsky.feed.post/2", "cid": "cid-post-2"}
    assert client.posts[1]["facets"][0]["features"][0]["uri"] == "https://github.com/jonas-is-coding/boardwire-ai"
    assert client.posts[0]["createdAt"] == "2026-09-02T09:00:00Z"

    # pin merged onto the live profile record
    assert len(client.puts) == 1
    put = client.puts[0]
    assert put["swap"] == "cid-live"
    assert put["record"]["pinnedPost"] == {"uri": result.root_uri, "cid": "cid-post-1"}
    assert put["record"]["avatar"] == _AVATAR
    assert put["record"]["displayName"] == "Boardwire"

    state = GrowthLedger.load(tmp_path / "ledger.json").pinned_thread
    assert state["pinned"] is True
    assert state["hash"] == identity.thread_hash()
    assert [p["uri"] for p in state["posts"]] == result.uris

    again = pin_intro_thread(client, identity, ledger, dry_run=False, logger=_LOGGER, now=_NOW)
    assert again.status == "skipped"
    assert len(client.posts) == 3 and len(client.puts) == 1


def test_pin_thread_resumes_after_partial_failure(tmp_path) -> None:
    identity = _identity()
    broken = FakeClient({"displayName": "Boardwire"}, fail_post_at=2)
    ledger = _ledger(tmp_path)

    with pytest.raises(GrowthClientError):
        pin_intro_thread(broken, identity, ledger, dry_run=False, logger=_LOGGER, now=_NOW)

    state = GrowthLedger.load(tmp_path / "ledger.json").pinned_thread
    assert state["pinned"] is False
    assert [p["uri"] for p in state["posts"]] == ["at://did:plc:me/app.bsky.feed.post/1"]

    healthy = FakeClient({"displayName": "Boardwire"})
    result = pin_intro_thread(healthy, identity, GrowthLedger.load(tmp_path / "ledger.json"), dry_run=False, logger=_LOGGER, now=_NOW)

    assert result.status == "pinned" and result.posted_now == 2
    assert len(healthy.posts) == 2  # only the two missing posts
    assert healthy.posts[0]["text"] == identity.intro_thread[1]
    assert healthy.posts[0]["reply"]["root"] == {"uri": "at://did:plc:me/app.bsky.feed.post/1", "cid": "cid-post-1"}
    assert healthy.puts[0]["record"]["pinnedPost"]["uri"] == "at://did:plc:me/app.bsky.feed.post/1"


def test_pin_thread_dry_run_writes_nothing(tmp_path) -> None:
    client = FakeClient({"displayName": "Boardwire"})
    result = pin_intro_thread(client, _identity(), _ledger(tmp_path), dry_run=True, logger=_LOGGER, now=_NOW)
    assert result.status == "dry_run"
    assert client.posts == [] and client.puts == []
    assert not (tmp_path / "ledger.json").exists()


def test_changed_thread_is_reposted_and_repinned(tmp_path) -> None:
    client = FakeClient({"displayName": "Boardwire"})
    ledger = _ledger(tmp_path)
    pin_intro_thread(client, _identity(), ledger, dry_run=False, logger=_LOGGER, now=_NOW)

    changed = _identity(thread=["New one", "New two"])
    result = pin_intro_thread(client, changed, ledger, dry_run=False, logger=_LOGGER, now=_NOW)

    assert result.status == "pinned" and result.posted_now == 2
    assert result.root_uri == "at://did:plc:me/app.bsky.feed.post/4"
    assert client.puts[-1]["record"]["pinnedPost"]["uri"] == result.root_uri
    assert ledger.pinned_thread["hash"] == changed.thread_hash()
