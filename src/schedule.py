"""Publish windows that survive GitHub's cron drift.

GitHub does not run ``schedule`` workflows on time. The publish workflow's
runs started 0.5h late in early August 2026 and 2.5-8h late from the last
week of August on (60 consecutive runs measured), which moved posts meant for
the 9:30 AM and 1:30 PM US Eastern engagement windows to 1 PM and 4 PM and
left the second slot with an empty queue. Instead of trusting a single cron
per window, ``publish-bluesky.yml`` now polls every 30 minutes and every run
asks this module whether it may post:

* ``now`` must fall inside one of the configured UTC windows
  (``config/schedule.json``), and
* the previous post on the same platform must be at least
  ``min_hours_between_posts`` old — the daily cap is enforced upstream at
  collection time, the spacing rule only keeps the two posts of a day apart.

Breaking items (see ``BOARDWIRE_BREAKING_*``) bypass the gate in
``_publish_approved``: a corroborated top story is worth more now than in a
window. Manual ``workflow_dispatch`` runs never enforce the gate either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dateutil import parser as date_parser

from src.config import SCHEDULE_CONFIG_PATH
from src.storage.json_store import JsonStore

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_MINUTES_PER_DAY = 24 * 60

DEFAULT_MIN_HOURS_BETWEEN_POSTS = 3.0


@dataclass(slots=True, frozen=True)
class PublishWindow:
    days: frozenset[int]          # 0 = Monday … 6 = Sunday, the day the window STARTS on
    start_minute: int             # minutes since midnight UTC, inclusive
    end_minute: int               # minutes since midnight UTC, exclusive; 1440 = end of day
    label: str = ""

    @property
    def wraps_midnight(self) -> bool:
        return self.end_minute <= self.start_minute

    def contains(self, now: datetime) -> bool:
        minute = now.hour * 60 + now.minute
        weekday = now.weekday()
        if not self.wraps_midnight:
            return weekday in self.days and self.start_minute <= minute < self.end_minute
        # e.g. 22:00 → 01:00: the late part belongs to the start day, the early
        # part to the following day.
        if weekday in self.days and minute >= self.start_minute:
            return True
        return (weekday - 1) % 7 in self.days and minute < self.end_minute

    def describe(self) -> str:
        days = ",".join(_DAY_NAMES[d] for d in sorted(self.days))
        return f"{self.label or 'window'} [{days} {_fmt(self.start_minute)}-{_fmt(self.end_minute)} UTC]"


@dataclass(slots=True)
class PublishSchedule:
    windows: list[PublishWindow] = field(default_factory=list)
    min_hours_between_posts: float = DEFAULT_MIN_HOURS_BETWEEN_POSTS

    def open_window(self, now: datetime) -> PublishWindow | None:
        now = _as_utc(now)
        for window in self.windows:
            if window.contains(now):
                return window
        return None

    def next_opening(self, now: datetime, horizon_days: int = 8) -> datetime | None:
        """Earliest window start strictly after ``now`` (None if no windows)."""
        now = _as_utc(now)
        best: datetime | None = None
        for offset in range(horizon_days + 1):
            day = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            for window in self.windows:
                if day.weekday() not in window.days:
                    continue
                start = day + timedelta(minutes=window.start_minute)
                if start <= now:
                    continue
                if best is None or start < best:
                    best = start
        return best


@dataclass(slots=True)
class GateDecision:
    open: bool
    reason: str
    window: PublishWindow | None = None
    hours_since_last_post: float | None = None


def _fmt(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_minute(raw: Any, *, end: bool) -> int:
    text = str(raw or "").strip()
    if end and text in {"24:00", "24"}:
        return _MINUTES_PER_DAY
    hours_text, _, minutes_text = text.partition(":")
    hours = int(hours_text)
    minutes = int(minutes_text or 0)
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise ValueError(f"invalid time {text!r}")
    return hours * 60 + minutes


def _parse_days(raw: Any) -> frozenset[int]:
    days: set[int] = set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, int) and 0 <= item <= 6:
            days.add(item)
            continue
        name = str(item).strip().lower()[:3]
        if name in _DAY_NAMES:
            days.add(_DAY_NAMES.index(name))
    return frozenset(days)


def parse_publish_schedule(raw: Any) -> PublishSchedule:
    if not isinstance(raw, dict):
        return PublishSchedule()
    try:
        spacing = float(raw.get("min_hours_between_posts", DEFAULT_MIN_HOURS_BETWEEN_POSTS))
    except (TypeError, ValueError):
        spacing = DEFAULT_MIN_HOURS_BETWEEN_POSTS
    windows: list[PublishWindow] = []
    for entry in raw.get("windows_utc", []) if isinstance(raw.get("windows_utc"), list) else []:
        if not isinstance(entry, dict):
            continue
        days = _parse_days(entry.get("days"))
        if not days:
            continue
        try:
            start = _parse_minute(entry.get("start"), end=False)
            end = _parse_minute(entry.get("end"), end=True)
        except (TypeError, ValueError):
            continue
        windows.append(PublishWindow(days=days, start_minute=start, end_minute=end, label=str(entry.get("label") or "")))
    return PublishSchedule(windows=windows, min_hours_between_posts=max(0.0, spacing))


def load_publish_schedule(path: Path | None = None) -> PublishSchedule:
    return parse_publish_schedule(JsonStore.load(path or SCHEDULE_CONFIG_PATH, default={}))


def hours_since_last_post(published: list[dict], now: datetime, platform: str | None = None) -> float | None:
    """Age of the newest published post (optionally only on ``platform``)."""
    now = _as_utc(now)
    latest: datetime | None = None
    for post in published:
        if not isinstance(post, dict):
            continue
        if platform and str(post.get("platform") or "") != platform:
            continue
        raw = post.get("published_at")
        if not raw:
            continue
        try:
            when = _as_utc(date_parser.parse(str(raw)))
        except (ValueError, OverflowError, TypeError):
            continue
        if latest is None or when > latest:
            latest = when
    if latest is None:
        return None
    return max(0.0, (now - latest).total_seconds() / 3600.0)


def evaluate_publish_gate(
    schedule: PublishSchedule,
    published: list[dict],
    now: datetime,
    platform: str | None = None,
) -> GateDecision:
    """May a routine (non-breaking) item publish right now?"""
    now = _as_utc(now)
    since = hours_since_last_post(published, now, platform=platform)
    if not schedule.windows:
        return GateDecision(open=True, reason="no publish windows configured", hours_since_last_post=since)
    window = schedule.open_window(now)
    if window is None:
        upcoming = schedule.next_opening(now)
        when = upcoming.strftime("%a %H:%M UTC") if upcoming else "never"
        return GateDecision(open=False, reason=f"outside every publish window (next opens {when})", hours_since_last_post=since)
    if since is not None and since < schedule.min_hours_between_posts:
        return GateDecision(
            open=False,
            reason=f"last post is {since:.1f}h old, minimum spacing is {schedule.min_hours_between_posts:.1f}h",
            window=window,
            hours_since_last_post=since,
        )
    return GateDecision(open=True, reason=f"inside {window.describe()}", window=window, hours_since_last_post=since)
