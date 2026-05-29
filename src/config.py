from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
FIXTURES_DIR = PROJECT_ROOT / "fixtures"
REPORTS_DIR = PROJECT_ROOT / "reports"
GENERATED_DIR = PROJECT_ROOT / "generated"
CARDS_DIR = GENERATED_DIR / "cards"
ARTICLES_DIR = PROJECT_ROOT / "articles"

SOURCES_PATH = CONFIG_DIR / "sources.json"
PERSONAS_PATH = CONFIG_DIR / "personas.json"
QUALITY_PATH = CONFIG_DIR / "quality.json"
SEEN_ITEMS_PATH = DATA_DIR / "seen_items.json"
DRAFTS_PATH = DATA_DIR / "drafts.json"
REVIEW_QUEUE_PATH = DATA_DIR / "review_queue.json"
PUBLISHED_POSTS_PATH = DATA_DIR / "published_posts.json"
ENGAGEMENT_PATH = DATA_DIR / "engagement.json"
VIRALITY_MODEL_PATH = DATA_DIR / "virality_model.json"
EMBEDDINGS_CACHE_PATH = DATA_DIR / "embeddings.json"
CLUSTERS_DEBUG_PATH = DATA_DIR / "clusters.json"
SAMPLE_ITEMS_PATH = FIXTURES_DIR / "sample_items.json"
REVIEW_REPORT_PATH = REPORTS_DIR / "review_queue.md"
ENGAGEMENT_REPORT_PATH = REPORTS_DIR / "engagement_report.md"

MAX_ITEMS_PER_RUN = 3
POST_CHAR_LIMIT = 280
