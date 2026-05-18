from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dateutil import parser as date_parser

from src.board.evaluator import evaluate_item
from src.board.llm_evaluator import evaluate_with_optional_llm
from src.board.personas import load_personas
from src.collector.rss_collector import fetch_all
from src.cards.card_data import from_review_item
from src.cards.renderer import render_card_png
from src.config import (
    CARDS_DIR,
    DRAFTS_PATH,
    MAX_ITEMS_PER_RUN,
    PERSONAS_PATH,
    PUBLISHED_POSTS_PATH,
    QUALITY_PATH,
    REVIEW_QUEUE_PATH,
    REVIEW_REPORT_PATH,
    SAMPLE_ITEMS_PATH,
    SEEN_ITEMS_PATH,
    SOURCES_PATH,
)
from src.llm.client import LLMConfig, load_llm_config
from src.models import DraftPost, FeedItem, Source
from src.publisher.base import PublishResult
from src.publisher.bluesky_publisher import BlueskyPublisher
from src.publisher.dry_run_publisher import DryRunPublisher
from src.quality.gates import QualityConfig, check_quality
from src.reports.review_report import generate_review_queue_report
from src.storage.json_store import JsonStore
from src.notifications import slack as notify
from src.utils.logger import get_logger
from src.writer.post_writer import generate_post

VALID_REVIEW_STATUSES = {"pending_review", "approved", "rejected", "published_dry_run", "deferred_due_to_cap", "expired_deferred"}
VALID_PUBLISHERS = {"dry_run", "bluesky"}


def _compose_sarah_post(package: dict[str, str | list[str]]) -> str:
    title = str(package.get("title", "")).strip()
    subtitle = str(package.get("subtitle", "")).strip()
    description = str(package.get("description", "")).strip()
    raw_tags = package.get("hashtags", [])
    tags = [str(t).strip() for t in raw_tags] if isinstance(raw_tags, list) else []
    tags_line = " ".join(t for t in tags if t)[:90]
    post = f"{title}\n{subtitle}\n\n{description}\n\n{tags_line}".strip()
    return post[:280]


def _load_sources() -> list[Source]:
    raw = JsonStore.load(SOURCES_PATH, default=[])
    return [
        Source(
            name=s["name"],
            url=s["url"],
            enabled=s.get("enabled", True),
            fallback_urls=s.get("fallback_urls"),
        )
        for s in raw
    ]


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _load_fixture_items() -> list[FeedItem]:
    raw = JsonStore.load(SAMPLE_ITEMS_PATH, default=[])
    items: list[FeedItem] = []
    seen_links: set[str] = set()
    for entry in raw:
        link = str(entry.get("link", "")).strip()
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        items.append(
            FeedItem(
                source=str(entry.get("source", "Unknown Source")),
                title=str(entry.get("title", "Untitled")),
                link=link,
                summary=str(entry.get("summary", "")),
                published_at=_parse_dt(entry.get("published_at")),
            )
        )
    return items


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Boardwire AI dry-run CLI")
    parser.add_argument("--debug-sources", action="store_true", help="Only fetch sources and print per-source counts and newest titles.")
    parser.add_argument("--limit", type=int, default=MAX_ITEMS_PER_RUN, help=f"Limit total candidates to process (default: {MAX_ITEMS_PER_RUN}).")
    parser.add_argument("--llm", action="store_true", help="Force LLM mode if provider is configured.")
    parser.add_argument("--llm-provider", choices=["none", "openai", "gemini"], default=None, help="Override BOARDWIRE_LLM_PROVIDER for this run.")
    parser.add_argument("--no-llm", action="store_true", help="Force rule-based mode.")
    parser.add_argument("--max-llm-items", type=int, default=None, help="Override BOARDWIRE_MAX_LLM_ITEMS for this run.")
    parser.add_argument("--use-fixtures", action="store_true", help="Load offline fixture items instead of RSS sources.")
    parser.add_argument("--review", action="store_true", help="Save quality-approved drafts to review queue.")
    parser.add_argument("--list-review-queue", action="store_true", help="List pending review queue items.")
    parser.add_argument("--list-deferred", action="store_true", help="List deferred_due_to_cap items.")
    parser.add_argument("--approve-review", type=str, default=None, help="Approve one review queue item by ID.")
    parser.add_argument("--reject-review", type=str, default=None, help="Reject one review queue item by ID.")
    parser.add_argument("--publish-approved", action="store_true", help="Publish approved review items in dry-run mode.")
    parser.add_argument("--list-published", action="store_true", help="List published dry-run posts.")
    parser.add_argument("--publisher", choices=["dry_run", "bluesky"], default=None, help="Publisher backend for --publish-approved.")
    parser.add_argument("--confirm-real-publish", action="store_true", help="Required confirmation flag for real publishing.")
    parser.add_argument("--quality-report", action="store_true", help="Print quality gate pass/fail reasons for each candidate.")
    parser.add_argument("--self-check-writer", action="store_true", help="Generate fixture posts and run quality gates as a writer self-check.")
    parser.add_argument("--max-posts-per-day", type=int, default=None, help="Override BOARDWIRE_MAX_POSTS_PER_DAY for this run.")
    parser.add_argument("--reset-fixture-state", action="store_true", help="Clear fixture-related seen/draft/review state (requires --use-fixtures).")
    parser.add_argument("--generate-review-report", action="store_true", help="Generate reports/review_queue.md from pending review items.")
    parser.add_argument("--generate-card", type=str, default=None, help="Generate one card for a review item ID.")
    parser.add_argument("--generate-cards", action="store_true", help="Generate cards for pending_review and approved items missing card_path.")
    parser.add_argument("--regenerate-cards", action="store_true", help="Regenerate cards for pending_review and approved items, even if card_path exists.")
    parser.add_argument("--ignore-daily-cap", action="store_true", help="Development-only: bypass daily cap checks for this run.")
    parser.add_argument("--create-test-review-item", action="store_true", help="Development-only: create one pending review item from fixtures.")
    return parser


def _review_id(link: str, created_at: str) -> str:
    return hashlib.sha1(f"{link}|{created_at}".encode("utf-8")).hexdigest()[:12]


