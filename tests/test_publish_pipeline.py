from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import src.main as main
from src.composer import select_format_variant
from src.storage.json_store import JsonStore


def _queue_item(link: str, score: int = 70, title: str = "Agent memory becomes infrastructure") -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": f"rid-{abs(hash(link)) % 10**8}",
        "status": "approved",
        "created_at": now,
        "score": score,
        "reason": "clear builder utility",
        "proposed_post": "Agent memory becomes infrastructure because it enables persistent agents.",
        "source_angle": "test",
        "is_llm_mode": True,
        "source_item": {
            "title": title,
            "source": "HackerNews",
            "link": link,
            "summary": "Adds MCP support, a local CLI and open weights for agents.",
            "source_tier": 1,
            "engagement_score": 500.0,
        },
        "card_path": None,
    }


def _package(question: str = "Anyone running this in prod?") -> dict:
    return {
        "title": "Agent memory becomes infrastructure.",
        "subtitle": "Agentmemory ships a 4-tier local pipeline with MCP support and zero cloud calls.",
        "description": "Card-only detail line.",
        "hashtags": ["#SomethingInvented", "#MCP"],
        "question": question,
    }


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    """Route all state files into tmp and silence network/LLM side effects."""
    review_path = tmp_path / "review_queue.json"
    published_path = tmp_path / "published_posts.json"
    releases_path = tmp_path / "published_releases.json"
    rejections_path = tmp_path / "gate_rejections.json"
    articles_dir = tmp_path / "articles"

    monkeypatch.setattr(main, "REVIEW_QUEUE_PATH", review_path)
    monkeypatch.setattr(main, "PUBLISHED_POSTS_PATH", published_path)
    monkeypatch.setattr(main, "PUBLISHED_RELEASES_PATH", releases_path)
    monkeypatch.setattr(main, "GATE_REJECTIONS_PATH", rejections_path)
    monkeypatch.setattr(main, "REVIEW_REPORT_PATH", tmp_path / "review_queue.md")
    monkeypatch.setattr(main, "ARTICLES_DIR", articles_dir)
    monkeypatch.setattr(main, "_generate_card_for_item", lambda item, logger: None)

    import src.reports.review_report as review_report

    monkeypatch.setattr(review_report, "GATE_REJECTIONS_PATH", rejections_path)

    for fn in ("sarah_packaged", "jim_published", "jim_failed", "sarah_failed_batch"):
        monkeypatch.setattr(main.notify, fn, lambda *a, **k: None)

    from src.notifications import persona_voice as voice

    monkeypatch.setattr(voice, "sarah_build_publish_package", lambda *a, **k: _package())
    monkeypatch.delenv("BOARDWIRE_PUBLISHER", raising=False)

    def run_publish() -> int:
        args = main._build_parser().parse_args(["--publish-approved"])
        return main._publish_approved(args, main.get_logger())

    return {
        "review_path": review_path,
        "published_path": published_path,
        "releases_path": releases_path,
        "rejections_path": rejections_path,
        "run": run_publish,
    }


def _find_variant_link(target: str) -> str:
    for i in range(500):
        link = f"https://example.com/story-{i}"
        if select_format_variant(link) == target:
            return link
    raise AssertionError(f"no link found for variant {target}")


def test_plain_publish_persists_ab_fields(pipeline) -> None:
    link = _find_variant_link("plain")
    JsonStore.save(pipeline["review_path"], [_queue_item(link, score=70)])

    assert pipeline["run"]() == 0

    published = json.loads(pipeline["published_path"].read_text())
    assert len(published) == 1
    post = published[0]
    assert post["format_variant"] == "plain"
    assert "Anyone running this in prod?" not in post["post"]
    assert post["hashtags_used"][0].startswith("#")
    # LLM tag not in config was dropped; validated #MCP survived.
    assert "#SomethingInvented" not in post["hashtags_used"]
    assert "#MCP" in post["hashtags_used"]
    assert 0 <= post["published_hour_utc"] <= 23
    assert post["published_weekday"] in {
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    }


