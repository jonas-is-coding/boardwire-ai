import logging

import numpy as np

from src.feedback.dataset import TrainingData
from src.feedback.model import (
    MIN_TRAINING_SAMPLES,
    load_model,
    save_model,
    train_virality_model,
)

_LOGGER = logging.getLogger("test")


def _synthetic_data(n: int, dim: int = 8) -> TrainingData:
    rng = np.random.default_rng(0)
    X = rng.normal(size=(n, dim)).astype(np.float32)
    # Label correlates with the first feature so the regressor has signal to fit.
    y = (2.0 * X[:, 0] + 0.5).astype(np.float32)
    return TrainingData(X=X, y=y, ids=[f"p{i}" for i in range(n)], feature_dim=dim)


def test_train_is_noop_below_min_samples() -> None:
    data = _synthetic_data(MIN_TRAINING_SAMPLES - 1)
    assert train_virality_model(data, _LOGGER) is None


def test_train_save_load_roundtrip(tmp_path) -> None:
    data = _synthetic_data(MIN_TRAINING_SAMPLES + 20)
    payload = train_virality_model(data, _LOGGER)
    assert payload is not None
    assert payload["n_samples"] == MIN_TRAINING_SAMPLES + 20
    assert payload["feature_dim"] == 8
    assert len(payload["coef"]) == 8

    path = tmp_path / "virality_model.json"
    save_model(payload, path)
    loaded = load_model(path)
    assert loaded is not None
    assert loaded["coef"] == payload["coef"]

    # First feature drives the label, so its standardized coefficient should
    # dominate — confirms the model learned the intended signal.
    coef = np.asarray(loaded["coef"])
    assert np.argmax(np.abs(coef)) == 0


def test_load_model_missing_returns_none(tmp_path) -> None:
    assert load_model(tmp_path / "nope.json") is None