def _queue_from_drafts(drafts: list[DraftPost]) -> list[dict]:
    queue_items: list[dict] = []
    for draft in drafts:
        if not draft.should_post:
            continue
        rid = _review_id(draft.link, draft.created_at)
        queue_items.append(
            {
                "id": rid,
                "status": "pending_review",
                "created_at": draft.created_at,
                "score": draft.score,
                "reason": draft.reason,
                "proposed_post": draft.post_text,
                "source_angle": draft.source_angle,
                "source_item": {
                    "title": draft.title,
                    "source": draft.source,
                    "link": draft.link,
                },
                "card_path": None,
            }
        )
    return queue_items


def _load_quality_config() -> QualityConfig:
    raw = JsonStore.load(QUALITY_PATH, default={})
    return QualityConfig(
        max_post_length=int(raw.get("max_post_length", 280)),
        min_llm_score=int(raw.get("min_llm_score", 60)),
        min_rule_score=int(raw.get("min_rule_score", 5)),
        max_defer_count=int(raw.get("max_defer_count", 3)),
        duplicate_lookback_hours=int(raw.get("duplicate_lookback_hours", 168)),
        fixture_duplicate_lookback_hours=int(raw.get("fixture_duplicate_lookback_hours", 1)),
        banned_phrases=list(raw.get("banned_phrases", [])),
        generic_phrases=list(raw.get("generic_phrases", [])),
    )


def _is_within_lookback(
    timestamp: str | None,
    now: datetime,
    lookback_hours: int,
    fixture_mode: bool,
) -> bool:
    if not timestamp:
        return not fixture_mode
    dt = _parse_dt(timestamp)
    if fixture_mode and not timestamp:
        return False
    delta = now - dt
    return delta.total_seconds() <= lookback_hours * 3600


def _history_posts(
    drafts_data: list[dict],
    review_queue_data: list[dict],
    published_data: list[dict],
    now: datetime,
    lookback_hours: int,
    fixture_mode: bool,
) -> list[str]:
    posts: list[str] = []
    for item in drafts_data:
        if _is_within_lookback(item.get("created_at"), now, lookback_hours, fixture_mode):
            post = str(item.get("post_text", ""))
            if post.strip():
                posts.append(post)
    for item in review_queue_data:
        if _is_within_lookback(item.get("created_at"), now, lookback_hours, fixture_mode):
            post = str(item.get("proposed_post", ""))
            if post.strip():
                posts.append(post)
    for item in published_data:
        if _is_within_lookback(item.get("published_at"), now, lookback_hours, fixture_mode):
            post = str(item.get("post", ""))
            if post.strip():
                posts.append(post)
    return posts


def _history_for_publish_item(
    drafts_data: list[dict],
    review_queue_data: list[dict],
    published_data: list[dict],
    review_id: str | None,
    now: datetime,
    lookback_hours: int,
) -> list[str]:
    posts: list[str] = []
    for item in drafts_data:
        if _is_within_lookback(item.get("created_at"), now, lookback_hours, fixture_mode=False):
            post = str(item.get("post_text", ""))
            if post.strip():
                posts.append(post)
    for item in review_queue_data:
        if item.get("id") == review_id:
            continue
        if _is_within_lookback(item.get("created_at"), now, lookback_hours, fixture_mode=False):
            post = str(item.get("proposed_post", ""))
            if post.strip():
                posts.append(post)
    for item in published_data:
        if _is_within_lookback(item.get("published_at"), now, lookback_hours, fixture_mode=False):
            post = str(item.get("post", ""))
            if post.strip():
                posts.append(post)
    return posts


def _published_history_only(
    published_data: list[dict],
    now: datetime,
    lookback_hours: int,
) -> list[str]:
    posts: list[str] = []
    for item in published_data:
        if _is_within_lookback(item.get("published_at"), now, lookback_hours, fixture_mode=False):
            post = str(item.get("post", ""))
            if post.strip():
                posts.append(post)
    return posts


def _history_for_review_item(
    drafts_data: list[dict],
    review_queue_data: list[dict],
    published_data: list[dict],
    now: datetime,
    lookback_hours: int,
    fixture_mode: bool,
    candidate_id: str | None,
    candidate_link: str | None,
    is_reprocessing_deferred: bool,
) -> list[str]:
    posts: list[str] = []
    for item in drafts_data:
        if _is_within_lookback(item.get("created_at"), now, lookback_hours, fixture_mode):
            post = str(item.get("post_text", ""))
            if post.strip():
                posts.append(post)

    for item in review_queue_data:
        if _is_within_lookback(item.get("created_at"), now, lookback_hours, fixture_mode):
            # Ignore self duplicate when reprocessing deferred item.
            if is_reprocessing_deferred:
                same_id = candidate_id and item.get("id") == candidate_id
                same_link_deferred = (
                    candidate_link
                    and item.get("status") == "deferred_due_to_cap"
                    and item.get("source_item", {}).get("link") == candidate_link
                )
                if same_id or same_link_deferred:
                    continue
            post = str(item.get("proposed_post", ""))
            if post.strip():
                posts.append(post)

    for item in published_data:
        if _is_within_lookback(item.get("published_at"), now, lookback_hours, fixture_mode):
            post = str(item.get("post", ""))
            if post.strip():
                posts.append(post)

    return posts


def _list_review_queue(logger) -> int:
    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    for item in queue:
        if item.get("status") not in VALID_REVIEW_STATUSES:
            item["status"] = "pending_review"
    pending = [item for item in queue if item.get("status") == "pending_review"]

    if not pending:
        logger.info("Review queue is empty")
        return 0

    logger.info("Pending review items: %d", len(pending))
    for item in pending:
        src = item.get("source_item", {})
        logger.info("ID: %s | Score: %s | Source: %s", item.get("id"), item.get("score"), src.get("source", "Unknown"))
        logger.info("Title: %s", src.get("title", "Untitled"))
        logger.info("Proposed post: %s", item.get("proposed_post", ""))
    return 0


def _generate_review_report(logger) -> int:
    pending = generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
    logger.info("Generated review report: %s", REVIEW_REPORT_PATH)
    logger.info("Pending items in report: %d", pending)
    return 0


