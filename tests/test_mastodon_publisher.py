from __future__ import annotations

from pathlib import Path

import requests

from src.publisher import mastodon_publisher as mod
from src.publisher.mastodon_publisher import MastodonPublisher


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _patch_requests(monkeypatch, calls: list) -> None:
    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if url.endswith("/api/v2/media"):
            return _Resp(200, {"id": "media-1"})
        if url.endswith("/api/v1/statuses"):
            return _Resp(200, {"id": "status-99", "url": "https://mastodon.social/@bw/status-99"})
        return _Resp(404, {})

    monkeypatch.setattr(mod.requests, "request", fake_request)


def test_text_only_post_succeeds(monkeypatch) -> None:
    calls: list = []
    _patch_requests(monkeypatch, calls)
    pub = MastodonPublisher(base_url="https://mastodon.social/", access_token="tok")

    result = pub.publish(post="An AI model ships today", source_link="https://example.com/x")

    assert result.success is True
    assert result.platform == "mastodon"
    assert result.external_id == "status-99"
    assert result.url == "https://mastodon.social/@bw/status-99"
    # Only the status call is made when there is no image.
    assert [c["url"] for c in calls] == ["https://mastodon.social/api/v1/statuses"]
    # Trailing slash on base_url is normalized away.
    assert "//api" not in calls[0]["url"]
    posted_status = calls[0]["kwargs"]["data"]["status"]
    assert "🔗 https://example.com/x" in posted_status


def test_post_with_image_uploads_media_first(monkeypatch, tmp_path: Path) -> None:
    calls: list = []
    _patch_requests(monkeypatch, calls)
    image = tmp_path / "card.png"
    image.write_bytes(b"\x89PNG\r\n")
    pub = MastodonPublisher(base_url="https://mastodon.social", access_token="tok")

    result = pub.publish(post="hello", image_path=str(image), image_alt="alt")

    assert result.success is True
    assert [c["url"] for c in calls] == [
        "https://mastodon.social/api/v2/media",
        "https://mastodon.social/api/v1/statuses",
    ]
    assert calls[1]["kwargs"]["data"]["media_ids[]"] == ["media-1"]


def test_missing_image_file_fails_fast(monkeypatch) -> None:
    calls: list = []
    _patch_requests(monkeypatch, calls)
    pub = MastodonPublisher(base_url="https://mastodon.social", access_token="tok")

    result = pub.publish(post="hello", image_path="/no/such/card.png")

    assert result.success is False
    assert "not found" in (result.error or "")
    assert calls == []


def test_request_error_is_reported(monkeypatch) -> None:
    def boom(method, url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(mod.requests, "request", boom)
    pub = MastodonPublisher(base_url="https://mastodon.social", access_token="tok")

    result = pub.publish(post="hello")

    assert result.success is False
    assert "request error" in (result.error or "")
