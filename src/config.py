from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
FIXTURES_DIR = PROJECT_ROOT / "fixtures"
REPORTS_DIR = PROJECT_ROOT / "reports"

SOURCES_PATH = CONFIG_DIR / "sources.json"
PERSONAS_PATH = CONFIG_DIR / "personas.json"
QUALITY_PATH = CONFIG_DIR / "quality.json"
SEEN_ITEMS_PATH = DATA_DIR / "seen_items.json"
DRAFTS_PATH = DATA_DIR / "drafts.json"
REVIEW_QUEUE_PATH = DATA_DIR / "review_queue.json"
PUBLISHED_POSTS_PATH = DATA_DIR / "published_posts.json"
SAMPLE_ITEMS_PATH = FIXTURES_DIR / "sample_items.json"
REVIEW_REPORT_PATH = REPORTS_DIR / "review_queue.md"

MAX_ITEMS_PER_RUN = 3
POST_CHAR_LIMIT = 280
