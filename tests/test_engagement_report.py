from src.reports.engagement_report import (
    build_report_summary,
    generate_engagement_report,
)


def _post(post_id: str, text: str, link: str, score: int = 80) -> dict:
    return {
        "id": post_id,
        "platform": "bluesky",
        "post": text,
        "source_link": link,
        "source_title": f"title-{post_id}",
        "score": score,
        "published_at": "2026-05-01T00:00:00Z",
    }


def _record(post_id: str, peak_total: int) -> dict:
    return {
        "id": post_id,
        "snapshots": [
            {
                "observed_at": "2026-05-02T00:00:00Z",
                "age_hours": 24.0,
                "like_count": peak_total,
                "repost_count": 0,
                "reply_count": 0,
                "quote_count": 0,
                "total_engagement": peak_total,
            }
        ],
    }


def test_summary_empty_when_no_snapshots() -> None:
    published = [_post("a", "x", "https://example.com")]
    summary = build_report_summary(published, {})
    assert summary.measured == 0
    assert summary.total_posts == 1
    assert summary.top is None


def test_summary_ranks_by_peak_engagement() -> None:
    published = [
        _post("low", "a release ships", "https://github.com/x/y"),
        _post("high", "general thoughts", "https://blog.example.com"),
    ]
    store = {"low": _record("low", 5), "high": _record("high", 50)}
    summary = build_report_summary(published, store)

    assert summary.measured == 2
    assert summary.top.id == "high"
    assert [p.id for p in summary.ranked] == ["high", "low"]
    assert summary.median_peak == 27.5
    # release-keyword / github flags are derived correctly
    low = next(p for p in summary.ranked if p.id == "low")
    assert low.has_release_kw is True
    assert low.is_github is True


def test_generate_writes_markdown(tmp_path) -> None:
    published_path = tmp_path / "published.json"
    engagement_path = tmp_path / "engagement.json"
    report_path = tmp_path / "report.md"

    import json

    published = [_post("p1", "new model release", "https://github.com/a/b")]
    published_path.write_text(json.dumps(published))
    engagement_path.write_text(json.dumps({"p1": _record("p1", 42)}))

    summary = generate_engagement_report(published_path, engagement_path, report_path)
    assert summary.measured == 1
    text = report_path.read_text()
    assert "# Boardwire Engagement Report" in text
    assert "42 pts" in text
    assert "## Patterns" in text


def test_generate_handles_missing_files(tmp_path) -> None:
    report_path = tmp_path / "report.md"
    summary = generate_engagement_report(
        tmp_path / "nope.json", tmp_path / "nope2.json", report_path
    )
    assert summary.measured == 0
    assert "No engagement data yet" in report_path.read_text()
