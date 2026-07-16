from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from urllib.parse import urlparse

from dateutil import parser as date_parser

from src.feedback.engagement_store import latest_snapshot, virality_label
from src.quality.gates import is_version_dominant_title
from src.storage.json_store import JsonStore

# Below this group size an average is more likely noise than signal, so the
# strategy sections print "insufficient data" instead.
_MIN_GROUP_N = 5

_WEEKDAY_ORDER = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Same release signals the model uses, so the hand report and the model read
# the data the same way.
_RELEASE_KEYWORDS = (
    "release",
    "released",
    "ships",
    "launch",
    "open-source",
    "open source",
    "weights",
    "api",
    "sdk",
)


@dataclass(slots=True)
class PostPerformance:
    id: str
    title: str
    source_link: str
    score: int
    peak_engagement: int
    likes: int
    reposts: int
    replies: int
    quotes: int
    age_hours: float | None
    post_excerpt: str
    has_release_kw: bool
    is_github: bool
    published_hour_utc: int | None = None
    published_weekday: str | None = None
    format_variant: str = "plain"
    hashtags_used: list[str] = field(default_factory=list)
    is_version_release: bool = False
    card_variant: str | None = None


@dataclass(slots=True)
class ReportSummary:
    total_posts: int
    measured: int
    top: PostPerformance | None = None
    median_peak: float = 0.0
    avg_peak: float = 0.0
    ranked: list[PostPerformance] = field(default_factory=list)


def _excerpt(text: str, limit: int = 140) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _is_github(link: str) -> bool:
    try:
        return "github.com" in urlparse(link or "").netloc.lower()
    except ValueError:
        return False


def _published_hour_weekday(post: dict) -> tuple[int | None, str | None]:
    """Read the explicit publish-time fields, falling back to published_at for
    posts recorded before the fields existed."""
    hour = post.get("published_hour_utc")
    weekday = post.get("published_weekday")
    if isinstance(hour, int) and isinstance(weekday, str) and weekday:
        return hour, weekday
    raw = post.get("published_at")
    if raw:
        try:
            dt = date_parser.parse(str(raw))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
            return dt.hour, dt.strftime("%A")
        except (ValueError, OverflowError):
            pass
    return None, None


