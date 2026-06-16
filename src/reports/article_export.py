from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from src.config import DOSSIERS_DIR
from src.storage.json_store import JsonStore
from src.notifications import persona_voice as voice


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def _safe_iso_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return datetime.now(timezone.utc).date().isoformat()


_PLACEHOLDER_TEXT = {
    "local newsworthiness fallback",
    "n/a",
    "unknown",
}


def _clean_text(value: str | None) -> str:
    """Strip machine annotations so degraded-mode prose stays readable."""
    if not value:
        return ""
    text = str(value)
    # Drop internal cluster annotations like "[Cluster context: ...]".
    text = re.sub(r"\[Cluster context:[^\]]*\]", "", text)
    # Drop redundant "original: <url>" tails (the link lives in Sources).
    text = re.sub(r"[—-]?\s*original:\s*\S+", "", text, flags=re.IGNORECASE)
    # Collapse leftover whitespace.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text).strip()
    if text.lower() in _PLACEHOLDER_TEXT:
        return ""
    return text


# -- research dossiers -----------------------------------------------------


def load_dossier_index(dossiers_dir: Path = DOSSIERS_DIR) -> dict[str, dict]:
    """Index persisted research dossiers by every source URL they cover.

    The newsroom reporter writes one dossier per researched story to
    ``data/dossiers/<lead_id>.json``. A review item is matched to its dossier
    by shared source link, so an article can be written from deep, verified
    research instead of a thin RSS summary.
    """
    index: dict[str, dict] = {}
    try:
        paths = sorted(Path(dossiers_dir).glob("*.json"))
    except (OSError, ValueError):
        return index
    for path in paths:
        dossier = JsonStore.load(path, default=None)
        if not isinstance(dossier, dict):
            continue
        urls = dossier.get("source_urls") or []
        if not isinstance(urls, list):
            continue
        for url in urls:
            key = str(url).strip()
            if key and key not in index:
                index[key] = dossier
    return index


def _dossier_for_item(item: dict, dossier_index: dict[str, dict]) -> dict | None:
    if not dossier_index:
        return None
    link = str(item.get("source_item", {}).get("link", "")).strip()
    if link and link in dossier_index:
        return dossier_index[link]
    return None


# -- front matter ----------------------------------------------------------


def _reading_time_minutes(body: str) -> int:
    words = len(re.findall(r"\w+", body or ""))
    return max(1, round(words / 220))


def _meta_description(item: dict, dossier: dict | None) -> str:
    """A short, plain-prose description for SEO and social previews."""
    candidates = []
    if dossier:
        candidates.append(_clean_text(dossier.get("summary")))
    source_item = item.get("source_item", {})
    candidates.append(_clean_text(item.get("reason")))
    candidates.append(_clean_text(source_item.get("summary")))
    for text in candidates:
        if text:
            one_line = " ".join(text.split())
            if len(one_line) > 200:
                one_line = one_line[:197].rstrip() + "..."
            return one_line
    return ""


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _front_matter(item: dict, body: str, dossier: dict | None = None) -> str:
    """Publishable front matter for the static news site.

    Backward compatible: keeps the original title/date/source/source_url keys
    and only *adds* fields the web frontend can progressively adopt
    (description, beat, reading time, a hero-image slot, a verified flag and a
    structured source list).
    """
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "Untitled")).strip() or "Untitled"
    source = str(source_item.get("source", "Unknown Source")).strip() or "Unknown Source"
    link = str(source_item.get("link", "")).strip()
    date = _safe_iso_date(item.get("created_at"))
    description = _meta_description(item, dossier)
    beat = str((dossier or {}).get("beat", "")).strip() or "news"

    lines = [
        "---",
        f'title: "{_yaml_escape(title)}"',
        f"date: {date}",
        f"source: {source}",
        f"source_url: {link or 'n/a'}",
        f'description: "{_yaml_escape(description)}"',
        f"beat: {beat}",
        f"reading_time: {_reading_time_minutes(body)}",
        'hero_image: ""',
    ]

    if dossier:
        claims = dossier.get("claims") or []
        verified = any(
            isinstance(c, dict) and str(c.get("support", "")).strip().lower() == "verified"
            for c in claims
        )
        lines.append(f"verified: {'true' if verified else 'false'}")
        source_urls = [str(u).strip() for u in (dossier.get("source_urls") or []) if str(u).strip()]
        if source_urls:
            lines.append("sources:")
            for url in source_urls[:10]:
                lines.append(f'  - "{_yaml_escape(url)}"')

    lines.extend(["---", "", ""])
    return "\n".join(lines)


# -- fallback article body (no LLM) ----------------------------------------