def _generate_card_for_item(item: dict, logger) -> str | None:
    review_id = str(item.get("id", "")).strip()
    if not review_id:
        return None
    logger.info("Generating card for: %s", review_id)
    card_data = from_review_item(item)
    output_path = CARDS_DIR / f"{review_id}.png"
    render_card_png(card_data, output_path)
    rel = f"generated/cards/{review_id}.png"
    logger.info("Saved card: %s", rel)
    return rel


def _generate_card_for_id(review_id: str, logger) -> int:
    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    for item in queue:
        if item.get("id") == review_id:
            card_path = _generate_card_for_item(item, logger)
            if card_path:
                item["card_path"] = card_path
                JsonStore.save(REVIEW_QUEUE_PATH, queue)
                generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
                return 0
    logger.warning("Review item not found for card generation: %s", review_id)
    return 1


def _generate_cards(logger) -> int:
    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    generated = 0
    for item in queue:
        status = item.get("status")
        if status not in {"pending_review", "approved"}:
            continue
        if item.get("card_path"):
            continue
        card_path = _generate_card_for_item(item, logger)
        if card_path:
            item["card_path"] = card_path
            generated += 1
    JsonStore.save(REVIEW_QUEUE_PATH, queue)
    generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
    logger.info("Generated cards: %d", generated)
    return 0


def _regenerate_cards(logger) -> int:
    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    regenerated = 0
    for item in queue:
        status = item.get("status")
        if status not in {"pending_review", "approved"}:
            continue
        card_path = _generate_card_for_item(item, logger)
        if card_path:
            item["card_path"] = card_path
            regenerated += 1
    JsonStore.save(REVIEW_QUEUE_PATH, queue)
    generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
    logger.info("Regenerated cards: %d", regenerated)
    return 0


def _create_test_review_item(logger) -> int:
    fixtures = _load_fixture_items()
    if not fixtures:
        logger.warning("No fixture items found")
        return 1

    item = fixtures[0]
    evaluation = evaluate_item(item, personas=[])
    post_text = generate_post(item, evaluation)
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rid = _review_id(item.link, created_at)

    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    for existing in queue:
        if existing.get("id") == rid:
            logger.info("Test review item already exists: %s", rid)
            return 0

    test_item = {
        "id": rid,
        "status": "pending_review",
        "created_at": created_at,
        "score": evaluation.score,
        "reason": evaluation.reason,
        "proposed_post": post_text,
        "source_angle": "Rule-based test item",
        "source_item": {
            "title": item.title,
            "source": item.source,
            "link": item.link,
        },
        "is_llm_mode": False,
        "card_path": None,
    }
    queue.append(test_item)
    JsonStore.save(REVIEW_QUEUE_PATH, queue)
    generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
    logger.info("Created test review item: %s", rid)
    return 0


def _list_deferred(logger) -> int:
    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    deferred = [item for item in queue if item.get("status") == "deferred_due_to_cap"]
    if not deferred:
        logger.info("Deferred queue is empty")
        return 0
    logger.info("Deferred items: %d", len(deferred))
    deferred_sorted = sorted(deferred, key=lambda x: int(x.get("score") or 0), reverse=True)
    for item in deferred_sorted:
        src = item.get("source_item", {})
        logger.info(
            "ID: %s | Title: %s | Score: %s | Defer count: %s | Deferred at: %s",
            item.get("id"),
            src.get("title", "Untitled"),
            item.get("score"),
            item.get("defer_count", 1),
            item.get("deferred_at", ""),
        )
    return 0


def _update_review_status(review_id: str, status: str, logger) -> int:
    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    updated = False
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for item in queue:
        if item.get("id") == review_id:
            current = item.get("status", "pending_review")
            if current == "published_dry_run":
                logger.warning("Review item %s is already published_dry_run", review_id)
                return 1
            item["status"] = status
            item["reviewed_at"] = now
            updated = True
            break

    if not updated:
        logger.warning("Review item not found: %s", review_id)
        return 1

    JsonStore.save(REVIEW_QUEUE_PATH, queue)
    generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
    logger.info("Review item %s marked as %s", review_id, status)

    for item in queue:
        if item.get("id") == review_id:
            title = item.get("source_item", {}).get("title", review_id)
            if status == "approved":
                notify.michael_human_approved(review_id, title)
            elif status == "rejected":
                notify.michael_human_rejected(review_id, title)
            break

    return 0


def _resolve_publisher(args, logger):
    configured = os.getenv("BOARDWIRE_PUBLISHER", "dry_run").strip().lower() or "dry_run"
    selected = args.publisher or configured
    if selected not in VALID_PUBLISHERS:
        logger.warning("Invalid publisher '%s', defaulting to dry_run", selected)
        selected = "dry_run"

    if selected == "dry_run":
        return DryRunPublisher(), "dry_run"

    real_enabled = os.getenv("BOARDWIRE_REAL_PUBLISH_ENABLED", "false").strip().lower() == "true"
    if not real_enabled:
        logger.error("Refusing %s publish: BOARDWIRE_REAL_PUBLISH_ENABLED must be true", selected)
        return None, selected
    if not args.confirm_real_publish:
        logger.error("Refusing %s publish: missing --confirm-real-publish", selected)
        return None, selected

    if selected == "bluesky":
        handle = os.getenv("BLUESKY_HANDLE", "").strip()
        app_password = os.getenv("BLUESKY_APP_PASSWORD", "").strip()
        if not handle or not app_password:
            logger.error("Refusing Bluesky publish: BLUESKY_HANDLE and BLUESKY_APP_PASSWORD are required")
            return None, "bluesky"
        return BlueskyPublisher(handle=handle, app_password=app_password), "bluesky"
    logger.error("Unsupported publisher: %s", selected)
    return None, selected


