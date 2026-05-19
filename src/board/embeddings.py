from __future__ import annotations

import json
from logging import Logger
from pathlib import Path
from typing import Iterable

import numpy as np

from src.models import FeedItem

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384


def _build_text(item: FeedItem) -> str:
    source = (item.source or "").strip()
    title = (item.title or "").strip()
    summary = (item.summary or "").strip().replace("\n", " ")
    head = f"{source}: {title}" if source else title
    if not summary:
        return head
    return f"{head}. {summary[:500]}"


class EmbeddingService:
    """fastembed wrapper with disk cache keyed by link."""

    def __init__(
        self,
        cache_path: Path,
        model_name: str = DEFAULT_MODEL,
        logger: Logger | None = None,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.model_name = model_name
        self.logger = logger
        self._model = None
        self._cache: dict[str, list[float]] = self._load_cache()

    def _load_cache(self) -> dict[str, list[float]]:
        if not self.cache_path.exists():
            return {}
        try:
            raw = json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            if self.logger:
                self.logger.warning("Embedding cache unreadable, starting empty: %s", exc)
            return {}
        if not isinstance(raw, dict):
            return {}
        cleaned: dict[str, list[float]] = {}
        for link, vec in raw.items():
            if isinstance(vec, list) and len(vec) == DEFAULT_DIM:
                cleaned[link] = vec
        return cleaned

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.cache_path.write_text(json.dumps(self._cache))
        except OSError as exc:
            if self.logger:
                self.logger.warning("Embedding cache save failed: %s", exc)

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from fastembed import TextEmbedding

        if self.logger:
            self.logger.info("Loading embedding model: %s", self.model_name)
        self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_items(self, items: Iterable[FeedItem]) -> dict[str, np.ndarray]:
        items_list = list(items)
        result: dict[str, np.ndarray] = {}

        to_embed: list[tuple[str, str]] = []
        for item in items_list:
            if not item.link:
                continue
            cached = self._cache.get(item.link)
            if cached is not None:
                result[item.link] = np.asarray(cached, dtype=np.float32)
            else:
                to_embed.append((item.link, _build_text(item)))

        if to_embed:
            model = self._ensure_model()
            texts = [text for _, text in to_embed]
            if self.logger:
                self.logger.info(
                    "Embedding %d new items (cache hits: %d)",
                    len(texts),
                    len(result),
                )
            vectors = list(model.embed(texts))
            for (link, _), vec in zip(to_embed, vectors):
                arr = np.asarray(vec, dtype=np.float32)
                self._cache[link] = arr.tolist()
                result[link] = arr
            self._save_cache()
        elif self.logger:
            self.logger.info("All %d items served from embedding cache", len(result))

        return result

    def prune_cache(self, keep_links: set[str]) -> int:
        before = len(self._cache)
        self._cache = {k: v for k, v in self._cache.items() if k in keep_links}
        removed = before - len(self._cache)
        if removed:
            self._save_cache()
        return removed
