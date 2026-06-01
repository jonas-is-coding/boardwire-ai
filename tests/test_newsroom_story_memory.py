from src.models import StoryLead
from src.newsroom.story_memory import StoryMemory


def _lead(headline, terms, beat="models", link="https://a.com/1"):
    return StoryLead(
        id="lead_abc123",
        headline=headline,
        beat=beat,
        angle_hypothesis="x",
        priority=10,
        main_link=link,
        member_links=[link],
        common_terms=terms,
    )


def test_record_creates_and_persists_storyline(tmp_path):
    path = tmp_path / "stories.json"
    mem = StoryMemory(path)
    lead = _lead("Model X2 ships", ["model", "weights", "x2"])
    line = mem.record(lead)
    mem.save()

    assert line.title == "Model X2 ships"
    assert path.exists()

    reloaded = StoryMemory(path)
    assert len(reloaded.storylines) == 1
    assert reloaded.storylines[0].beat == "models"


def test_match_finds_running_storyline(tmp_path):
    mem = StoryMemory(tmp_path / "stories.json")
    mem.record(_lead("Model X2 ships", ["model", "weights", "release", "acme"]))

    match = mem.match(["model", "weights", "release", "acme"], "models")
    assert match is not None

    # Different beat → no match even with same terms.
    assert mem.match(["model", "weights", "release", "acme"], "infra") is None
    # Unrelated terms → no match.
    assert mem.match(["funding", "round", "valuation"], "models") is None


def test_record_merges_followup_into_existing(tmp_path):
    mem = StoryMemory(tmp_path / "stories.json")
    mem.record(_lead("Model X2 ships", ["model", "weights", "acme", "release"], link="https://a.com/x2"))

    followup = _lead("Model X2 gets API", ["model", "weights", "acme", "api"], link="https://a.com/x2-api")
    line = mem.record(followup)

    assert len(mem.storylines) == 1  # merged, not duplicated
    assert "https://a.com/x2" in line.update_links
    assert "https://a.com/x2-api" in line.update_links