def _build_publish_caption(item: dict) -> str:
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "")).strip()
    lower = title.lower()
    core = "Check whether this changes measurable capability, reliability, or cost in real AI workloads."
    tags = ["#AI", "#Boardwire"]

    if any(k in lower for k in ("agent", "workflow", "tooling", "agentic")):
        core = "Agent reliability in production is still the hard part — check whether the evals reflect real task completion."
        tags = ["#AIAgents", "#BuildersAI", "#Boardwire"]
    elif any(k in lower for k in ("open source", "open-source", "open model", "open-weight", "weights")):
        core = "Open weights: you can inspect it, run it locally, and fine-tune — worth evaluating against your current stack."
        tags = ["#OpenSource", "#LLM", "#Boardwire"]
    elif any(k in lower for k in ("benchmark", "evaluation", "leaderboard", " eval ")):
        core = "A benchmark only matters if the eval setup is public and the tasks map to something you need in production."
        tags = ["#Benchmark", "#BuildersAI", "#Boardwire"]
    elif any(k in lower for k in ("robot", "robotics")):
        core = "Robotics progress is meaningful when it holds outside curated demos — look for generalization results."
        tags = ["#Robotics", "#AI", "#Boardwire"]
    elif any(k in lower for k in ("infra", "inference", "deployment", "serving", "latency")):
        core = "Inference improvements compound fast — check whether the numbers hold under sustained load, not just peak tests."
        tags = ["#MLOps", "#Inference", "#Boardwire"]
    elif any(k in lower for k in ("fine-tun", "training", "dataset")):
        core = "Training improvements matter most when they reduce cost or data requirements — see if the method is reproducible."
        tags = ["#MLTraining", "#BuildersAI", "#Boardwire"]
    elif any(k in lower for k in ("rag", "retrieval", "embedding")):
        core = "Retrieval quality is the bottleneck most RAG systems hit first — check recall on domain-specific data."
        tags = ["#RAG", "#BuildersAI", "#Boardwire"]

    tag_str = " ".join(tags)
    if title:
        caption = f"{core} — {title.rstrip('.')}. {tag_str}"
    else:
        caption = f"{core} {tag_str}"
    return caption[:280]


def _resolve_card_image_path(item: dict, logger) -> str | None:
    card_path = str(item.get("card_path") or "").strip()
    if not card_path:
        return None

    raw = Path(card_path)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(CARDS_DIR / raw.name)
        if card_path.startswith("generated/"):
            candidates.append(Path.cwd() / card_path)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    logger.warning("Card path set but file missing: %s", card_path)
    return None


def _build_image_alt_text(item: dict) -> str:
    source_item = item.get("source_item", {})
    title = " ".join(str(source_item.get("title", "")).split()).strip()
    source = " ".join(str(source_item.get("source", "")).split()).strip()
    if title and source:
        return f"Boardwire card: {title} ({source})"
    if title:
        return f"Boardwire card: {title}"
    if source:
        return f"Boardwire card from {source}"
    return "Boardwire news card"


def _publish_approved(args, logger) -> int:
    from src.notifications import persona_voice as voice

    queue = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    published = JsonStore.load(PUBLISHED_POSTS_PATH, default=[])
    quality_config = _load_quality_config()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    now_dt = datetime.now(timezone.utc)
    publisher, selected_platform = _resolve_publisher(args, logger)
    if publisher is None:
        return 1

    existing_ids = {item.get("id") for item in published}
    existing_links = {item.get("source_link") for item in published}

    logger.info("Publishing approved posts in %s mode", selected_platform)
    published_count = 0
    quality_rejected_count = 0
    blocked_missing_image_count = 0
    posted_with_image_count = 0

    for item in queue:
        status = item.get("status", "pending_review")
        rid = item.get("id")
        if status not in VALID_REVIEW_STATUSES:
            status = "pending_review"
            item["status"] = status

        auto_approved_legacy = status == "pending_review" and bool(str(item.get("chloe_note", "")).strip())
        if status != "approved" and not auto_approved_legacy:
            continue
        if auto_approved_legacy:
            item["status"] = "approved"
            logger.info("Auto-upgraded legacy pending_review item to approved: %s", rid)

        source_item = item.get("source_item", {})
        source_link = source_item.get("link")
        if rid in existing_ids or source_link in existing_links:
            logger.info("Skipped already published item: %s", rid)
            item["status"] = "published_dry_run"
            continue

        source_summary = str(source_item.get("summary", "")).strip()
        base_post_text = str(item.get("proposed_post") or "").strip() or _build_publish_caption(item)
        sarah_package = voice.sarah_build_publish_package(
            title=str(source_item.get("title", "Untitled")),
            source=str(source_item.get("source", "Unknown Source")),
            reason=str(item.get("reason", "")),
            score=int(item.get("score") or 0),
            claire_note=str(item.get("claire_note", "")),
            chloe_note=str(item.get("chloe_note", "")),
            post_text=base_post_text,
            summary=source_summary,
        )
        if sarah_package:
            item["sarah_package"] = sarah_package
            post_text = _compose_sarah_post(sarah_package)
            item["proposed_post"] = post_text
            notify.sarah_packaged(
                title=str(sarah_package.get("title", "")),
                subtitle=str(sarah_package.get("subtitle", "")),
                description=str(sarah_package.get("description", "")),
                hashtags=[str(x) for x in sarah_package.get("hashtags", [])] if isinstance(sarah_package.get("hashtags"), list) else [],
            )
            try:
                regenerated = _generate_card_for_item(item, logger)
                if regenerated:
                    item["card_path"] = regenerated
                    logger.info("Card regenerated with Sarah package: %s", regenerated)
            except Exception as exc:
                logger.warning("Card regeneration after Sarah failed for %s: %s", rid, exc)
        else:
            post_text = base_post_text
        card_path = item.get("card_path")
        if selected_platform == "bluesky":
            logger.info("Image required for Bluesky: %s", rid)
        abs_card_path = _resolve_card_image_path(item, logger)
        if selected_platform == "bluesky" and not abs_card_path:
            logger.info("Card missing, regenerating: %s", rid)
            try:
                regenerated = _generate_card_for_item(item, logger)
            except Exception as exc:  # pragma: no cover - defensive publish safety
                logger.warning("Card regeneration failed for %s: %s", rid, exc)
                regenerated = None
            if regenerated:
                item["card_path"] = regenerated
                card_path = regenerated
                logger.info("Card generated: %s", regenerated)
                abs_card_path = _resolve_card_image_path(item, logger)
        logger.info("Publish quality check for: %s", rid)
        logger.info("Ignoring draft/review duplicates during publish context")
        history = _published_history_only(
            published,
            now=now_dt,
            lookback_hours=max(1, quality_config.duplicate_lookback_hours),
        )
        quality = check_quality(
            post=post_text,
            source_link=source_link,
            score=int(item.get("score") or 0),
            is_llm_mode=bool(item.get("is_llm_mode", False)),
            config=quality_config,
            history_posts=history,
            context="publish",
            context_text=f"{source_item.get('title', '')} {item.get('reason', '')}",
        )
        if not quality.passed:
            logger.warning("Quality reject: %s (%s)", rid, "; ".join(quality.reasons))
            quality_rejected_count += 1
            continue
        logger.info("Quality pass: %s", rid)
        if selected_platform == "bluesky" and not abs_card_path:
            logger.warning("Publish blocked (no image available): %s", rid)
            blocked_missing_image_count += 1
            continue

        result: PublishResult = publisher.publish(
            post=post_text,
            source_link=source_link,
            image_path=abs_card_path,
            image_alt=_build_image_alt_text(item),
        )
        if not result.success:
            logger.warning("Publish failed for %s: %s", rid, result.error or "unknown error")
            notify.jim_failed(
                platform=selected_platform,
                title=source_item.get("title", rid),
                error=result.error or "unknown error",
            )
            continue

        post = {
            "id": rid,
            "published_at": now,
            "platform": result.platform,
            "post": post_text,
            "source_link": source_link,
            "source_title": source_item.get("title", "Untitled"),
            "score": item.get("score"),
            "reason": item.get("reason", ""),
            "card_path": card_path,
            "external_id": result.external_id,
            "url": result.url,
        }

        published.append(post)
        existing_ids.add(rid)
        existing_links.add(source_link)
        item["status"] = "published_dry_run"
        item["published_at"] = now
        published_count += 1
        if abs_card_path:
            posted_with_image_count += 1
        logger.info("Published %s item: %s", selected_platform, rid)
        notify.jim_published(
            platform=selected_platform,
            title=source_item.get("title", rid),
            post_text=post_text,
            url=result.url,
            with_image=bool(abs_card_path),
            chloe_note=item.get("chloe_note", ""),
        )

    JsonStore.save(REVIEW_QUEUE_PATH, queue)
    JsonStore.save(PUBLISHED_POSTS_PATH, published)
    generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
    logger.info("Published count: %d", published_count)
    logger.info("Publish blocked (missing image): %d", blocked_missing_image_count)
    logger.info("Posted with image: %d", posted_with_image_count)
    logger.info("Quality rejected before publish: %d", quality_rejected_count)
    return 0