def test_question_variant_included_in_post(pipeline) -> None:
    link = _find_variant_link("question")
    JsonStore.save(pipeline["review_path"], [_queue_item(link, score=70)])

    assert pipeline["run"]() == 0

    published = json.loads(pipeline["published_path"].read_text())
    post = published[0]
    assert post["format_variant"] == "question"
    assert "Anyone running this in prod?" in post["post"]


def test_high_score_item_published_as_thread(pipeline) -> None:
    link = _find_variant_link("plain")
    JsonStore.save(pipeline["review_path"], [_queue_item(link, score=95)])

    assert pipeline["run"]() == 0

    published = json.loads(pipeline["published_path"].read_text())
    post = published[0]
    assert post["format_variant"] == "thread"
    assert len(post["thread_uris"]) == 3
    assert post["thread_partial"] is False


def test_publish_persists_composer_version_and_card_variant(pipeline) -> None:
    from src.composer import COMPOSER_VERSION

    link = _find_variant_link("plain")
    JsonStore.save(pipeline["review_path"], [_queue_item(link, score=70)])
    assert pipeline["run"]() == 0

    published = json.loads(pipeline["published_path"].read_text())
    post = published[0]
    assert post["composer_version"] == COMPOSER_VERSION
    # Non-GitHub source → editorial card variant.
    assert post["card_variant"].startswith("editorial")


