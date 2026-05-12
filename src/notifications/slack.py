from __future__ import annotations

import os
from typing import Literal

import requests

from src.notifications import persona_voice as voice

_WEBHOOKS: dict[str, str | None] = {}

_PERSONA_ENV = {
    "claire": "SLACK_WEBHOOK_URL_CLAIRE",
    "chloe": "SLACK_WEBHOOK_URL_CHLOE",
    "madison": "SLACK_WEBHOOK_URL_MADISON",
}


def _webhook(persona: str) -> str | None:
    if persona not in _WEBHOOKS:
        env_key = _PERSONA_ENV.get(persona, "")
        url = os.getenv(env_key, "").strip() if env_key else ""
        if not url:
            url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
        _WEBHOOKS[persona] = url or None
    return _WEBHOOKS[persona]


def _post(persona: str, payload: dict) -> None:
    url = _webhook(persona)
    if not url:
        return
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


_COLORS = {
    "green": "#2eb886",
    "yellow": "#f5a623",
    "red": "#d00000",
    "gray": "#aaaaaa",
}


def _send(
    persona: Literal["claire", "chloe", "madison"],
    text: str,
    color: str = "gray",
    fields: list[dict] | None = None,
    title: str | None = None,
    title_link: str | None = None,
) -> None:
    attachment: dict = {
        "color": _COLORS.get(color, color),
        "text": text,
        "mrkdwn_in": ["text"],
    }
    if title:
        attachment["title"] = title
    if title_link:
        attachment["title_link"] = title_link
    if fields:
        attachment["fields"] = fields

    _post(persona, {"attachments": [attachment]})


# ---------------------------------------------------------------------------
# Public notification events
# ---------------------------------------------------------------------------

def pam_found_candidate(title: str, source: str, link: str, score: int) -> str:
    return claire_found_candidate(title, source, link, score)


def claire_found_candidate(title: str, source: str, link: str, score: int) -> str:
    """Returns Claire's commentary so it can be passed to Chloe."""
    llm_text = voice.claire_on_found(title, source, score, summary="")
    text = llm_text or f"Neuer Kandidat aus *{source}* · Score *{score}*"
    _send("claire", text, color="yellow", title=title, title_link=link)
    return text


def claire_post_deferred(title: str, link: str, text: str) -> None:
    """Post a pre-generated Claire message (for interleaved ordering)."""
    _send("claire", text, color="yellow", title=title, title_link=link)


def michael_approved(title: str, link: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str:
    return chloe_approved(title, link, score, reason, is_llm, claire_note)


def chloe_approved(title: str, link: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str:
    """Returns Chloe's commentary so it can be passed to Madison."""
    llm_text = voice.chloe_on_approved(title, score, reason, is_llm, claire_note)
    text = llm_text or f"✅ Freigegeben ({'LLM' if is_llm else 'Regel'}) · Score {score}"
    _send(
        "chloe",
        text,
        color="green",
        title=title,
        title_link=link,
    )
    return text


def michael_rejected(title: str, link: str, reasons: list[str], claire_note: str = "") -> None:
    chloe_rejected(title, link, reasons, claire_note)


def chloe_rejected(title: str, link: str, reasons: list[str], claire_note: str = "") -> None:
    llm_text = voice.chloe_on_rejected(title, reasons, claire_note)
    text = llm_text or f"❌ {'; '.join(reasons)}"
    _send("chloe", text, color="red", title=title, title_link=link)


def michael_human_approved(review_id: str, title: str) -> None:
    chloe_human_approved(review_id, title)


def chloe_human_approved(review_id: str, title: str) -> None:
    _send("chloe", f"👍 Manuell genehmigt: *{title}*", color="green")


def michael_human_rejected(review_id: str, title: str) -> None:
    chloe_human_rejected(review_id, title)


def chloe_human_rejected(review_id: str, title: str) -> None:
    _send("chloe", f"👎 Manuell abgelehnt: *{title}*", color="red")


def jim_published(platform: str, title: str, post_text: str, url: str | None, with_image: bool, chloe_note: str = "") -> None:
    madison_published(platform, title, post_text, url, with_image, chloe_note)


def madison_published(platform: str, title: str, post_text: str, url: str | None, with_image: bool, chloe_note: str = "") -> None:
    llm_text = voice.madison_on_published(title, platform, post_text, chloe_note)
    image_note = " 🖼️" if with_image else ""
    link_text = f"\n🔗 <{url}|Post ansehen>" if url else ""
    body = llm_text or f"✅ Live auf *{platform}*{image_note}"
    _send("madison", f"{body}{link_text}\n\n_{post_text}_", color="green", title=title)


def jim_failed(platform: str, title: str, error: str) -> None:
    madison_failed(platform, title, error)


def madison_failed(platform: str, title: str, error: str) -> None:
    _send("madison", f"❌ Fehlgeschlagen auf *{platform}*\n'{error}'", color="red", title=title)


def run_started(sources_count: int, items_count: int, llm_mode: bool) -> None:
    _send(
        "claire",
        f"▶️ Neue Runde — *{sources_count}* Quellen, *{items_count}* neue Artikel"
        + (", LLM aktiv" if llm_mode else ""),
        color="gray",
    )


def run_finished(queued: int, rejected: int) -> None:
    _send(
        "claire",
        f"⏹️ Abgeschlossen — *{queued}* in Queue, *{rejected}* abgelehnt",
        color="gray",
    )