def _fallback_article_body(item: dict, dossier: dict | None = None) -> str:
    """Best-effort readable article when no LLM draft is available.

    This is a real news piece for a reader, not internal review documentation.
    It only restates facts we actually have. When a research dossier exists it
    is woven into prose (summary, background, key facts, attributed claims and
    the full source list); otherwise we fall back to the cleaned summary.
    """
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "Untitled")).strip() or "Untitled"
    source = str(source_item.get("source", "Unknown Source")).strip() or "Unknown Source"
    link = str(source_item.get("link", "")).strip()
    summary = _clean_text(source_item.get("summary"))
    reason = _clean_text(item.get("reason"))

    paragraphs: list[str] = [f"# {title}", ""]

    if dossier:
        lede = _clean_text(dossier.get("summary")) or reason or summary
        if lede:
            paragraphs.extend([lede, ""])

        background = _clean_text(dossier.get("background"))
        if background and background.lower() not in lede.lower():
            paragraphs.extend([background, ""])

        key_facts = [str(f).strip() for f in (dossier.get("key_facts") or []) if str(f).strip()]
        if key_facts:
            paragraphs.append("Here is what the reporting establishes:")
            paragraphs.append("")
            paragraphs.extend(f"- {fact}" for fact in key_facts[:6])
            paragraphs.append("")

        claims = dossier.get("claims") or []
        attributed = []
        for raw in claims[:6]:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            support = str(raw.get("support", "unverified")).strip().lower()
            if support == "verified":
                attributed.append(f"- {text} (corroborated across multiple sources)")
            elif support == "single_source":
                attributed.append(f"- {text} (reported by a single source so far)")
            else:
                attributed.append(f"- {text} (unconfirmed)")
        if attributed:
            paragraphs.append("The key claims, with how well they are supported:")
            paragraphs.append("")
            paragraphs.extend(attributed)
            paragraphs.append("")

        open_questions = [str(q).strip() for q in (dossier.get("open_questions") or []) if str(q).strip()]
        if open_questions:
            joined = "; ".join(open_questions[:3])
            tail = "" if joined.endswith((".", "?", "!")) else "."
            paragraphs.append(
                "Some things remain genuinely open, and it is worth being honest about them: "
                + joined
                + tail
            )
            paragraphs.append("")

        source_urls = [str(u).strip() for u in (dossier.get("source_urls") or []) if str(u).strip()]
        if source_urls or link:
            paragraphs.extend(["## Sources", ""])
            seen: set[str] = set()
            for url in source_urls + ([link] if link else []):
                if url and url not in seen:
                    seen.add(url)
                    paragraphs.append(f"- [{source}]({url})")
            paragraphs.append("")
        return "\n".join(paragraphs)

    # No dossier: weave the cleaned source metadata into prose.
    lede = reason or summary
    if lede:
        paragraphs.extend([lede, ""])

    extra = summary if lede is reason else reason
    if extra and extra != lede and extra.lower() not in lede.lower():
        paragraphs.extend([extra, ""])

    paragraphs.extend(
        [
            f"This story surfaced via {source}. For the original details and any "
            "numbers we have not confirmed here, follow the source below.",
            "",
        ]
    )

    if link:
        paragraphs.extend(["## Sources", "", f"- [{source}]({link})", ""])

    return "\n".join(paragraphs)


def _build_article_markdown(item: dict, dossier: dict | None = None) -> str:
    body = _fallback_article_body(item, dossier)
    return _front_matter(item, body, dossier) + body


# -- export ----------------------------------------------------------------


def export_review_articles(
    review_queue_path: Path,
    output_dir: Path,
    dossiers_dir: Path = DOSSIERS_DIR,
) -> int:
    queue = JsonStore.load(review_queue_path, default=[])
    output_dir.mkdir(parents=True, exist_ok=True)
    dossier_index = load_dossier_index(dossiers_dir)

    exportable = [
        item
        for item in queue
        if item.get("status") in {"approved", "published_dry_run", "pending_review"}
    ]

    written = 0
    llm_calls = 0
    try:
        llm_budget = max(0, int(os.getenv("BOARDWIRE_TIFFANY_CALL_BUDGET", "3").strip()))
    except ValueError:
        llm_budget = 3

    for item in exportable:
        source_item = item.get("source_item", {})
        title = str(source_item.get("title", "Untitled"))
        date_prefix = _safe_iso_date(item.get("created_at"))
        filename = f"{date_prefix}-{_slugify(title)}-{item.get('id', 'item')}.md"
        target = output_dir / filename
        dossier = _dossier_for_item(item, dossier_index)
        ai_article = None
        if llm_calls < llm_budget:
            ai_article = voice.tiffany_write_article(
                title=str(source_item.get("title", "Untitled")),
                source=str(source_item.get("source", "Unknown Source")),
                link=str(source_item.get("link", "")),
                status=str(item.get("status", "unknown")),
                score=int(item.get("score") or 0),
                reason=str(item.get("reason", "")),
                proposed_post=str(item.get("proposed_post", "")),
                summary=str(source_item.get("summary", "")),
                created_at=str(item.get("created_at", "")),
                dossier=dossier,
            )
            llm_calls += 1
        if isinstance(ai_article, str) and ai_article.strip():
            body = ai_article.strip()
            full = _front_matter(item, body, dossier) + body
        else:
            full = _build_article_markdown(item, dossier)
        target.write_text(full + "\n", encoding="utf-8")
        written += 1
    return written


def write_article_for_item(item: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_item = item.get("source_item", {})
    title = str(source_item.get("title", "Untitled"))
    date_prefix = _safe_iso_date(item.get("created_at"))
    filename = f"{date_prefix}-{_slugify(title)}-{item.get('id', 'item')}.md"
    target = output_dir / filename
    body = _build_article_markdown(item)
    target.write_text(body + "\n", encoding="utf-8")
    return target
