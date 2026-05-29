from __future__ import annotations

import math
from datetime import datetime, timezone
from logging import Logger
from pathlib import Path
from typing import Any

import numpy as np

from src.board.embeddings import DEFAULT_MODEL, EmbeddingService
from src.config import EMBEDDINGS_CACHE_PATH, VIRALITY_MODEL_PATH
from src.feedback.dataset import TrainingData, _post_to_feed_item, _structured_features
from src.storage.json_store import JsonStore

# Below this many mature samples the model would overfit noise, so training is
# a deliberate no-op and the funnel keeps using its rule-based scoring only.
MIN_TRAINING_SAMPLES = 30

MODEL_VERSION = 1


def train_virality_model(
    data: TrainingData,
    logger: Logger,
    min_samples: int = MIN_TRAINING_SAMPLES,
) -> dict[str, Any] | None:
    """Fit a standardized ridge regressor on log1p(engagement).

    Stored as plain JSON (coefficients + scaler stats) so the model is small,
    diffable in git, and reproducible — no pickled binaries in the repo.
    """
    n = data.X.shape[0]
    if n < min_samples:
        logger.info(
            "Virality model not trained: %d/%d mature samples", n, min_samples
        )
        return None

    from sklearn.linear_model import Ridge

    mean = data.X.mean(axis=0)
    std = data.X.std(axis=0)
    std = np.where(std == 0, 1.0, std)
    X_scaled = (data.X - mean) / std

    model = Ridge(alpha=1.0)
    model.fit(X_scaled, data.y)

    payload = {
        "version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "n_samples": int(n),
        "feature_dim": int(data.feature_dim),
        "embed_model": DEFAULT_MODEL,
        "feat_mean": mean.astype(float).tolist(),
        "feat_std": std.astype(float).tolist(),
        "coef": model.coef_.astype(float).tolist(),
        "intercept": float(model.intercept_),
    }
    logger.info("Virality model trained on %d samples", n)
    return payload


def save_model(payload: dict[str, Any], path: Path = VIRALITY_MODEL_PATH) -> None:
    JsonStore.save(path, payload)


def load_model(path: Path = VIRALITY_MODEL_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = JsonStore.load(path, default=None)
    if not isinstance(payload, dict) or "coef" not in payload:
        return None
    return payload


class ViralityScorer:
    """Predicts a virality score for candidate posts from a trained JSON model.

    Returns a neutral 0.0 when no model is available, so callers can always add
    the score as a ranking signal without special-casing the cold-start period.
    """

    def __init__(self, logger: Logger | None = None, model_path: Path = VIRALITY_MODEL_PATH) -> None:
        self.logger = logger
        self._model = load_model(model_path)
        self._embed_service: EmbeddingService | None = None
        if self._model is not None:
            self._coef = np.asarray(self._model["coef"], dtype=np.float32)
            self._mean = np.asarray(self._model["feat_mean"], dtype=np.float32)
            self._std = np.asarray(self._model["feat_std"], dtype=np.float32)
            self._intercept = float(self._model["intercept"])

    @property
    def available(self) -> bool:
        return self._model is not None

    def _embed(self) -> EmbeddingService:
        if self._embed_service is None:
            self._embed_service = EmbeddingService(EMBEDDINGS_CACHE_PATH, logger=self.logger)
        return self._embed_service

    def score(self, post: dict[str, Any]) -> float:
        """Predicted engagement (back-transformed from log1p). 0.0 if no model."""
        if self._model is None:
            return 0.0
        item = _post_to_feed_item(post)
        embeddings = self._embed().embed_items([item])
        emb = embeddings.get(item.link)
        if emb is None:
            return 0.0
        structured = np.asarray(_structured_features(post), dtype=np.float32)
        features = np.concatenate([emb, structured])
        if features.shape[0] != self._coef.shape[0]:
            if self.logger:
                self.logger.warning(
                    "Virality model feature_dim mismatch (%d vs %d); skipping",
                    features.shape[0],
                    self._coef.shape[0],
                )
            return 0.0
        scaled = (features - self._mean) / self._std
        predicted_log = float(np.dot(scaled, self._coef) + self._intercept)
        return max(0.0, math.expm1(predicted_log))
