from __future__ import annotations

import os
from logging import Logger

from src.models import FeedItem

# Small, CPU-friendly cross-encoder. Swap to "BAAI/bge-reranker-base" via
# BOARDWIRE_RERANKER_MODEL for higher quality at a higher latency cost.
DEFAULT_RERANKER_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# The reranker scores each candidate against this profile, biasing selection
# toward concrete, builder-relevant items that tend to go viral with engineers.
DEFAULT_QUERY = (
    "A new AI tool, model, framework, dataset, or release that software "
    "developers and AI engineers can use hands-on today. Concrete and "
    "technical, not opinion or speculation, and likely to spark strong "
    "interest among builders."
)


def _doc_text(item: FeedItem) -> str:
    title = (item.title or "").strip()
    summary = (item.summary or "").strip().replace("\n", " ")
    if summary:
        return f"{title}. {summary[:500]}"
    return title


class Reranker:
    """Cross-encoder reranker that reorders candidates by builder-virality fit.

    Degrades to a no-op (original order) whenever the model can't be loaded or
    scoring fails, so the funnel never breaks if fastembed/the weights are
    unavailable — matching how the embedding path handles missing models.
    """

    def __init__(
        self,
        model_name: str | None = None,
        query: str | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("BOARDWIRE_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
        self.query = query or os.getenv("BOARDWIRE_RERANKER_QUERY", DEFAULT_QUERY)
        self.logger = logger
        self._encoder = None
        self._load_failed = False

    def _ensure_encoder(self):
        if self._encoder is not None or self._load_failed:
            return self._encoder
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._encoder = TextCrossEncoder(model_name=self.model_name)
            if self.logger:
                self.logger.info("Reranker model loaded: %s", self.model_name)
        except Exception as exc:  # import error, unknown model, download failure
            self._load_failed = True
            if self.logger:
                self.logger.warning("Reranker unavailable (%s); keeping local order", exc)
        return self._encoder

    def rerank(self, items: list[FeedItem]) -> list[FeedItem]:
        """Return items reordered by descending relevance; input order on failure."""
        items = list(items)
        if len(items) < 2:
            return items

        encoder = self._ensure_encoder()
        if encoder is None:
            return items

        try:
            docs = [_doc_text(it) for it in items]
            scores = list(encoder.rerank(self.query, docs))
        except Exception as exc:
            if self.logger:
                self.logger.warning("Reranker scoring failed (%s); keeping local order", exc)
            return items

        if len(scores) != len(items):
            if self.logger:
                self.logger.warning(
                    "Reranker returned %d scores for %d items; keeping local order",
                    len(scores),
                    len(items),
                )
            return items

        ranked = sorted(zip(items, scores), key=lambda pair: float(pair[1]), reverse=True)
        if self.logger:
            for item, score in ranked[:8]:
                self.logger.info("Rerank score=%.4f | %s", float(score), item.title[:100])
        return [item for item, _ in ranked]
