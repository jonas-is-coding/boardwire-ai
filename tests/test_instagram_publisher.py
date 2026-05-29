from __future__ import annotations

import requests

from src.publisher import instagram_publisher as mod
from src.publisher.instagram_publisher import InstagramPublisher


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _publisher() -> InstagramPublisher:
    return InstagramPublisher(
        user_id="123",
        access_token="tok",
        image_base_url="https://cdn.example/cards/",
        api_version="v21.0",
    )


def test_full_publish_flow(monkeypatch) -> None:
    calls: list = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if url.endswith("/123/media"):
            return _Resp(200, {"id": "container-1"})
        if url.endswith("/123/media_publish"):
            return _Resp(200, {"id": "media-77"})
        if url.endswith("/media-77"):
            return _Resp(200, {"permalink": "https://www.instagram.com/p/abc/"})
        return _Resp(404, {})

    monkeypatch.setattr(mod.requests, "request", fake_request)

    result = _publisher().publish(
        post="AI release", source_link="https://example.com/x", image_path="generated/cards/77.png"
    )

    assert result.success is True
    assert result.external_id == "media-77"
    assert result.url == "https://www.instagram.com/p/abc/"
    # Container is created with a public image URL derived from the filename.
    container = calls[0]["kwargs"]["data"]
    assert container["image_url"] == "https://cdn.example/cards/77.png"
    assert "🔗 https://example.com/x" in container["caption"]
    assert [c["method"] for c in calls] == ["POST", "POST", "GET"]


def test_missing_image_fails(monkeypatch) -> None:
    result = _publisher().publish(post="hi")
    assert result.success is False
    assert "image is required" in (result.error or "")


def test_missing_base_url_fails() -> None:
    pub = InstagramPublisher(user_id="123", access_token="tok", image_base_url="")
    result = pub.publish(post="hi", image_path="generated/cards/77.png")
    assert result.success is False
    assert "INSTAGRAM_IMAGE_BASE_URL" in (result.error or "")


def test_container_failure_short_circuits(monkeypatch) -> None:
    calls: list = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        return _Resp(400, {"error": "bad"})

    monkeypatch.setattr(mod.requests, "request", fake_request)
    result = _publisher().publish(post="hi", image_path="generated/cards/77.png")

    assert result.success is False
    assert "container creation failed" in (result.error or "")
    # media_publish is never attempted after a container failure.
    assert all("media_publish" not in url for url in calls)


def test_request_error_is_reported(monkeypatch) -> None:
    def boom(method, url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(mod.requests, "request", boom)
    result = _publisher().publish(post="hi", image_path="generated/cards/77.png")

    assert result.success is False
    assert "request error" in (result.error or "")
