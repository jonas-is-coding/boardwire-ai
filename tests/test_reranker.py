import logging
from datetime import datetime, timezone

from src.board.reranker import Reranker, _doc_text
from src.models import FeedItem

_LOGGER = logging.getLogger("test")


def _item(title: str, summary: str = "") -> FeedItem:
    return FeedItem(
        source="src",
        title=title,
        link=f"https://example.com/{title.replace(' ', '-')}",
        summary=summary,
        published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )


class _FakeEncoder:
    """Returns a preset score per document text substring."""

    def __init__(self, scores_by_title: dict[str, float]) -> None:
        self.scores_by_title = scores_by_title

    def rerank(self, query, documents):
        out = []
        for doc in documents:
            score = 0.0
            for key, val in self.scores_by_title.items():
                if key in doc:
                    score = val
                    break
            out.append(score)
        return out


def test_doc_text_combines_title_and_summary() -> None:
    assert _doc_text(_item("Title", "Body")) == "Title. Body"
    assert _doc_text(_item("Title")) == "Title"


def test_rerank_noop_when_encoder_unavailable(monkeypatch) -> None:
    r = Reranker(logger=_LOGGER)
    monkeypatch.setattr(r, "_ensure_encoder", lambda: None)
    items = [_item("a"), _item("b"), _item("c")]
    assert r.rerank(items) == items


def test_rerank_orders_by_score(monkeypatch) -> None:
    r = Reranker(logger=_LOGGER)
    fake = _FakeEncoder({"low": 0.1, "mid": 0.5, "high": 0.9})
    monkeypatch.setattr(r, "_ensure_encoder", lambda: fake)

    items = [_item("low item"), _item("high item"), _item("mid item")]
    ranked = r.rerank(items)
    assert [it.title for it in ranked] == ["high item", "mid item", "low item"]


def test_rerank_single_item_is_passthrough(monkeypatch) -> None:
    r = Reranker(logger=_LOGGER)
    called = {"n": 0}

    def _fail():
        called["n"] += 1
        raise AssertionError("encoder should not load for <2 items")

    monkeypatch.setattr(r, "_ensure_encoder", _fail)
    items = [_item("only")]
    assert r.rerank(items) == items
    assert called["n"] == 0


def test_rerank_score_count_mismatch_keeps_order(monkeypatch) -> None:
    class _BadEncoder:
        def rerank(self, query, documents):
            return [0.5]  # wrong length

    r = Reranker(logger=_LOGGER)
    monkeypatch.setattr(r, "_ensure_encoder", lambda: _BadEncoder())
    items = [_item("a"), _item("b")]
    assert r.rerank(items) == items
