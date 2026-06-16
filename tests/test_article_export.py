import json

from src.reports import article_export
from src.storage.json_store import JsonStore


def _review_item(link="https://news.example/quiet-comeback"):
    return {
        "id": "abc123",
        "status": "approved",
        "created_at": "2026-06-16T08:00:00Z",
        "score": 88,
        "reason": "A measurable conservation win backed by multiple sources.",
        "proposed_post": "Otters are back on the river.",
        "source_item": {
            "title": "River otters return after a decades-long cleanup",
            "source": "Example Wire",
            "link": link,
            "summary": "Otters spotted again on the upper river.",
        },
    }


def _dossier(link="https://news.example/quiet-comeback"):
    return {
        "lead_id": "lead_1",
        "headline": "River otters return after a decades-long cleanup",
        "summary": "After a 20-year cleanup the river's otter population has recovered.",
        "beat": "environment",
        "angle": "A slow, deliberate cleanup paying off",
        "key_facts": ["Otter sightings up sharply", "Water quality met targets in 2025"],
        "claims": [
            {"text": "Otters now breed on the upper river", "support": "verified",
             "source_links": [link, "https://b.example/otters"]},
            {"text": "Population is the largest in 40 years", "support": "single_source",
             "source_links": [link]},
        ],
        "numbers": ["20-year cleanup", "+300% sightings"],
        "quotes": [],
        "background": "The river was heavily polluted through the 1990s.",
        "open_questions": ["Will the recovery survive a dry summer?"],
        "source_urls": [link, "https://b.example/otters"],
        "used_llm": True,
    }


def test_load_dossier_index_by_url(tmp_path):
    d_dir = tmp_path / "dossiers"
    d_dir.mkdir()
    JsonStore.save(d_dir / "lead_1.json", _dossier())

    index = article_export.load_dossier_index(d_dir)
    assert "https://news.example/quiet-comeback" in index
    assert "https://b.example/otters" in index
    assert index["https://b.example/otters"]["beat"] == "environment"


def test_load_dossier_index_missing_dir(tmp_path):
    assert article_export.load_dossier_index(tmp_path / "nope") == {}


def test_fallback_article_uses_dossier_facts(tmp_path, monkeypatch):
    # Force the no-LLM path so we exercise the dossier-aware fallback.
    monkeypatch.setattr(article_export.voice, "tiffany_write_article", lambda **kw: None)

    d_dir = tmp_path / "dossiers"
    d_dir.mkdir()
    JsonStore.save(d_dir / "lead_1.json", _dossier())

    queue = tmp_path / "review_queue.json"
    JsonStore.save(queue, [_review_item()])
    out = tmp_path / "articles"

    written = article_export.export_review_articles(queue, out, dossiers_dir=d_dir)
    assert written == 1

    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    # Dossier facts made it into the prose.
    assert "Otter sightings up sharply" in text
    assert "corroborated across multiple sources" in text
    assert "reported by a single source" in text
    assert "Will the recovery survive a dry summer?" in text
    # Richer front matter for the website.
    assert "beat: environment" in text
    assert "verified: true" in text
    assert "reading_time:" in text
    assert "description:" in text
    assert "https://b.example/otters" in text


def test_dossier_passed_to_tiffany(tmp_path, monkeypatch):
    captured = {}

    def fake_tiffany(**kwargs):
        captured.update(kwargs)
        return "# Real headline\n\nA proper article body.\n\n## Sources\n\n- [x](https://x)"

    monkeypatch.setattr(article_export.voice, "tiffany_write_article", fake_tiffany)

    d_dir = tmp_path / "dossiers"
    d_dir.mkdir()
    JsonStore.save(d_dir / "lead_1.json", _dossier())

    queue = tmp_path / "review_queue.json"
    JsonStore.save(queue, [_review_item()])
    out = tmp_path / "articles"

    article_export.export_review_articles(queue, out, dossiers_dir=d_dir)
    assert captured["dossier"] is not None
    assert captured["dossier"]["beat"] == "environment"

    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert "# Real headline" in text
    assert text.startswith("---")  # front matter prepended to the LLM body


def test_hero_image_uses_card_path(tmp_path, monkeypatch):
    monkeypatch.delenv("BOARDWIRE_ARTICLE_IMAGE_BASE_URL", raising=False)
    monkeypatch.setattr(article_export.voice, "tiffany_write_article", lambda **kw: None)
    item = _review_item()
    item["card_path"] = "generated/cards/abc123.png"

    queue = tmp_path / "review_queue.json"
    JsonStore.save(queue, [item])
    out = tmp_path / "articles"
    article_export.export_review_articles(queue, out, dossiers_dir=tmp_path / "none")

    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert 'hero_image: "generated/cards/abc123.png"' in text


def test_hero_image_uses_public_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDWIRE_ARTICLE_IMAGE_BASE_URL", "https://cdn.example/cards/")
    monkeypatch.setattr(article_export.voice, "tiffany_write_article", lambda **kw: None)
    item = _review_item()
    item["card_path"] = "generated/cards/abc123.png"

    queue = tmp_path / "review_queue.json"
    JsonStore.save(queue, [item])
    out = tmp_path / "articles"
    article_export.export_review_articles(queue, out, dossiers_dir=tmp_path / "none")

    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert 'hero_image: "https://cdn.example/cards/abc123.png"' in text


def test_hero_image_empty_without_card(tmp_path, monkeypatch):
    monkeypatch.delenv("BOARDWIRE_ARTICLE_IMAGE_BASE_URL", raising=False)
    monkeypatch.setattr(article_export.voice, "tiffany_write_article", lambda **kw: None)
    queue = tmp_path / "review_queue.json"
    JsonStore.save(queue, [_review_item()])  # no card_path
    out = tmp_path / "articles"
    article_export.export_review_articles(queue, out, dossiers_dir=tmp_path / "none")

    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert 'hero_image: ""' in text


def test_export_without_dossier_is_backward_compatible(tmp_path, monkeypatch):
    monkeypatch.setattr(article_export.voice, "tiffany_write_article", lambda **kw: None)

    queue = tmp_path / "review_queue.json"
    JsonStore.save(queue, [_review_item()])
    out = tmp_path / "articles"

    written = article_export.export_review_articles(queue, out, dossiers_dir=tmp_path / "none")
    assert written == 1
    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert 'title: "River otters return after a decades-long cleanup"' in text
    assert "source: Example Wire" in text
    assert "## Sources" in text
    # No dossier → no verified flag emitted.
    assert "verified:" not in text
