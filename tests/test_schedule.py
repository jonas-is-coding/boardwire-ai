from __future__ import annotations

from datetime import datetime, timezone

from src.schedule import (
    GateDecision,
    PublishSchedule,
    PublishWindow,
    evaluate_publish_gate,
    hours_since_last_post,
    load_publish_schedule,
    parse_publish_schedule,
)


def _utc(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


_WEEKDAYS = frozenset({0, 1, 2, 3, 4})
_MORNING = PublishWindow(days=_WEEKDAYS, start_minute=13 * 60, end_minute=16 * 60, label="morning")
_MIDDAY = PublishWindow(days=_WEEKDAYS, start_minute=17 * 60, end_minute=20 * 60 + 30, label="midday")
_SUNDAY = PublishWindow(days=frozenset({6}), start_minute=21 * 60 + 30, end_minute=24 * 60, label="sunday")
_SCHEDULE = PublishSchedule(windows=[_MORNING, _MIDDAY, _SUNDAY], min_hours_between_posts=3)


def test_repo_schedule_config_parses_to_three_windows() -> None:
    schedule = load_publish_schedule()
    assert len(schedule.windows) == 3
    assert schedule.min_hours_between_posts == 3
    assert schedule.windows[2].days == frozenset({6})
    assert schedule.windows[2].end_minute == 24 * 60


def test_window_membership_by_weekday_and_minute() -> None:
    thursday = _utc(2026, 9, 3, 13, 0)  # 2026-09-03 is a Thursday
    assert _MORNING.contains(thursday)
    assert not _MORNING.contains(_utc(2026, 9, 3, 12, 59))
    assert not _MORNING.contains(_utc(2026, 9, 3, 16, 0))  # end is exclusive
    assert not _MORNING.contains(_utc(2026, 9, 5, 14, 0))  # Saturday
    assert _SUNDAY.contains(_utc(2026, 9, 6, 23, 59))
    assert not _SUNDAY.contains(_utc(2026, 9, 7, 0, 0))


def test_window_wrapping_past_midnight_belongs_to_its_start_day() -> None:
    window = PublishWindow(days=frozenset({6}), start_minute=22 * 60, end_minute=60)
    assert window.contains(_utc(2026, 9, 6, 22, 30))  # Sunday night
    assert window.contains(_utc(2026, 9, 7, 0, 30))   # early Monday, still the Sunday window
    assert not window.contains(_utc(2026, 9, 7, 1, 0))
    assert not window.contains(_utc(2026, 9, 6, 0, 30))  # early Sunday is Saturday's tail, not configured


def test_next_opening_skips_to_the_following_window() -> None:
    assert _SCHEDULE.next_opening(_utc(2026, 9, 3, 16, 30)) == _utc(2026, 9, 3, 17, 0)
    assert _SCHEDULE.next_opening(_utc(2026, 9, 4, 21, 0)) == _utc(2026, 9, 6, 21, 30)  # Fri night → Sunday
    assert _SCHEDULE.next_opening(_utc(2026, 9, 6, 23, 0)) == _utc(2026, 9, 7, 13, 0)  # Sun night → Monday
    assert PublishSchedule().next_opening(_utc(2026, 9, 3, 12, 0)) is None


def test_parse_accepts_names_ints_and_24_00_and_drops_garbage() -> None:
    schedule = parse_publish_schedule(
        {
            "min_hours_between_posts": "2.5",
            "windows_utc": [
                {"days": ["Monday", 6], "start": "9:05", "end": "24:00", "label": "x"},
                {"days": [], "start": "09:00", "end": "10:00"},
                {"days": ["tue"], "start": "25:00", "end": "10:00"},
                "not a window",
            ],
        }
    )
    assert schedule.min_hours_between_posts == 2.5
    assert len(schedule.windows) == 1
    assert schedule.windows[0].days == frozenset({0, 6})
    assert (schedule.windows[0].start_minute, schedule.windows[0].end_minute) == (9 * 60 + 5, 24 * 60)
    assert parse_publish_schedule(None).windows == []


def test_hours_since_last_post_filters_by_platform_and_ignores_bad_dates() -> None:
    now = _utc(2026, 9, 3, 15, 0)
    published = [
        {"platform": "bluesky", "published_at": "2026-09-03T13:00:00Z"},
        {"platform": "bluesky", "published_at": "2026-09-03T09:00:00Z"},
        {"platform": "dry_run", "published_at": "2026-09-03T14:50:00Z"},
        {"platform": "bluesky", "published_at": "garbage"},
        "not a post",
    ]
    assert hours_since_last_post(published, now, platform="bluesky") == 2.0
    assert hours_since_last_post(published, now) == 1.0 / 6 * 1  # dry_run 10 min ago counts without a filter
    assert hours_since_last_post([], now) is None


def test_gate_closed_outside_windows_open_inside_and_spaced() -> None:
    thursday_noon = _utc(2026, 9, 3, 12, 30)
    closed = evaluate_publish_gate(_SCHEDULE, [], thursday_noon, platform="bluesky")
    assert isinstance(closed, GateDecision) and not closed.open
    assert "next opens Thu 13:00 UTC" in closed.reason

    inside = _utc(2026, 9, 3, 13, 40)
    assert evaluate_publish_gate(_SCHEDULE, [], inside, platform="bluesky").open

    recent = [{"platform": "bluesky", "published_at": "2026-09-03T12:00:00Z"}]
    spaced_out = evaluate_publish_gate(_SCHEDULE, recent, inside, platform="bluesky")
    assert not spaced_out.open and "minimum spacing" in spaced_out.reason
    assert spaced_out.window is _MORNING

    old_enough = [{"platform": "bluesky", "published_at": "2026-09-03T10:30:00Z"}]
    assert evaluate_publish_gate(_SCHEDULE, old_enough, inside, platform="bluesky").open


def test_gate_is_open_without_configured_windows() -> None:
    decision = evaluate_publish_gate(PublishSchedule(), [], _utc(2026, 9, 5, 3, 0))
    assert decision.open and "no publish windows" in decision.reason