def _list_published(logger) -> int:
    published = JsonStore.load(PUBLISHED_POSTS_PATH, default=[])
    if not published:
        logger.info("No published dry-run posts yet")
        return 0

    logger.info("Published dry-run posts: %d", len(published))
    for item in published:
        logger.info("Published at: %s | Platform: %s", item.get("published_at"), item.get("platform"))
        logger.info("Source title: %s", item.get("source_title"))
        logger.info("Post: %s", item.get("post"))
    return 0


def _self_check_writer(logger) -> int:
    fixtures = _load_fixture_items()
    quality_config = _load_quality_config()
    history: list[str] = []
    passed = 0
    rejected = 0

    logger.info("Writer self-check using fixtures: %d items", len(fixtures))
    for item in fixtures:
        evaluation = evaluate_item(item, personas=[])
        post_text = generate_post(item, evaluation)
        quality = check_quality(
            post=post_text,
            source_link=item.link,
            score=evaluation.score,
            is_llm_mode=False,
            config=quality_config,
            history_posts=history,
            context="review",
            context_text=f"{item.title} {item.summary}",
        )

        status = "PASS" if quality.passed else "REJECT"
        logger.info("[%s] %s", status, item.title)
        logger.info("Post: %s", post_text)
        if quality.reasons:
            logger.info("Reasons: %s", "; ".join(quality.reasons))

        if quality.passed:
            passed += 1
            history.append(post_text)
        else:
            rejected += 1

    logger.info("Writer self-check summary: passed=%d rejected=%d", passed, rejected)
    return 0


def _reset_fixture_state(logger) -> int:
    fixtures = _load_fixture_items()
    fixture_links = {item.link for item in fixtures}

    seen = JsonStore.load(SEEN_ITEMS_PATH, default=[])
    drafts = JsonStore.load(DRAFTS_PATH, default=[])
    review = JsonStore.load(REVIEW_QUEUE_PATH, default=[])

    seen_before = len(seen)
    drafts_before = len(drafts)
    review_before = len(review)

    seen_after = [link for link in seen if link not in fixture_links]
    drafts_after = [d for d in drafts if d.get("link") not in fixture_links]
    review_after = [r for r in review if r.get("source_item", {}).get("link") not in fixture_links]

    JsonStore.save(SEEN_ITEMS_PATH, seen_after)
    JsonStore.save(DRAFTS_PATH, drafts_after)
    JsonStore.save(REVIEW_QUEUE_PATH, review_after)
    generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)

    logger.info("Fixture state reset complete")
    logger.info("Removed from seen_items: %d", seen_before - len(seen_after))
    logger.info("Removed from drafts: %d", drafts_before - len(drafts_after))
    logger.info("Removed from review_queue: %d", review_before - len(review_after))
    logger.info("published_posts.json unchanged")
    return 0


