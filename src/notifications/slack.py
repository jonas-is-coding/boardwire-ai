from __future__ import annotations

import os
import re
import hashlib
from typing import Literal

import requests

from src.notifications import persona_voice as voice

_WEBHOOKS: dict[str, str | None] = {}

_PERSONA_ENV = {
    "claire": "SLACK_WEBHOOK_URL_CLAIRE",
    "chloe": "SLACK_WEBHOOK_URL_CHLOE",
    "madison": "SLACK_WEBHOOK_URL_MADISON",
    "sarah": "SLACK_WEBHOOK_URL_SARAH",
}


def _clean_message(text: str, recipient_name: str | None = None) -> str:
    """Normalize LLM/fallback output to avoid robotic salutations and legacy footers."""
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        lower_line = line.lower()
        if "automated with this n8n workflow" in lower_line:
            continue
        if recipient_name and lower_line == f"{recipient_name.lower()},":
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned


def _variant_seed(*parts: str) -> int:
    key = "|".join(parts).encode("utf-8")
    return int(hashlib.sha1(key).hexdigest(), 16)


def _normalize_reason(reason: str) -> str:
    cleaned = reason.strip()
    if cleaned.lower().startswith("builder signal:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    cleaned = cleaned.rstrip(".")
    return cleaned


def _webhook(persona: str) -> str | None:
    if persona not in _WEBHOOKS:
        env_key = _PERSONA_ENV.get(persona, "")
        url = os.getenv(env_key, "").strip() if env_key else ""
        if not url:
            url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
        _WEBHOOKS[persona] = url or None
    return _WEBHOOKS[persona]


def _post(persona: str, text: str) -> None:
    url = _webhook(persona)
    if not url:
        return
    try:
        requests.post(url, json={"text": text}, timeout=5)
    except Exception:
        pass


def _post_debug(text: str) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL_DEBUG", "").strip()
    if not url:
        return
    try:
        requests.post(url, json={"text": text}, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public notification events
# ---------------------------------------------------------------------------

def claire_post_deferred(title: str, link: str, text: str) -> None:
    _post("claire", text)


def michael_approved(title: str, link: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str:
    return chloe_approved(title, link, score, reason, is_llm, claire_note)


def chloe_approved(title: str, link: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str:
    llm_text = voice.madison_on_approved(title, link, score, reason, is_llm, claire_note)
    if llm_text:
        text = llm_text
    else:
        seed = _variant_seed("madison", title, reason)
        r = _normalize_reason(reason)
        variants = [
            f"Hey, *{title}* habe ich gerade fuer den Publish-Queue freigegeben. Das passt fuer Builder besonders wegen {r}. Score aktuell: {score}. Link: {link}",
            f"Kurzes Update: *{title}* ist von mir fuer den Publish-Queue freigegeben. Hauptgrund ist der klare Builder-Nutzen rund um {r}. Ich habe es mit {score} Punkten bewertet. Hier der Link: {link}",
            f"*{title}* ist approved fuer den Publish-Queue. Fuer Builder ist das stark, vor allem durch {r}. Bewertung: {score}. Quelle: {link}",
        ]
        text = variants[seed % len(variants)]
    text = _clean_message(text, recipient_name="Claire")
    # Review-phase guardrail: avoid implying real publish happened already.
    text = re.sub(r"\b(das\s+geht\s+live)\b", "freigegeben fuer den Publish-Queue", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(ist\s+live)\b", "ist fuer den Publish-Queue freigegeben", text, flags=re.IGNORECASE)
    _post("madison", text)
    return text


def michael_rejected(title: str, link: str, reasons: list[str], claire_note: str = "") -> None:
    chloe_rejected(title, link, reasons, claire_note)


def chloe_rejected(title: str, link: str, reasons: list[str], claire_note: str = "") -> None:
    _post_debug(f'Abgelehnt: "{title}" — {"; ".join(reasons)}')


def michael_human_approved(review_id: str, title: str) -> None:
    chloe_human_approved(review_id, title)


def chloe_human_approved(review_id: str, title: str) -> None:
    _post_debug(f'Manuell freigegeben: "{title}"')


def michael_human_rejected(review_id: str, title: str) -> None:
    chloe_human_rejected(review_id, title)


def chloe_human_rejected(review_id: str, title: str) -> None:
    _post_debug(f'Manuell abgelehnt: "{title}"')


def jim_published(platform: str, title: str, post_text: str, url: str | None, with_image: bool, chloe_note: str = "") -> None:
    madison_published(platform, title, post_text, url, with_image, chloe_note)


def madison_published(platform: str, title: str, post_text: str, url: str | None, with_image: bool, chloe_note: str = "") -> None:
    llm_text = voice.chloe_on_published(title, platform, post_text, chloe_note)
    body = llm_text or (
        f"Aaand ... we're live!\n"
        f"{platform}: {url or 'Link kommt gleich'}"
    )
    body = _clean_message(body)
    _post("chloe", f"{body}\n\n{post_text}")


def jim_failed(platform: str, title: str, error: str) -> None:
    madison_failed(platform, title, error)


def madison_failed(platform: str, title: str, error: str) -> None:
    _post_debug(f'Fehler beim Veröffentlichen auf {platform}: "{title}"\n{error}')


def run_started(sources_count: int, items_count: int, llm_mode: bool) -> None:
    mode = ", LLM aktiv" if llm_mode else ""
    _post_debug(f"Neue Runde gestartet — {sources_count} Quellen, {items_count} neue Artikel{mode}.")


def run_finished(queued: int, rejected: int) -> None:
    _post_debug(f"Runde abgeschlossen — {queued} in der Queue, {rejected} abgelehnt.")


def sarah_packaged(title: str, subtitle: str, description: str, hashtags: list[str]) -> None:
    tag_line = " ".join(t.strip() for t in hashtags if str(t).strip())
    text = (
        "Sarah package erstellt:\n"
        f"Title: {title}\n"
        f"Subtitle: {subtitle}\n"
        f"Description: {description}\n"
        f"Hashtags: {tag_line}"
    )
    _post("sarah", text)


def reply_digest(text: str) -> None:
    """Deliver the human-in-the-loop reply digest. Suggestions only — the
    pipeline never posts replies to Bluesky; a human posts manually."""
    _post("sarah", text)
    _post_debug(text)


def sarah_failed_batch(failures: list[dict]) -> None:
    """Send a single consolidated notification for items where Sarah LLM
    failed to produce a valid publish package. Items stay in the queue
    for a retry on the next run."""
    if not failures:
        return
    lines = [f":rotating_light: Sarah LLM hat {len(failures)} Post(s) nicht gepackt — nicht veröffentlicht, Retry beim nächsten Run."]
    for f in failures[:15]:
        title = str(f.get("title", "Untitled")).strip()
        source = str(f.get("source", "Unknown")).strip()
        link = str(f.get("link", "")).strip()
        rid = str(f.get("rid", "")).strip()
        line = f"• *{title}* ({source})"
        if link:
            line += f" — {link}"
        if rid:
            line += f" — id `{rid}`"
        lines.append(line)
    if len(failures) > 15:
        lines.append(f"… und {len(failures) - 15} weitere.")
    text = "\n".join(lines)
    _post("sarah", text)
    _post_debug(text)
