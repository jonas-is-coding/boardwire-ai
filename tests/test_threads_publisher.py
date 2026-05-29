from __future__ import annotations

import requests

from src.publisher import threads_publisher as mod
from src.publisher.threads_publisher import ThreadsPublisher


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _fake(monkeypatch, calls: list) -> None:
    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if url.endswith("/123/threads"):
            return _Resp(200, {"id": "container-1"})
        if url.endswith("/123/threads_publish"):
            return _Resp(200, {"id": "thread-55"})
        if url.endswith("/thread-55"):
            return _Resp(200, {"permalink": "https://www.threads.net/@bw/post/55"})
        return _Resp(404, {})

    monkeypatch.setattr(mod.requests, "request", fake_request)


def test_text_only_post(monkeypatch) -> None:
    calls: list = []
    _fake(monkeypatch, calls)
    pub = ThreadsPublisher(user_id="123", access_token="tok", api_version="v1.0")

    result = pub.publish(post="AI release", source_link="https://example.com/x")

    assert result.success is True
    assert result.external_id == "thread-55"
    assert result.url == "https://www.threads.net/@bw/post/55"
    container = calls[0]["kwargs"]["data"]
    assert container["media_type"] == "TEXT"
    assert "image_url" not in container
    assert "🔗 https://example.com/x" in container["text"]


def test_image_post_when_base_url_set(monkeypatch) -> None:
    calls: list = []
    _fake(monkeypatch, calls)
    pub = ThreadsPublisher(
        user_id="123",
        access_token="tok",
        image_base_url="https://cdn.example/cards/",
        api_version="v1.0",
    )

    result = pub.publish(post="hi", image_path="generated/cards/55.png")

    assert result.success is True
    container = calls[0]["kwargs"]["data"]
    assert container["media_type"] == "IMAGE"
    assert container["image_url"] == "https://cdn.example/cards/55.png"


def test_image_path_without_base_url_falls_back_to_text(monkeypatch) -> None:
    calls: list = []
    _fake(monkeypatch, calls)
    pub = ThreadsPublisher(user_id="123", access_token="tok", api_version="v1.0")

    result = pub.publish(post="hi", image_path="generated/cards/55.png")

    assert result.success is True
    assert calls[0]["kwargs"]["data"]["media_type"] == "TEXT"


def test_publish_failure_reported(monkeypatch) -> None:
    def fake_request(method, url, **kwargs):
        if url.endswith("/123/threads"):
            return _Resp(200, {"id": "container-1"})
        return _Resp(400, {})

    monkeypatch.setattr(mod.requests, "request", fake_request)
    pub = ThreadsPublisher(user_id="123", access_token="tok", api_version="v1.0")

    result = pub.publish(post="hi")
    assert result.success is False
    assert "publish failed" in (result.error or "")


def test_request_error_is_reported(monkeypatch) -> None:
    def boom(method, url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(mod.requests, "request", boom)
    pub = ThreadsPublisher(user_id="123", access_token="tok", api_version="v1.0")

    result = pub.publish(post="hi")
    assert result.success is False
    assert "request error" in (result.error or "")
