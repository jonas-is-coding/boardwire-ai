from datetime import datetime, timezone

import pytest

from src.main import _breaking_config, _count_today_by_kind, _is_breaking_item
from src.quality.gates import QualityConfig, check_quality


def _review_item(score, *, source_count=1, cluster_engagement=0, engagement=0, breaking=None, status="approved", created_at=None):
    item = {
        "status": status,
        "score": score,
        "created_at": created_at,
        "source_item": {
            "engagement_score": engagement,
            "cluster_context": {
                "source_count": source_count,
                "total_engagement_score": cluster_engagement,
            },
        },
    }
    if breaking is not None:
        item["breaking"] = breaking
    return item


def _cfg(**overrides):
    cfg = {
        "enabled": True,
        "threshold": 92,
        "max_extra_per_day": 3,
        "max_extra_per_run": 2,
        "require_corroboration": True,
        "min_engagement": 100.0,
    }
    cfg.update(overrides)
    return cfg


def test_breaking_requires_score_above_threshold():
    cfg = _cfg()
    assert not _is_breaking_item(_review_item(90, source_count=3), 90, cfg)
    assert _is_breaking_item(_review_item(95, source_count=3), 95, cfg)


def test_breaking_requires_corroboration_when_enabled():
    cfg = _cfg()
    # High score but single source and no engagement -> not breaking.
    assert not _is_breaking_item(_review_item(99, source_count=1, engagement=0), 99, cfg)
    # Corroboration via multiple sources.
    assert _is_breaking_item(_review_item(99, source_count=2), 99, cfg)
    # Corroboration via high engagement.
    assert _is_breaking_item(_review_item(99, source_count=1, engagement=150), 99, cfg)
    # Corroboration via cluster engagement.
    assert _is_breaking_item(_review_item(99, source_count=1, cluster_engagement=150), 99, cfg)


def test_breaking_without_corroboration_requirement():
    cfg = _cfg(require_corroboration=False)
    assert _is_breaking_item(_review_item(95, source_count=1, engagement=0), 95, cfg)


def test_breaking_disabled():
    cfg = _cfg(enabled=False)
    assert not _is_breaking_item(_review_item(99, source_count=5), 99, cfg)


def test_count_today_by_kind_splits_normal_and_breaking():
    today = datetime(2026, 6, 14, tzinfo=timezone.utc).date()
    today_iso = "2026-06-14T09:00:00Z"
    yesterday_iso = "2026-06-13T09:00:00Z"
    queue = [
        _review_item(80, created_at=today_iso),
        _review_item(80, created_at=today_iso),
        _review_item(95, created_at=today_iso, breaking=True),
        _review_item(95, created_at=yesterday_iso, breaking=True),  # not today
        _review_item(80, created_at=today_iso, status="rejected"),  # not live
    ]
    normal, breaking = _count_today_by_kind(queue, today)
    assert normal == 2
    assert breaking == 1


def test_breaking_config_reads_env(monkeypatch):
    monkeypatch.setenv("BOARDWIRE_BREAKING_SCORE_THRESHOLD", "88")
    monkeypatch.setenv("BOARDWIRE_BREAKING_MAX_EXTRA_PER_DAY", "5")
    monkeypatch.setenv("BOARDWIRE_BREAKING_REQUIRE_CORROBORATION", "false")
    cfg = _breaking_config()
    assert cfg["threshold"] == 88
    assert cfg["max_extra_per_day"] == 5
    assert cfg["require_corroboration"] is False


def test_breaking_config_defaults_on_bad_values(monkeypatch):
    monkeypatch.setenv("BOARDWIRE_BREAKING_SCORE_THRESHOLD", "not-an-int")
    cfg = _breaking_config()
    assert cfg["threshold"] == 92


def _quality_config():
    return QualityConfig(
        max_post_length=280,
        min_llm_score=62,
        min_rule_score=4,
        max_defer_count=3,
        duplicate_lookback_hours=168,
        fixture_duplicate_lookback_hours=1,
        banned_phrases=[],
        generic_phrases=[],
    )


def test_allow_duplicate_bypasses_near_duplicate_gate():
    config = _quality_config()
    post = "Anthropic suspends Claude Fable 5 API access after safety review enables new limits."
    history = [post]  # identical earlier post

    rejected = check_quality(
        post=post,
        source_link="https://example.com/a",
        score=95,
        is_llm_mode=True,
        config=config,
        history_posts=history,
        context="review",
        allow_duplicate=False,
    )
    assert not rejected.passed
    assert any("uplicate" in r for r in rejected.reasons)

    allowed = check_quality(
        post=post,
        source_link="https://example.com/a",
        score=95,
        is_llm_mode=True,
        config=config,
        history_posts=history,
        context="review",
        allow_duplicate=True,
    )
    assert allowed.passed, allowed.reasons


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