def run(argv: list[str] | None = None) -> int:
    logger = get_logger()
    args = _build_parser().parse_args(argv)

    if args.list_review_queue:
        return _list_review_queue(logger)
    if args.generate_card:
        return _generate_card_for_id(args.generate_card, logger)
    if args.generate_cards:
        return _generate_cards(logger)
    if args.regenerate_cards:
        return _regenerate_cards(logger)
    if args.create_test_review_item:
        if not args.use_fixtures:
            logger.error("--create-test-review-item requires --use-fixtures")
            return 1
        return _create_test_review_item(logger)
    if args.list_deferred:
        return _list_deferred(logger)
    if args.generate_review_report:
        return _generate_review_report(logger)
    if args.self_check_writer:
        return _self_check_writer(logger)
    if args.reset_fixture_state:
        if not args.use_fixtures:
            logger.error("--reset-fixture-state is only allowed with --use-fixtures")
            return 1
        return _reset_fixture_state(logger)
    if args.approve_review:
        return _update_review_status(args.approve_review, "approved", logger)
    if args.reject_review:
        return _update_review_status(args.reject_review, "rejected", logger)
    if args.publish_approved:
        return _publish_approved(args, logger)
    if args.list_published:
        return _list_published(logger)

    sources = _load_sources()
    personas = load_personas(JsonStore.load(PERSONAS_PATH, default=[]))
    seen_links = set(JsonStore.load(SEEN_ITEMS_PATH, default=[]))
    drafts_data = JsonStore.load(DRAFTS_PATH, default=[])
    existing_drafts_data = list(drafts_data)
    review_queue_data = JsonStore.load(REVIEW_QUEUE_PATH, default=[])
    published_data = JsonStore.load(PUBLISHED_POSTS_PATH, default=[])
    quality_config = _load_quality_config()
    llm_config = load_llm_config()
    max_posts_per_day_env = os.getenv("BOARDWIRE_MAX_POSTS_PER_DAY", "3")
    try:
        max_posts_per_day = int(max_posts_per_day_env)
    except ValueError:
        max_posts_per_day = 3
    max_posts_per_day = max(1, max_posts_per_day)

    if args.max_llm_items is not None and args.max_llm_items > 0:
        llm_config = LLMConfig(
            provider=llm_config.provider,
            openai_model=llm_config.openai_model,
            gemini_model=llm_config.gemini_model,
            openai_api_key=llm_config.openai_api_key,
            gemini_api_key=llm_config.gemini_api_key,
            max_items=args.max_llm_items,
        )
    if args.llm_provider is not None:
        llm_config.provider = args.llm_provider
    if args.max_posts_per_day is not None and args.max_posts_per_day > 0:
        max_posts_per_day = args.max_posts_per_day
    ignore_daily_cap = False
    if args.ignore_daily_cap:
        if os.getenv("GITHUB_EVENT_NAME", "").strip().lower() == "schedule":
            logger.error("--ignore-daily-cap is not allowed in scheduled GitHub workflows")
            return 1
        ignore_daily_cap = True
        logger.info("Daily cap ignored for this run")

    if args.use_fixtures:
        all_items = _load_fixture_items()
        source_report = {}
        logger.info("Using fixtures: %s", SAMPLE_ITEMS_PATH)
        logger.info("Loaded fixture items: %d", len(all_items))
    else:
        all_items, source_report = fetch_all(sources, logger=logger)

    if args.debug_sources and not args.use_fixtures:
        logger.info("Source debug summary")
        for source_name, details in source_report.items():
            count = details["count"]
            error = details["error"]
            newest_titles = details["newest_titles"]
            if error:
                logger.warning("Failed source %s: %s", source_name, error)
            logger.info("%s -> %d items", source_name, count)
            for title in newest_titles:
                logger.info("  - %s", title)
        logger.info("Total unique fetched items: %d", len(all_items))
        return 0

    # Load deferred items first and expire over-retried entries.
    max_defer_count = max(1, quality_config.max_defer_count)
    deferred_candidates: list[dict] = []
    deferred_expired = 0
    for item in review_queue_data:
        if item.get("status") != "deferred_due_to_cap":
            continue
        defer_count = int(item.get("defer_count") or 1)
        if defer_count > max_defer_count:
            item["status"] = "expired_deferred"
            logger.warning("Deferred item expired after max retries: %s", item.get("id"))
            deferred_expired += 1
            continue

        src = item.get("source_item", {})
        link = str(src.get("link", "")).strip()
        if not link:
            continue
        deferred_candidates.append(
            {
                "id": item.get("id"),
                "queue_item": item,
                "feed_item": FeedItem(
                    source=str(src.get("source", "Unknown Source")),
                    title=str(src.get("title", "Untitled")),
                    link=link,
                    summary=str(item.get("reason", "")),
                    published_at=_parse_dt(item.get("created_at")),
                ),
                "score": int(item.get("score") or 0),
                "is_deferred": True,
            }
        )
    deferred_candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Loaded deferred items: %d", len(deferred_candidates))
    if deferred_expired:
        logger.info("Deferred items expired this run: %d", deferred_expired)

    deferred_links = {d["feed_item"].link for d in deferred_candidates}
    unseen_items = [item for item in all_items if item.link not in seen_links and item.link not in deferred_links]
    fresh_candidates = sorted(unseen_items, key=lambda x: x.published_at, reverse=True)

    candidate_pipeline: list[dict] = []
    for d in deferred_candidates:
        candidate_pipeline.append({"feed_item": d["feed_item"], "is_deferred": True, "queue_item": d["queue_item"]})
    for f in fresh_candidates:
        candidate_pipeline.append({"feed_item": f, "is_deferred": False, "queue_item": None})
    candidate_pipeline = candidate_pipeline[: args.limit]

    llm_requested = args.llm or llm_config.provider == "openai"
    llm_requested = llm_requested or llm_config.provider == "gemini"
    llm_forced_off = args.no_llm
    llm_enabled = llm_requested and not llm_forced_off
    logger.info("LLM mode: %s", "enabled" if llm_enabled else "disabled")
    logger.info("LLM provider: %s", llm_config.provider if llm_enabled else "none")
    if llm_enabled and llm_config.provider == "openai":
        logger.info("Using model: %s", llm_config.openai_model)
    elif llm_enabled and llm_config.provider == "gemini":
        logger.info("Using Gemini model: %s", llm_config.gemini_model)
    else:
        logger.info("Using model: n/a")
    if llm_enabled and llm_config.provider not in {"openai", "gemini"}:
        logger.warning("Falling back to rule-based evaluator: unsupported provider '%s'", llm_config.provider)
    if llm_enabled and llm_config.provider == "openai" and not llm_config.openai_api_key:
        logger.warning("Falling back to rule-based evaluator: OPENAI_API_KEY is missing")
    if llm_enabled and llm_config.provider == "gemini" and not llm_config.gemini_api_key:
        logger.warning("Falling back to rule-based evaluator: GEMINI_API_KEY is missing")

    created_drafts: list[DraftPost] = []
    processed_links: list[str] = []
    deferred_due_to_cap_links: set[str] = set()
    deferred_reprocessed = 0
    deferred_became_review = 0
    llm_evaluated = 0
    gemini_evaluated = 0
    llm_mode_by_link: dict[str, bool] = {}
    _claire_notes: dict[str, str] = {}          # link → Claire's LLM text (for Chloe context)
    _chloe_notes: dict[str, str] = {}           # link → Chloe's LLM text (for Madison context)
    _pending_claire: dict[str, tuple] = {}      # link → (title, link) — deferred until Chloe fires

    notify.run_started(
        sources_count=len(sources),
        items_count=len(candidate_pipeline),
        llm_mode=llm_enabled,
    )

    for idx, candidate in enumerate(candidate_pipeline):
        item = candidate["feed_item"]
        is_deferred = bool(candidate["is_deferred"])
        deferred_queue_item = candidate["queue_item"]
        if is_deferred:
            logger.info("Reprocessing deferred item: %s", item.title)
            deferred_reprocessed += 1
        use_llm_for_item = llm_enabled and idx < llm_config.max_items
        if use_llm_for_item:
            decision = evaluate_with_optional_llm(
                item=item,
                personas=personas,
                llm_config=llm_config,
                force_llm=args.llm,
                logger=logger,
            )
            if decision.used_llm:
                llm_evaluated += 1
                if llm_config.provider == "gemini":
                    gemini_evaluated += 1
            evaluation = decision.evaluation
            post_text = decision.post_text
            source_angle = decision.source_angle
            llm_mode_by_link[item.link] = decision.used_llm
        else:
            evaluation = evaluate_item(item, personas)
            post_text = generate_post(item, evaluation)
            source_angle = "Rule-based"
            llm_mode_by_link[item.link] = False

        draft = DraftPost(
            title=item.title,
            link=item.link,
            source=item.source,
            score=evaluation.score,
            should_post=evaluation.should_post,
            reason=evaluation.reason,
            post_text=post_text,
            source_angle=source_angle,
        )
        drafts_data.append(asdict(draft))
        created_drafts.append(draft)
        if evaluation.should_post:
            # Generate Claire's text now (needed as context for Chloe) but defer posting
            # so Claire+Chloe messages appear interleaved per article in Slack.
            from src.notifications import persona_voice as _pv
            claire_text = _pv.claire_on_found(item.title, item.source, evaluation.score, item.summary[:300])
            fallback_reason = (evaluation.reason or "").strip()
            if fallback_reason.lower().startswith("builder signal:"):
                fallback_reason = (
                    "Das Thema trifft klar Builder-Interesse "
                    f"({fallback_reason.split(':', 1)[1].strip()})."
                )
            claire_text = claire_text or (
                f"Aus *{item.source}* ist ein starker Kandidat reingekommen: *{item.title}*.\n"
                f"Relevanz fuer Builder: {fallback_reason or 'klarer praktischer Nutzen fuer aktuelle AI-Workflows.'}\n"
                f"_Score: {evaluation.score}_"
            )
            _claire_notes[item.link] = claire_text
            _pending_claire[item.link] = (item.title, item.link)
        processed_links.append(item.link)
        if deferred_queue_item is not None:
            # keep reference for post-quality status transitions
            deferred_queue_item["_reprocessed"] = True
            deferred_queue_item["_draft_created_at"] = draft.created_at

    JsonStore.save(DRAFTS_PATH, drafts_data)

    evaluator_approved = sum(1 for d in created_drafts if d.should_post)
    evaluator_rejected = len(created_drafts) - evaluator_approved
    quality_pass = 0
    quality_reject = 0
    saved_to_review_queue = 0

    if args.review:
        queue_items = _queue_from_drafts(created_drafts)
        deferred_queue_by_link: dict[str, dict] = {}
        for q in review_queue_data:
            if q.get("status") == "deferred_due_to_cap":
                link = str(q.get("source_item", {}).get("link", "")).strip()
                if link:
                    deferred_queue_by_link[link] = q
        now_dt = datetime.now(timezone.utc)
        lookback_hours = (
            quality_config.fixture_duplicate_lookback_hours if args.use_fixtures else quality_config.duplicate_lookback_hours
        )
        lookback_hours = max(1, lookback_hours)
        passed_queue_items: list[dict] = []
        today = datetime.now(timezone.utc).date()
        existing_today = 0
        for q in review_queue_data:
            status = q.get("status")
            if status not in {"pending_review", "approved", "published_dry_run"}:
                continue
            dt = _parse_dt(q.get("created_at"))
            if dt.date() == today:
                existing_today += 1
        remaining_today = max(0, max_posts_per_day - existing_today)

        deferred_rejected = 0
        for item in queue_items:
            source_title = item.get("source_item", {}).get("title", "Untitled")
            source_link = str(item.get("source_item", {}).get("link", "")).strip()
            proposed_post = item.get("proposed_post", "")
            score_val = int(item.get("score") or 0)
            is_llm_mode = llm_mode_by_link.get(source_link, False)
            item["is_llm_mode"] = is_llm_mode
            linked_deferred = deferred_queue_by_link.get(source_link)
            is_reprocessed_deferred = bool(linked_deferred and linked_deferred.get("_reprocessed"))
            if is_reprocessed_deferred and args.quality_report:
                logger.info("Ignoring self duplicate for deferred item: %s", linked_deferred.get("id"))
            history = _history_for_review_item(
                existing_drafts_data,
                review_queue_data,
                published_data,
                now=now_dt,
                lookback_hours=lookback_hours,
                fixture_mode=args.use_fixtures,
                candidate_id=(linked_deferred.get("id") if is_reprocessed_deferred else None),
                candidate_link=(source_link if is_reprocessed_deferred else None),
                is_reprocessing_deferred=is_reprocessed_deferred,
            )
            quality = check_quality(
                post=proposed_post,
                source_link=source_link,
                score=score_val,
                is_llm_mode=is_llm_mode,
                config=quality_config,
                history_posts=history,
                context="review",
                context_text=f"{source_title} {item.get('reason', '')}",
            )
            if quality.passed:
                if (not ignore_daily_cap) and remaining_today <= 0:
                    quality_reject += 1
                    logger.warning("Quality reject: daily post cap reached (%d)", max_posts_per_day)
                    if is_reprocessed_deferred:
                        linked_deferred["defer_count"] = int(linked_deferred.get("defer_count") or 1) + 1
                        linked_deferred["deferred_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        if int(linked_deferred["defer_count"]) > max_defer_count:
                            linked_deferred["status"] = "expired_deferred"
                            logger.warning("Deferred item expired after max retries: %s", linked_deferred.get("id"))
                        else:
                            linked_deferred["status"] = "deferred_due_to_cap"
                        deferred_due_to_cap_links.add(source_link)
                    else:
                        item["status"] = "deferred_due_to_cap"
                        item["deferred_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        item["defer_count"] = 1
                        item["original_score"] = score_val
                        item["original_reason"] = item.get("reason", "")
                        review_queue_data.append(item)
                        deferred_due_to_cap_links.add(source_link)
                    if args.quality_report:
                        logger.info("Quality report [REJECT] ID=%s | title=%s | score=%d", item.get("id"), source_title, score_val)
                        logger.info("Proposed post: %s", proposed_post)
                        logger.info("Reason: daily post cap reached (%d). Existing today=%d", max_posts_per_day, existing_today)
                    continue
                if is_reprocessed_deferred:
                    linked_deferred["status"] = "approved"
                    linked_deferred["score"] = score_val
                    linked_deferred["reason"] = item.get("reason", "")
                    linked_deferred["proposed_post"] = proposed_post
                    linked_deferred["source_angle"] = item.get("source_angle", linked_deferred.get("source_angle", ""))
                    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    linked_deferred["created_at"] = now_iso
                    linked_deferred["reactivated_at"] = now_iso
                    linked_deferred["is_llm_mode"] = is_llm_mode
                    linked_deferred.pop("deferred_at", None)
                    linked_deferred.pop("defer_count", None)
                    linked_deferred.pop("original_score", None)
                    linked_deferred.pop("original_reason", None)
                    quality_pass += 1
                    remaining_today -= 1
                    logger.info("Quality pass: %s", linked_deferred.get("id"))
                    deferred_became_review += 1
                else:
                    item["status"] = "approved"
                    passed_queue_items.append(item)
                    history.append(proposed_post)
                    quality_pass += 1
                    remaining_today -= 1
                    logger.info("Quality pass: %s", item.get("id"))
                    # Send Claire's deferred notification first — then Chloe's immediately after
                    if source_link in _pending_claire:
                        c_title, c_link = _pending_claire.pop(source_link)
                        notify.claire_post_deferred(c_title, c_link, _claire_notes.get(source_link, ""))
                    chloe_note = notify.michael_approved(
                        title=source_title,
                        link=source_link,
                        score=score_val,
                        reason=item.get("reason", ""),
                        is_llm=is_llm_mode,
                        claire_note=_claire_notes.get(source_link, ""),
                    )
                    _chloe_notes[source_link] = chloe_note
                    item["claire_note"] = _claire_notes.get(source_link, "")
                    item["chloe_note"] = chloe_note
            else:
                quality_reject += 1
                logger.warning("Quality reject: %s", "; ".join(quality.reasons))
                _pending_claire.pop(source_link, None)
                notify.michael_rejected(
                    title=source_title,
                    link=source_link,
                    reasons=quality.reasons,
                    claire_note=_claire_notes.get(source_link, ""),
                )
                if is_reprocessed_deferred:
                    linked_deferred["status"] = "rejected"
                    linked_deferred["rejected_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    deferred_rejected += 1

            if args.quality_report:
                status = "PASS" if quality.passed else "REJECT"
                logger.info("Quality report [%s] ID=%s | title=%s | score=%d", status, item.get("id"), source_title, score_val)
                logger.info("Proposed post: %s", proposed_post)
                logger.info("Reason: %s", "; ".join(quality.reasons) if quality.reasons else "passed")

        review_queue_data.extend(passed_queue_items)
        for q in review_queue_data:
            q.pop("_reprocessed", None)
            q.pop("_draft_created_at", None)
        JsonStore.save(REVIEW_QUEUE_PATH, review_queue_data)
        generate_review_queue_report(REVIEW_QUEUE_PATH, REVIEW_REPORT_PATH)
        saved_to_review_queue = len(passed_queue_items)
        logger.info("Saved %d drafts to review queue", saved_to_review_queue)
        logger.info("Quality gate summary: passed=%d rejected=%d", quality_pass, quality_reject)
        logger.info("Deferred due to daily cap: %d", len([x for x in review_queue_data if x.get("status") == "deferred_due_to_cap"]))

    # Do not mark cap-deferred candidates as seen so they can be reconsidered later.
    effective_processed_links = [link for link in processed_links if link not in deferred_due_to_cap_links]
    updated_seen = list(seen_links.union(effective_processed_links))
    JsonStore.save(SEEN_ITEMS_PATH, updated_seen)

    notify.run_finished(queued=saved_to_review_queue, rejected=quality_reject)
    logger.info("Boardwire AI dry run complete")
    logger.info("Sources loaded: %d", len(sources) if not args.use_fixtures else 0)
    logger.info("Fetched items: %d", len(all_items))
    logger.info("Unseen items: %d", len(unseen_items))
    logger.info("Processed items: %d", len(created_drafts))
    logger.info("Candidate limit: %d", args.limit)
    logger.info("LLM evaluated %d items", llm_evaluated)
    if llm_config.provider == "gemini":
        logger.info("Gemini evaluated %d items", gemini_evaluated)
    logger.info("Evaluator approved: %d", evaluator_approved)
    logger.info("Evaluator rejected: %d", evaluator_rejected)
    logger.info("Quality passed: %d", quality_pass)
    logger.info("Quality rejected: %d", quality_reject)
    logger.info("Saved to review queue: %d", saved_to_review_queue)
    logger.info("Deferred reprocessed: %d", deferred_reprocessed)
    logger.info("Deferred promoted to review: %d", deferred_became_review)
    logger.info("Deferred expired: %d", deferred_expired)
    if args.review:
        logger.info("Deferred rejected: %d", deferred_rejected)

    if created_drafts:
        logger.info("Drafts written to: %s", DRAFTS_PATH)
        logger.info("Seen links updated in: %s", SEEN_ITEMS_PATH)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
