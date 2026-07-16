from __future__ import annotations

from pathlib import Path

from src.publisher import bluesky_publisher as mod
from src.publisher.bluesky_publisher import (
    BlueskyPublisher,
    ThreadPost,
    _compose_text_with_link,
    _rkey_from_at_uri,
    build_reply_ref,
)
from src.publisher.base import PublishResult
from src.publisher.dry_run_publisher import DryRunPublisher


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _patch_requests(monkeypatch, calls: list, fail_create_at: int | None = None) -> None:
    """Fake Bluesky endpoints. fail_create_at: 1-based createRecord call index to 500."""
    create_count = {"n": 0}

    def fake_post(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        if url.endswith("createSession"):
            return _Resp(200, {"accessJwt": "jwt", "did": "did:plc:test"})
        if url.endswith("uploadBlob"):
            return _Resp(200, {"blob": {"$type": "blob", "ref": {"$link": "cid-blob"}}})
        if url.endswith("deleteRecord"):
            return _Resp(200, {})
        if url.endswith("createRecord"):
            create_count["n"] += 1
            if fail_create_at is not None and create_count["n"] == fail_create_at:
                return _Resp(500, {})
            n = create_count["n"]
            return _Resp(200, {"uri": f"at://did:plc:test/app.bsky.feed.post/{n}", "cid": f"cid-{n}"})
        return _Resp(404, {})

    monkeypatch.setattr(mod.requests, "post", fake_post)


def _created_records(calls: list) -> list[dict]:
    return [
        c["kwargs"]["json"]["record"]
        for c in calls
        if c["url"].endswith("createRecord")
    ]


def test_compose_text_with_link_facet_offsets_ascii() -> None:
    text, facets = _compose_text_with_link("Hello world", "https://example.com/a")
    assert text == "Hello world\n\n🔗 https://example.com/a"
    idx = facets[0]["index"]
    assert text.encode("utf-8")[idx["byteStart"] : idx["byteEnd"]].decode() == "https://example.com/a"


def test_compose_text_with_link_multibyte_body_offsets() -> None:
    body = "Größeres Modell 🚀 läuft überall lokal.\n\n#LocalLLM #AI"
    url = "https://example.com/ünïcode-path"
    text, facets = _compose_text_with_link(body, url)
    raw = text.encode("utf-8")
    assert len(raw) <= 300
    idx = facets[0]["index"]
    assert raw[idx["byteStart"] : idx["byteEnd"]].decode("utf-8") == url
    assert "#LocalLLM #AI" in text


def test_compose_text_with_link_trims_at_word_boundary_only() -> None:
    body = "word " * 80  # far over budget
    url = "https://example.com/some/long/path"
    text, facets = _compose_text_with_link(body.strip(), url)
    assert len(text.encode("utf-8")) <= 300
    assert text.endswith(url)
    prose = text.split("\n\n")[0].rstrip("…")
    for token in prose.split():
        assert token == "word"


def test_publish_reads_uri_and_cid(monkeypatch, tmp_path: Path) -> None:
    calls: list = []
    _patch_requests(monkeypatch, calls)
    image = tmp_path / "card.png"
    image.write_bytes(b"\x89PNG")
    pub = BlueskyPublisher(handle="h", app_password="p")

    result = pub.publish(post="hello", source_link="https://x.com/a", image_path=str(image))

    assert result.success is True
    assert result.external_id == "at://did:plc:test/app.bsky.feed.post/1"
    assert result.cid == "cid-1"


def test_publish_thread_chains_reply_refs(monkeypatch, tmp_path: Path) -> None:
    calls: list = []
    _patch_requests(monkeypatch, calls)
    image = tmp_path / "card.png"
    image.write_bytes(b"\x89PNG")
    pub = BlueskyPublisher(handle="h", app_password="p")

    result = pub.publish_thread(
        [
            ThreadPost(post="Hook post\n\n#AI #MCP", image_path=str(image), image_alt="card"),
            ThreadPost(post="Concrete facts here."),
            ThreadPost(post="Anyone running this?", source_link="https://example.com/story"),
        ]
    )

    assert result.success is True
    assert len(result.results) == 3
    records = _created_records(calls)
    assert "reply" not in records[0]
    root_ref = {"uri": "at://did:plc:test/app.bsky.feed.post/1", "cid": "cid-1"}
    assert records[1]["reply"] == {"root": root_ref, "parent": root_ref}
    assert records[2]["reply"] == {
        "root": root_ref,
        "parent": {"uri": "at://did:plc:test/app.bsky.feed.post/2", "cid": "cid-2"},
    }
    # Only post 1 carries the image; post 3 carries the link facet.
    assert "embed" in records[0]
    assert "embed" not in records[1]
    assert records[2]["facets"][0]["features"][0]["uri"] == "https://example.com/story"
    # Session created exactly once for the whole thread.
    assert sum(1 for c in calls if c["url"].endswith("createSession")) == 1


def test_publish_thread_aborts_on_failure_and_returns_partial(monkeypatch) -> None:
    calls: list = []
    _patch_requests(monkeypatch, calls, fail_create_at=2)
    pub = BlueskyPublisher(handle="h", app_password="p")

    result = pub.publish_thread(
        [
            ThreadPost(post="Post one"),
            ThreadPost(post="Post two"),
            ThreadPost(post="Post three"),
        ]
    )

    assert result.success is False
    # Post 1 succeeded and is reported so the caller can record partial state.
    assert result.uris == ["at://did:plc:test/app.bsky.feed.post/1"]
    assert "post 2" in result.error.lower()
    # Post 3 was never attempted (abort, no double-post risk).
    assert len(_created_records(calls)) == 2


def test_build_reply_ref_shape() -> None:
    root = PublishResult(success=True, platform="bluesky", external_id="at://r", cid="cid-r")
    parent = PublishResult(success=True, platform="bluesky", external_id="at://p", cid="cid-p")
    assert build_reply_ref(root, parent) == {
        "root": {"uri": "at://r", "cid": "cid-r"},
        "parent": {"uri": "at://p", "cid": "cid-p"},
    }


def test_dry_run_publisher_simulates_threads() -> None:
    pub = DryRunPublisher()
    result = pub.publish_thread([ThreadPost(post="a"), ThreadPost(post="b"), ThreadPost(post="c")])
    assert result.success is True
    assert len(result.results) == 3
    assert all(r.cid for r in result.results)
    assert len(set(result.uris)) == 3


def test_rkey_from_at_uri() -> None:
    assert _rkey_from_at_uri("at://did:plc:test/app.bsky.feed.post/3abc") == "3abc"
    assert _rkey_from_at_uri("not-a-uri") is None


def test_delete_post_sends_delete_record(monkeypatch) -> None:
    calls: list = []
    _patch_requests(monkeypatch, calls)
    pub = BlueskyPublisher(handle="h", app_password="p")

    result = pub.delete_post("at://did:plc:test/app.bsky.feed.post/3abc")

    assert result.success is True
    delete_calls = [c for c in calls if c["url"].endswith("deleteRecord")]
    assert len(delete_calls) == 1
    assert delete_calls[0]["kwargs"]["json"] == {
        "repo": "did:plc:test",
        "collection": "app.bsky.feed.post",
        "rkey": "3abc",
    }
