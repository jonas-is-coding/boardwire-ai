from __future__ import annotations

from datetime import datetime, timezone

from src.main import _select_published_for_delete, _uris_for_published_item


def test_uris_for_published_item_prefers_thread_uris_without_duplicate_external_id() -> None:
    item = {
        "external_id": "at://did/app.bsky.feed.post/1",
        "thread_uris": ["at://did/app.bsky.feed.post/1", "at://did/app.bsky.feed.post/2"],
    }

    assert _uris_for_published_item(item) == [
        "at://did/app.bsky.feed.post/1",
        "at://did/app.bsky.feed.post/2",
    ]


def test_select_published_for_delete_filters_by_age_platform_limit_and_deleted() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    posts = [
        {
            "id": "oldest",
            "platform": "bluesky",
            "published_at": "2026-07-16T08:00:00Z",
            "external_id": "at://did/app.bsky.feed.post/oldest",
        },
        {
            "id": "newer-but-eligible",
            "platform": "bluesky",
            "published_at": "2026-07-16T10:30:00Z",
            "external_id": "at://did/app.bsky.feed.post/newer",
        },
        {
            "id": "too-new",
            "platform": "bluesky",
            "published_at": "2026-07-16T11:30:00Z",
            "external_id": "at://did/app.bsky.feed.post/new",
        },
        {
            "id": "other-platform",
            "platform": "mastodon",
            "published_at": "2026-07-16T08:00:00Z",
            "external_id": "mastodon-1",
        },
        {
            "id": "already-deleted",
            "platform": "bluesky",
            "published_at": "2026-07-16T08:00:00Z",
            "external_id": "at://did/app.bsky.feed.post/deleted",
            "deleted_at": "2026-07-16T09:00:00Z",
        },
    ]

    selected = _select_published_for_delete(posts, older_than_hours=1, limit=1, now=now)

    assert [item["id"] for item in selected] == ["oldest"]
