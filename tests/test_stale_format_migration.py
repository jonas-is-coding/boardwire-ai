from __future__ import annotations

from logging import getLogger

from src.composer import COMPOSER_VERSION
from src.main import migrate_review_queue_composition

_LOGGER = getLogger("test")


def _item(status: str, **overrides) -> dict:
    base = {
        "id": "item-1",
        "status": status,
        "created_at": "2026-07-15T10:00:00Z",
        "source_item": {"title": "A story", "link": "https://example.com/x", "summary": "s"},
        "proposed_post": "some editor draft text",
    }
    base.update(overrides)
    return base


def _valid_package() -> dict:
    return {
        "title": "Agent memory is now infrastructure.",
        "subtitle": "Agentmemory ships persistent state for coding agents.",
        "description": "4-tier local pipeline.",
        "hashtags": ["#AI", "#AIAgents"],
        "question": "",
    }


def test_recomposes_item_with_valid_package() -> None:
    item = _item("approved", sarah_package=_valid_package())
    recomposed, expired = migrate_review_queue_composition([item], _LOGGER)
    assert (recomposed, expired) == (1, 0)
    assert item["composer_version"] == COMPOSER_VERSION
    # Recomposed to the new format: hook + hashtags present, no old markers.
    assert "Agent memory is now infrastructure." in item["proposed_post"]
    assert "#AI" in item["proposed_post"]
    assert "Quelle:" not in item["proposed_post"]


def test_expires_old_format_text_without_package() -> None:
    old_text = (
        "Old headline.\n\nOld subtitle.\n\nOld description.\n\n"
        "📖 Read the full article: file:///x\nQuelle: https://example.com/x"
    )
    item = _item("approved", proposed_post=old_text)
    recomposed, expired = migrate_review_queue_composition([item], _LOGGER)
    assert (recomposed, expired) == (0, 1)
    assert item["status"] == "expired_deferred"
    assert "migration_note" in item


def test_leaves_fresh_editor_draft_untouched() -> None:
    # No package, but the stored text is a plain Editor draft (not old-format).
    # Publish will regenerate it, so migration must not expire it.
    item = _item("approved", proposed_post="Prompt injection can extract history from Claude.")
    recomposed, expired = migrate_review_queue_composition([item], _LOGGER)
    assert (recomposed, expired) == (0, 0)
    assert item["status"] == "approved"
    assert "composer_version" not in item


def test_already_current_version_skipped() -> None:
    item = _item("approved", sarah_package=_valid_package(), composer_version=COMPOSER_VERSION)
    before = dict(item)
    recomposed, expired = migrate_review_queue_composition([item], _LOGGER)
    assert (recomposed, expired) == (0, 0)
    assert item["proposed_post"] == before["proposed_post"]


def test_non_pending_items_ignored() -> None:
    item = _item("published_dry_run", proposed_post="📖 Read the full article: x\nQuelle: y")
    recomposed, expired = migrate_review_queue_composition([item], _LOGGER)
    assert (recomposed, expired) == (0, 0)
    assert item["status"] == "published_dry_run"
