from __future__ import annotations

import os
from typing import Literal

import requests

_WEBHOOK_URL: str | None = None


def _webhook() -> str | None:
    global _WEBHOOK_URL
    if _WEBHOOK_URL is None:
        _WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip() or None
    return _WEBHOOK_URL


def _post(payload: dict) -> None:
    url = _webhook()
    if not url:
        return
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass  # Notifications are best-effort — never block the pipeline


# ---------------------------------------------------------------------------
# Persona helpers
# ---------------------------------------------------------------------------

_PERSONAS: dict[str, dict] = {
    "pam": {"username": "Pam · Research", "icon_emoji": ":mag:"},
    "michael": {"username": "Michael · Editor", "icon_emoji": ":memo:"},
    "jim": {"username": "Jim · Publisher", "icon_emoji": ":mega:"},
}

_COLORS = {
    "green": "#2eb886",
    "yellow": "#f5a623",
    "red": "#d00000",
    "gray": "#aaaaaa",
}


def _send(
    persona: Literal["pam", "michael", "jim"],
    text: str,
    color: str = "gray",
    fields: list[dict] | None = None,
    title: str | None = None,
    title_link: str | None = None,
) -> None:
    p = _PERSONAS[persona]
    attachment: dict = {
        "color": _COLORS.get(color, color),
        "text": text,
        "footer": "Boardwire AI",
        "mrkdwn_in": ["text"],
    }
    if title:
        attachment["title"] = title
    if title_link:
        attachment["title_link"] = title_link
    if fields:
        attachment["fields"] = fields

    _post({**p, "attachments": [attachment]})


# ---------------------------------------------------------------------------
# Public notification events
# ---------------------------------------------------------------------------

def pam_found_candidate(title: str, source: str, link: str, score: int) -> None:
    """Pam reports a new article that passed initial evaluation."""
    _send(
        "pam",
        f"Neuer Kandidat aus *{source}* mit Score *{score}*",
        color="yellow",
        title=title,
        title_link=link,
    )


def michael_approved(title: str, link: str, score: int, reason: str, is_llm: bool) -> None:
    """Michael approves an item for the review queue."""
    mode = "LLM" if is_llm else "Regel"
    _send(
        "michael",
        f"✅ Freigegeben für Review-Queue ({mode}-Modus)",
        color="green",
        title=title,
        title_link=link,
        fields=[
            {"title": "Score", "value": str(score), "short": True},
            {"title": "Begründung", "value": reason, "short": False},
        ],
    )


def michael_rejected(title: str, link: str, reasons: list[str]) -> None:
    """Michael rejects an item at the quality gate."""
    _send(
        "michael",
        f"❌ Abgelehnt: {'; '.join(reasons)}",
        color="red",
        title=title,
        title_link=link,
    )


def michael_human_approved(review_id: str, title: str) -> None:
    """A human approved an item in the review queue."""
    _send(
        "michael",
        f"👍 Manuell genehmigt: *{title}* (`{review_id}`)",
        color="green",
    )


def michael_human_rejected(review_id: str, title: str) -> None:
    """A human rejected an item in the review queue."""
    _send(
        "michael",
        f"👎 Manuell abgelehnt: *{title}* (`{review_id}`)",
        color="red",
    )


def jim_published(
    platform: str,
    title: str,
    post_text: str,
    url: str | None,
    with_image: bool,
) -> None:
    """Jim reports a successful publication."""
    image_note = " 🖼️" if with_image else ""
    link_text = f"\n🔗 <{url}|Post ansehen>" if url else ""
    _send(
        "jim",
        f"✅ Veröffentlicht auf *{platform}*{image_note}{link_text}\n\n_{post_text}_",
        color="green",
        title=title,
    )


def jim_failed(platform: str, title: str, error: str) -> None:
    """Jim reports a publish failure."""
    _send(
        "jim",
        f"❌ Veröffentlichung fehlgeschlagen auf *{platform}*\n`{error}`",
        color="red",
        title=title,
    )


def run_started(sources_count: int, items_count: int, llm_mode: bool) -> None:
    """Pam announces the start of a collection run."""
    _send(
        "pam",
        (
            f"▶️ Neue Runde gestartet — "
            f"*{sources_count}* Quellen, *{items_count}* neue Artikel, "
            f"LLM: {'an' if llm_mode else 'aus'}"
        ),
        color="gray",
    )


def run_finished(queued: int, rejected: int) -> None:
    """Pam announces the end of a run."""
    _send(
        "pam",
        f"⏹️ Runde abgeschlossen — *{queued}* in Queue, *{rejected}* abgelehnt",
        color="gray",
    )
