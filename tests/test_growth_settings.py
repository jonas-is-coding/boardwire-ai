from __future__ import annotations

from src.growth.settings import CandidateFilters, DiscoveryWeights, GrowthConfig, load_growth_config


def test_reciprocity_defaults() -> None:
    config = GrowthConfig()
    assert config.weights.reciprocity == 0.5
    assert config.reciprocity_min_follow_ratio == 0.8


def test_load_growth_config_parses_reciprocity_fields(tmp_path) -> None:
    path = tmp_path / "growth.json"
    path.write_text(
        '{"weights": {"reciprocity": 0.7}, "reciprocity_min_follow_ratio": 0.65, '
        '"filters": {"max_followers": 2000}}'
    )
    config = load_growth_config(path)
    assert config.weights.reciprocity == 0.7
    assert config.reciprocity_min_follow_ratio == 0.65
    assert config.filters.max_followers == 2000


def test_load_growth_config_defaults_reciprocity_fields_when_absent(tmp_path) -> None:
    path = tmp_path / "growth.json"
    path.write_text("{}")
    config = load_growth_config(path)
    assert config.weights.reciprocity == 0.5
    assert config.reciprocity_min_follow_ratio == 0.8


def test_repo_growth_config_targets_follow_back_sized_accounts() -> None:
    """The repo's live config, not just the dataclass defaults: max_followers
    must stay well under typical seed-account follower counts (thousands to
    tens of thousands) so discovery targets accounts that can plausibly
    follow us back, and the reciprocity signal must be enabled."""
    config = load_growth_config()
    assert 0 < config.filters.max_followers <= 5000
    assert config.weights.reciprocity > 0
    assert 0 < config.reciprocity_min_follow_ratio <= config.filters.max_follow_ratio