def _build_performance(post: dict, record: dict) -> PostPerformance:
    snapshot = latest_snapshot(record) or {}
    text = post.get("post") or ""
    link = post.get("source_link") or ""
    try:
        score = int(post.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    hour, weekday = _published_hour_weekday(post)
    raw_tags = post.get("hashtags_used", [])
    hashtags = [str(t) for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
    return PostPerformance(
        id=str(post.get("id", "")),
        title=str(post.get("source_title") or _excerpt(text, 80) or "Untitled"),
        source_link=link,
        score=score,
        peak_engagement=virality_label(record),
        likes=int(snapshot.get("like_count", 0) or 0),
        reposts=int(snapshot.get("repost_count", 0) or 0),
        replies=int(snapshot.get("reply_count", 0) or 0),
        quotes=int(snapshot.get("quote_count", 0) or 0),
        age_hours=snapshot.get("age_hours"),
        post_excerpt=_excerpt(text),
        has_release_kw=any(k in text.lower() for k in _RELEASE_KEYWORDS),
        is_github=_is_github(link),
        published_hour_utc=hour,
        published_weekday=weekday,
        format_variant=str(post.get("format_variant") or "plain"),
        hashtags_used=hashtags,
        is_version_release=is_version_dominant_title(str(post.get("source_title") or "")),
        card_variant=(str(post.get("card_variant")) if post.get("card_variant") else None),
    )


def build_report_summary(published: list[dict], store: dict) -> ReportSummary:
    performances: list[PostPerformance] = []
    for post in published:
        post_id = post.get("id")
        record = store.get(post_id) if post_id else None
        if not record or not (record.get("snapshots")):
            continue
        performances.append(_build_performance(post, record))

    performances.sort(key=lambda p: p.peak_engagement, reverse=True)
    if not performances:
        return ReportSummary(total_posts=len(published), measured=0)

    peaks = [p.peak_engagement for p in performances]
    return ReportSummary(
        total_posts=len(published),
        measured=len(performances),
        top=performances[0],
        median_peak=float(median(peaks)),
        avg_peak=float(mean(peaks)),
        ranked=performances,
    )


def _group_avg(performances: list[PostPerformance], predicate) -> tuple[float, int]:
    group = [p.peak_engagement for p in performances if predicate(p)]
    if not group:
        return 0.0, 0
    return float(mean(group)), len(group)


def _grouped_lines(
    performances: list[PostPerformance],
    key_fn,
    label_fn=str,
    sort_key=None,
) -> list[str]:
    """Render one line per group, guarding small groups against misleading
    averages ("insufficient data (n<5)")."""
    groups: dict = defaultdict(list)
    for perf in performances:
        key = key_fn(perf)
        if key is None:
            continue
        groups[key].append(perf.peak_engagement)

    if not groups:
        return ["- insufficient data (n<5)"]

    lines: list[str] = []
    keys = sorted(groups.keys(), key=sort_key) if sort_key else sorted(groups.keys())
    for key in keys:
        peaks = groups[key]
        if len(peaks) < _MIN_GROUP_N:
            lines.append(f"- {label_fn(key)}: insufficient data (n<{_MIN_GROUP_N}, have {len(peaks)})")
        else:
            lines.append(f"- {label_fn(key)}: avg **{mean(peaks):.1f}** (n={len(peaks)})")
    return lines


def _weekday_sort_key(weekday: str) -> int:
    try:
        return _WEEKDAY_ORDER.index(weekday)
    except ValueError:
        return len(_WEEKDAY_ORDER)


def _strategy_sections(performances: list[PostPerformance]) -> list[str]:
    """Sections that answer the strategy questions: when to post, which format
    wins, which hashtag combos work, and whether releases stay dead weight."""
    lines: list[str] = []

    lines.append("## Engagement by published hour (UTC)")
    lines.append("")
    lines.extend(
        _grouped_lines(
            performances,
            key_fn=lambda p: p.published_hour_utc,
            label_fn=lambda h: f"{h:02d}:00 UTC",
        )
    )
    lines.append("")

    lines.append("## Engagement by weekday")
    lines.append("")
    lines.extend(
        _grouped_lines(
            performances,
            key_fn=lambda p: p.published_weekday,
            sort_key=_weekday_sort_key,
        )
    )
    lines.append("")

    lines.append("## Engagement by format variant")
    lines.append("")
    lines.extend(_grouped_lines(performances, key_fn=lambda p: p.format_variant or "plain"))
    lines.append("")

    lines.append("## Engagement by card variant")
    lines.append("")
    lines.extend(_grouped_lines(performances, key_fn=lambda p: p.card_variant))
    lines.append("")

    lines.append("## Engagement by hashtag combination")
    lines.append("")
    lines.extend(
        _grouped_lines(
            performances,
            key_fn=lambda p: " ".join(sorted(p.hashtags_used)) if p.hashtags_used else None,
        )
    )
    lines.append("")

    lines.append("## Version-release posts vs others")
    lines.append("")
    version_posts = [p for p in performances if p.is_version_release]
    other_posts = [p for p in performances if not p.is_version_release]
    for label, group in (("Version releases", version_posts), ("Others", other_posts)):
        if len(group) == 0:
            lines.append(f"- {label}: n=0")
        elif len(group) < _MIN_GROUP_N:
            lines.append(f"- {label}: insufficient data (n<{_MIN_GROUP_N}, have {len(group)})")
        else:
            peaks = [p.peak_engagement for p in group]
            lines.append(f"- {label}: avg **{mean(peaks):.1f}** (n={len(peaks)})")
    lines.append(
        "  (Version-only releases are now blocked by the quality gate; this group should trend to n=0.)"
    )
    lines.append("")
    return lines


def _render_markdown(summary: ReportSummary) -> str:
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lines: list[str] = []
    lines.append("# Boardwire Engagement Report")
    lines.append("")
    lines.append(f"Generated: `{generated}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Measured posts: **{summary.measured}** of {summary.total_posts} published")

    if summary.measured == 0:
        lines.append("")
        lines.append(
            "No engagement data yet. Run `--collect-engagement` (the daily "
            "workflow does this automatically) once posts have been live for a while."
        )
        lines.append("")
        return "\n".join(lines)

    assert summary.top is not None
    lines.append(f"- Median peak engagement: **{summary.median_peak:.1f}**")
    lines.append(f"- Average peak engagement: **{summary.avg_peak:.1f}**")
    lines.append(f"- Top: **{summary.top.peak_engagement}** — {summary.top.title}")
    lines.append("")

    # Patterns that build intuition before the model has enough data to learn.
    rel_avg, rel_n = _group_avg(summary.ranked, lambda p: p.has_release_kw)
    non_avg, non_n = _group_avg(summary.ranked, lambda p: not p.has_release_kw)
    gh_avg, gh_n = _group_avg(summary.ranked, lambda p: p.is_github)
    other_avg, other_n = _group_avg(summary.ranked, lambda p: not p.is_github)
    lines.append("## Patterns")
    lines.append("")
    lines.append(
        f"- Release-keyword posts: avg **{rel_avg:.1f}** (n={rel_n}) "
        f"vs others avg **{non_avg:.1f}** (n={non_n})"
    )
    lines.append(
        f"- GitHub sources: avg **{gh_avg:.1f}** (n={gh_n}) "
        f"vs other sources avg **{other_avg:.1f}** (n={other_n})"
    )
    lines.append("")
    lines.extend(_strategy_sections(summary.ranked))
    lines.append("## Ranked posts")
    lines.append("")
    for idx, perf in enumerate(summary.ranked, start=1):
        age = f"{perf.age_hours:.0f}h" if perf.age_hours is not None else "n/a"
        lines.append(f"{idx}. **{perf.peak_engagement} pts** — {perf.title}")
        lines.append(
            f"   likes {perf.likes} · reposts {perf.reposts} · replies {perf.replies} "
            f"· quotes {perf.quotes} · age {age} · score {perf.score}"
        )
        if perf.source_link:
            lines.append(f"   {perf.source_link}")
        if perf.post_excerpt:
            lines.append(f"   > {perf.post_excerpt}")
        lines.append("")
    return "\n".join(lines)


def generate_engagement_report(
    published_posts_path: Path,
    engagement_path: Path,
    report_path: Path,
) -> ReportSummary:
    published = JsonStore.load(published_posts_path, default=[])
    store = JsonStore.load(engagement_path, default={})
    if not isinstance(store, dict):
        store = {}
    summary = build_report_summary(published, store)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_markdown(summary) + "\n", encoding="utf-8")
    return summary
