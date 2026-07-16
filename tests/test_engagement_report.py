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


def _post_with_meta(
    post_id: str,
    hour: int,
    weekday: str,
    variant: str,
    tags: list[str],
    title: str = "",
    card_variant: str = "",
) -> dict:
    post = _post(post_id, f"text for {post_id} about a model release", "https://example.com/" + post_id)
    post["source_title"] = title or f"title-{post_id}"
    post["published_hour_utc"] = hour
    post["published_weekday"] = weekday
    post["format_variant"] = variant
    post["hashtags_used"] = tags
    if card_variant:
        post["card_variant"] = card_variant
    return post


def test_card_variant_section_present(tmp_path) -> None:
    import json

    published = [
        _post_with_meta(f"e{i}", hour=13, weekday="Tuesday", variant="plain", tags=["#AI"], card_variant="editorial_stat")
        for i in range(5)
    ]
    published.append(
        _post_with_meta("og1", hour=13, weekday="Tuesday", variant="plain", tags=["#AI"], card_variant="github_og")
    )
    store = {p["id"]: _record(p["id"], 12) for p in published}

    published_path = tmp_path / "published.json"
    engagement_path = tmp_path / "engagement.json"
    report_path = tmp_path / "report.md"
    published_path.write_text(json.dumps(published))
    engagement_path.write_text(json.dumps(store))

    generate_engagement_report(published_path, engagement_path, report_path)
    text = report_path.read_text()
    assert "## Engagement by card variant" in text
    assert "editorial_stat: avg **12.0** (n=5)" in text
    assert "github_og: insufficient data (n<5" in text


def test_strategy_sections_present_with_small_n_guard(tmp_path) -> None:
    import json

    published = [
        _post_with_meta(f"p{i}", hour=13, weekday="Tuesday", variant="question", tags=["#AI", "#MCP"])
        for i in range(5)
    ]
    published.append(_post_with_meta("solo", hour=22, weekday="Sunday", variant="thread", tags=["#AI"]))
    store = {p["id"]: _record(p["id"], 10) for p in published}

    published_path = tmp_path / "published.json"
    engagement_path = tmp_path / "engagement.json"
    report_path = tmp_path / "report.md"
    published_path.write_text(json.dumps(published))
    engagement_path.write_text(json.dumps(store))

    generate_engagement_report(published_path, engagement_path, report_path)
    text = report_path.read_text()

    assert "## Engagement by published hour (UTC)" in text
    assert "## Engagement by weekday" in text
    assert "## Engagement by format variant" in text
    assert "## Engagement by hashtag combination" in text
    assert "## Version-release posts vs others" in text
    # n=5 group gets a real average; n=1 groups print the guard.
    assert "13:00 UTC: avg **10.0** (n=5)" in text
    assert "22:00 UTC: insufficient data (n<5" in text
    assert "thread: insufficient data (n<5" in text
    assert "question: avg **10.0** (n=5)" in text


def test_version_release_group_detected(tmp_path) -> None:
    import json

    published = [
        _post_with_meta("v1", hour=9, weekday="Monday", variant="plain", tags=["#AI"], title="ollama v0.30.11"),
        _post_with_meta("n1", hour=9, weekday="Monday", variant="plain", tags=["#AI"], title="Real headline about agents"),
    ]
    store = {p["id"]: _record(p["id"], 3) for p in published}
    published_path = tmp_path / "published.json"
    engagement_path = tmp_path / "engagement.json"
    report_path = tmp_path / "report.md"
    published_path.write_text(json.dumps(published))
    engagement_path.write_text(json.dumps(store))

    generate_engagement_report(published_path, engagement_path, report_path)
    text = report_path.read_text()
    assert "Version releases: insufficient data" in text
    assert "Others: insufficient data" in text


def test_hour_weekday_fallback_from_published_at(tmp_path) -> None:
    # Old posts without the explicit fields fall back to published_at.
    from src.reports.engagement_report import build_report_summary

    post = _post("old", "legacy post", "https://example.com/old")
    post["published_at"] = "2026-05-03T22:15:00Z"  # a Sunday
    summary = build_report_summary([post], {"old": _record("old", 7)})
    perf = summary.ranked[0]
    assert perf.published_hour_utc == 22
    assert perf.published_weekday == "Sunday"
    assert perf.format_variant == "plain"


def test_generate_handles_missing_files(tmp_path) -> None:
    report_path = tmp_path / "report.md"
    summary = generate_engagement_report(
        tmp_path / "nope.json", tmp_path / "nope2.json", report_path
    )
    assert summary.measured == 0
    assert "No engagement data yet" in report_path.read_text()
