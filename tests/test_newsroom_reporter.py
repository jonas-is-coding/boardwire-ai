from datetime import datetime, timezone

from src.models import FeedItem, StoryLead
from src.newsroom.config import NewsroomConfig
from src.newsroom.reporter import Reporter
from src.research.fetcher import FetchedDoc


def _config(**over):
    base = dict(
        enabled=True,
        max_stories=2,
        fetch_fulltext=True,
        max_fetch_per_story=5,
        web_search=False,
        web_results=4,
    )
    base.update(over)
    return NewsroomConfig(**base)


def _lead():
    return StoryLead(
        id="lead_x",
        headline="Acme ships Model X2 with open weights",
        beat="models",
        angle_hypothesis="2 sources converging on models",
        priority=50,
        main_link="https://a.com/x2",
        member_links=["https://a.com/x2", "https://b.com/x2"],
        sources=["Acme", "HN"],
        common_terms=["model", "weights", "x2"],
    )


def _items():
    return {
        "https://a.com/x2": FeedItem("Acme", "Model X2", "https://a.com/x2", "rss summary a", datetime(2026, 5, 28, tzinfo=timezone.utc), 1),
        "https://b.com/x2": FeedItem("HN", "X2 thread", "https://b.com/x2", "rss summary b", datetime(2026, 5, 28, tzinfo=timezone.utc), 3, 200.0),
    }


def _fake_fetcher(urls, **kwargs):
    texts = {
        "https://a.com/x2": "Acme released Model X2 with open weights. It scores 71% on SWE-bench.",
        "https://b.com/x2": "Community notes Model X2 is Apache-2.0 licensed and runs on a single GPU.",
    }
    return [FetchedDoc(url=u, ok=True, status=200, title="t", text=texts.get(u, "")) for u in urls]


def test_reporter_builds_llm_dossier():
    captured = {}

    def fake_llm(system, user):
        captured["user"] = user
        return {
            "summary": "Acme released Model X2 with open weights.",
            "angle": "Open-weights model you can run on one GPU",
            "key_facts": ["Open weights", "71% on SWE-bench", "Apache-2.0"],
            "claims": [
                {"text": "X2 scores 71% on SWE-bench", "support": "single_source", "source_links": ["https://a.com/x2"]},
                {"text": "X2 is Apache-2.0", "support": "verified", "source_links": ["https://a.com/x2", "https://b.com/x2"]},
            ],
            "numbers": ["SWE-bench: 71%"],
            "quotes": [],
            "background": "Follows the X-series.",
            "open_questions": ["Pricing for hosted API?"],
        }

    reporter = Reporter(llm_json=fake_llm, fetcher=_fake_fetcher)
    dossier = reporter.research(_lead(), config=_config(), items_by_link=_items())

    assert dossier.used_llm is True
    assert dossier.angle == "Open-weights model you can run on one GPU"
    assert "Open weights" in dossier.key_facts
    assert len(dossier.claims) == 2
    assert dossier.claims[1].support == "verified"
    assert dossier.source_urls == ["https://a.com/x2", "https://b.com/x2"]
    # Full text (not just RSS summary) reached the prompt.
    assert "SWE-bench" in captured["user"]


def test_reporter_falls_back_to_extractive_without_llm():
    reporter = Reporter(llm_json=None, fetcher=_fake_fetcher)
    dossier = reporter.research(_lead(), config=_config(), items_by_link=_items())

    assert dossier.used_llm is False
    assert dossier.summary
    assert dossier.source_urls == ["https://a.com/x2", "https://b.com/x2"]
    # Two sources → the headline claim is treated as corroborated.
    assert dossier.claims[0].support == "verified"


def test_reporter_recovers_from_llm_error():
    def boom(system, user):
        raise RuntimeError("llm down")

    reporter = Reporter(llm_json=boom, fetcher=_fake_fetcher)
    dossier = reporter.research(_lead(), config=_config(), items_by_link=_items())
    assert dossier.used_llm is False
    assert dossier.summary