def test_validation_failure_regenerates_then_publishes(pipeline, monkeypatch) -> None:
    from src.notifications import persona_voice as voice

    link = _find_variant_link("plain")
    JsonStore.save(pipeline["review_path"], [_queue_item(link, score=70)])

    calls = {"n": 0}

    def flaky_package(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            # First attempt leaks HN engagement metadata → rejected.
            bad = _package()
            bad["subtitle"] = "Recall stores data with 58 comments and 77 points on HN."
            return bad
        return _package()  # regenerated: clean

    monkeypatch.setattr(voice, "sarah_build_publish_package", flaky_package)

    assert pipeline["run"]() == 0
    published = json.loads(pipeline["published_path"].read_text())
    assert len(published) == 1
    assert calls["n"] == 2  # regenerated exactly once
    assert "58 comments and 77 points" not in published[0]["post"]


def test_validation_failure_twice_skips(pipeline, monkeypatch) -> None:
    from src.notifications import persona_voice as voice

    link = _find_variant_link("plain")
    JsonStore.save(pipeline["review_path"], [_queue_item(link, score=70)])

    calls = {"n": 0}

    def always_bad(*a, **k):
        calls["n"] += 1
        bad = _package()
        bad["subtitle"] = "Recall stores data with 58 comments and 77 points on HN."
        return bad

    monkeypatch.setattr(voice, "sarah_build_publish_package", always_bad)

    assert pipeline["run"]() == 0
    published = json.loads(pipeline["published_path"].read_text())
    assert published == []  # never published
    assert calls["n"] == 2  # tried, regenerated once, then gave up
    rejections = json.loads(pipeline["rejections_path"].read_text())
    assert any("engagement metadata" in "; ".join(r.get("reasons", [])).lower() for r in rejections)


def test_null_summary_does_not_leak_literal_none(pipeline) -> None:
    # A GitHub Trending item with no summary stores explicit JSON null, not a
    # missing key. dict.get(key, default) only applies the default when the
    # key is ABSENT, so `.get("summary", "")` returns None here, and str(None)
    # == "None" would leak the literal word into the prompt/card.
    link = _find_variant_link("plain")
    item = _queue_item(link, score=70)
    item["source_item"]["summary"] = None
    JsonStore.save(pipeline["review_path"], [item])

    assert pipeline["run"]() == 0

    published = json.loads(pipeline["published_path"].read_text())
    assert len(published) == 1
    assert "None" not in published[0]["post"]


def test_publish_resets_sarah_provider_state_per_attempt(tmp_path, monkeypatch) -> None:
    """A provider marked 'used'/'exhausted' before this item's packaging must
    not block it: _package_once resets sarah_generation state on every
    attempt, so pre-existing state (e.g. from a previous item in the same
    run) can't poison this one. Without the reset in main.py, this item would
    fail every attempt as soon as any provider had been touched once."""
    from src.llm import sarah_generation

    review_path = tmp_path / "review_queue.json"
    published_path = tmp_path / "published_posts.json"
    articles_dir = tmp_path / "articles"

    monkeypatch.setattr(main, "REVIEW_QUEUE_PATH", review_path)
    monkeypatch.setattr(main, "PUBLISHED_POSTS_PATH", published_path)
    monkeypatch.setattr(main, "PUBLISHED_RELEASES_PATH", tmp_path / "published_releases.json")
    monkeypatch.setattr(main, "GATE_REJECTIONS_PATH", tmp_path / "gate_rejections.json")
    monkeypatch.setattr(main, "REVIEW_REPORT_PATH", tmp_path / "review_queue.md")
    monkeypatch.setattr(main, "ARTICLES_DIR", articles_dir)
    monkeypatch.setattr(main, "_generate_card_for_item", lambda item, logger: None)
    for fn in ("sarah_packaged", "jim_published", "jim_failed", "sarah_failed_batch"):
        monkeypatch.setattr(main.notify, fn, lambda *a, **k: None)
    monkeypatch.delenv("BOARDWIRE_PUBLISHER", raising=False)
    monkeypatch.delenv("BOARDWIRE_SARAH_PROVIDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")

    # Simulate state left over from an earlier item/attempt in this same
    # process: groq already "used" once and cerebras/mistral exhausted.
    sarah_generation._STATE["used"]["groq"] = 1
    sarah_generation._STATE["exhausted"]["cerebras"] = True
    sarah_generation._STATE["exhausted"]["mistral"] = True

    valid_json = (
        '{"title": "Agent memory becomes infrastructure.", '
        '"subtitle": "Agentmemory ships a 4-tier pipeline with MCP support.", '
        '"description": "Runs fully local.", "hashtags": ["#AI", "#MCP"], '
        '"question": ""}'
    )

    def fake_post(url, **kwargs):
        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": valid_json}}]}

        return _Resp()

    monkeypatch.setattr(sarah_generation.requests, "post", fake_post)

    link = _find_variant_link("plain")
    JsonStore.save(review_path, [_queue_item(link, score=70)])

    args = main._build_parser().parse_args(["--publish-approved"])
    assert main._publish_approved(args, main.get_logger()) == 0

    published = json.loads(published_path.read_text())
    assert len(published) == 1  # succeeded despite the pre-poisoned state
    assert published[0]["hashtags_used"]


def test_release_dedupe_blocks_second_publish(pipeline) -> None:
    item_one = _queue_item(
        "https://github.com/ollama/ollama/releases/tag/v0.30.11",
        score=80,
        title="Ollama v0.30.11 adds MCP sandboxing",
    )
    JsonStore.save(pipeline["review_path"], [item_one])
    assert pipeline["run"]() == 0
    releases = json.loads(pipeline["releases_path"].read_text())
    assert releases[0]["project"] == "Ollama"
    assert releases[0]["version"] == "v0.30.11"

    # Same (project, version) from a different link/item must be blocked.
    item_two = _queue_item(
        "https://github.com/ollama/ollama/releases/tag/v0.30.11?again=1",
        score=80,
        title="ollama v0.30.11 ships MCP integration",
    )
    queue = json.loads(pipeline["review_path"].read_text())
    queue.append(item_two)
    JsonStore.save(pipeline["review_path"], queue)

    assert pipeline["run"]() == 0
    published = json.loads(pipeline["published_path"].read_text())
    assert len(published) == 1  # second one rejected by dedupe
    rejections = json.loads(pipeline["rejections_path"].read_text())
    assert any("Release dedupe" in "; ".join(r.get("reasons", [])) for r in rejections)
