from __future__ import annotations

from logging import getLogger
from pathlib import Path

from src.cards import github_og as mod
from src.cards.github_og import fetch_github_og_image, github_og_url

_LOGGER = getLogger("test")


class _Resp:
    def __init__(self, status_code: int, headers: dict, content: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content


def test_og_url_shape() -> None:
    assert github_og_url("mistralai", "mistral") == "https://opengraph.githubassets.com/1/mistralai/mistral"


def test_fetch_success_writes_image(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mod.requests,
        "get",
        lambda url, **kw: _Resp(200, {"Content-Type": "image/png"}, b"\x89PNGdata"),
    )
    out = tmp_path / "card.png"
    result = fetch_github_og_image("x", "y", out, logger=_LOGGER)
    assert result == out
    assert out.read_bytes() == b"\x89PNGdata"


def test_fetch_non_200_returns_none(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.requests, "get", lambda url, **kw: _Resp(404, {}, b""))
    assert fetch_github_og_image("x", "y", tmp_path / "c.png", logger=_LOGGER) is None


def test_fetch_non_image_content_type_returns_none(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mod.requests,
        "get",
        lambda url, **kw: _Resp(200, {"Content-Type": "text/html"}, b"<html>"),
    )
    assert fetch_github_og_image("x", "y", tmp_path / "c.png", logger=_LOGGER) is None


def test_fetch_network_error_returns_none(monkeypatch, tmp_path: Path) -> None:
    import requests

    def boom(url, **kw):
        raise requests.RequestException("network down")

    monkeypatch.setattr(mod.requests, "get", boom)
    assert fetch_github_og_image("x", "y", tmp_path / "c.png", logger=_LOGGER) is None


def test_fetch_empty_owner_repo_returns_none(tmp_path: Path) -> None:
    assert fetch_github_og_image("", "y", tmp_path / "c.png") is None
    assert fetch_github_og_image("x", "", tmp_path / "c.png") is None


# --- variant selection (deterministic 50/50, GitHub-only) ------------------

def test_variant_selection_deterministic_and_github_only() -> None:
    import src.main as main

    non_github = {"id": "abc", "source_item": {"link": "https://blog.example.com/post"}}
    assert main._select_card_variant(non_github) == "editorial"

    # GitHub items split ~50/50 across ids, and the choice is stable per id.
    github_variants = []
    for i in range(200):
        item = {"id": f"id-{i}", "source_item": {"link": "https://github.com/o/r"}}
        v = main._select_card_variant(item)
        assert v in {"editorial", "github_og"}
        assert v == main._select_card_variant(item)  # stable
        github_variants.append(v)
    share = github_variants.count("github_og") / len(github_variants)
    assert 0.35 < share < 0.65
