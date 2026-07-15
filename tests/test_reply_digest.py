from __future__ import annotations

from logging import getLogger

from src.feedback import reply_digest as mod
from src.feedback.reply_digest import (
    ReplyDigestConfig,
    build_digest_text,
    collect_reply_candidates,
    load_reply_digest_config,
)

_LOGGER = getLogger("test")


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _search_payload() -> dict:
    return {
        "posts": [
            {
                "uri": "at://did:plc:aaa/app.bsky.feed.post/111",
                "author": {"handle": "builder.bsky.social"},
                "record": {"text": "Shipping an MCP server for our internal tools, works great"},
                "likeCount": 20,
                "replyCount": 4,
                "repostCount": 3,
            },
            {
                "uri": "at://did:plc:bbb/app.bsky.feed.post/222",
                "author": {"handle": "quiet.bsky.social"},
                "record": {"text": "low engagement post"},
                "likeCount": 1,
                "replyCount": 0,
                "repostCount": 0,
            },
            {
                "uri": "at://did:plc:ccc/app.bsky.feed.post/333",
                "author": {"handle": "boardwire.bsky.social"},
                "record": {"text": "our own post must be excluded"},
                "likeCount": 50,
                "replyCount": 5,
                "repostCount": 5,
            },
        ]
    }


def test_collect_filters_and_ranks(monkeypatch) -> None:
    calls: list = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return _Resp(200, _search_payload())

    monkeypatch.setattr(mod.requests, "get", fake_get)

    config = ReplyDigestConfig(keywords=["MCP"], max_posts=8, posts_per_keyword=5, min_engagement=5)
    candidates = collect_reply_candidates(config, _LOGGER, own_handle="boardwire.bsky.social")

    # Read-only: only GETs against the public search endpoint, never a POST.
    assert all("searchPosts" in c["url"] for c in calls)
    # Low-engagement and own posts filtered out.
    assert [c.author_handle for c in candidates] == ["builder.bsky.social"]
    assert candidates[0].engagement == 30  # 20 + 2*3 + 4


def test_digest_never_posts_to_bluesky(monkeypatch) -> None:
    """The digest path must not perform any write request to Bluesky."""
    posted: list = []

    def fake_get(url, **kwargs):
        return _Resp(200, _search_payload())

    def fake_post(url, **kwargs):  # any POST would be a violation unless it's Slack
        posted.append(url)
        return _Resp(200, {})

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "post", fake_post)
    monkeypatch.setenv("BLUESKY_HANDLE", "boardwire.bsky.social")
    # LLM drafting off (no providers configured in tests) → suggestion is None.
    import src.notifications.persona_voice as voice

    monkeypatch.setattr(voice, "draft_reply_suggestion", lambda *a, **k: "Try pairing it with a local runner?")
    import src.notifications.slack as slack

    slack_calls: list = []
    monkeypatch.setattr(slack, "reply_digest", lambda text: slack_calls.append(text))

    count = mod.run_reply_digest(_LOGGER, config=ReplyDigestConfig(keywords=["MCP"], max_posts=3, posts_per_keyword=3, min_engagement=5))

    assert count == 1
    assert posted == []  # zero POSTs from this module: nothing published anywhere
    assert len(slack_calls) == 1
    assert "suggestions only" in slack_calls[0].lower() or "nothing was posted" in slack_calls[0].lower()


def test_digest_text_marks_missing_suggestions(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        return _Resp(200, _search_payload())

    monkeypatch.setattr(mod.requests, "get", fake_get)
    config = ReplyDigestConfig(keywords=["MCP"], max_posts=3, posts_per_keyword=3, min_engagement=5)
    candidates = collect_reply_candidates(config, _LOGGER)
    text = build_digest_text(candidates)

    assert "nothing was posted" in text
    assert "bsky.app/profile/builder.bsky.social/post/111" in text
    assert "no draft available" in text


def test_load_config_defaults(tmp_path) -> None:
    config = load_reply_digest_config(tmp_path / "missing.json")
    assert config.keywords  # falls back to niche defaults
    assert config.max_posts >= 1
