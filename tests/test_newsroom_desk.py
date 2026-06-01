from datetime import datetime, timezone

from src.clustering import NewsCluster
from src.models import FeedItem
from src.newsroom.desk import classify_beat, lead_from_cluster


def _item(source, title, link, tier=2, eng=0.0):
    return FeedItem(
        source=source,
        title=title,
        link=link,
        summary=title,
        published_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        source_tier=tier,
        engagement_score=eng,
    )


def _cluster(main, members, common_terms, score=42, eng=120.0):
    sources = sorted({m.source for m in members})
    return NewsCluster(
        id="c1",
        items=members,
        main_item=main,
        sources=sources,
        source_count=len(sources),
        total_engagement_score=eng,
        best_source_tier=min(m.source_tier for m in members),
        cluster_score=score,
        common_terms=common_terms,
        cluster_summary=f"{len(sources)} sources",
    )


def test_classify_beat_picks_specific_beat():
    assert classify_beat("New autonomous agent with MCP tool use") == "agents"
    assert classify_beat("Open weights model release on GitHub") in {"models", "open_source"}
    assert classify_beat("vLLM inference throughput on GPU") == "infra"
    assert classify_beat("Series B funding round announced") == "business"
    assert classify_beat("some unrelated chatter") == "general"


def test_lead_from_cluster_collects_member_links():
    main = _item("OpenAI", "Model X2 ships with open weights", "https://a.com/x2", tier=1)
    other = _item("HN", "Model X2 discussion", "https://b.com/x2", tier=3, eng=200.0)
    cluster = _cluster(main, [main, other], ["model", "weights", "x2"])

    lead = lead_from_cluster(cluster)

    assert lead.headline == "Model X2 ships with open weights"
    assert lead.main_link == "https://a.com/x2"
    assert set(lead.member_links) == {"https://a.com/x2", "https://b.com/x2"}
    assert lead.priority == 42
    assert lead.source_tier == 1
    assert lead.beat in {"models", "open_source"}
    assert lead.id.startswith("lead_")
    assert lead.is_followup is False


def test_lead_marks_followup_when_storyline_given():
    main = _item("OpenAI", "Model X3 ships", "https://a.com/x3", tier=1)
    cluster = _cluster(main, [main], ["model", "x3"])

    class _Story:
        id = "story_abc"

    lead = lead_from_cluster(cluster, storyline=_Story())
    assert lead.is_followup is True
    assert lead.storyline_id == "story_abc"
