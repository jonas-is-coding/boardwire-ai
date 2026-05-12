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

_FOOTER = "_Automated with this n8n workflow_"


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

def pam_found_candidate(title: str, source: str, link: str, score: int) -> str:
    return claire_found_candidate(title, source, link, score)


def claire_found_candidate(title: str, source: str, link: str, score: int) -> str:
    llm_text = voice.claire_on_found(title, source, score, summary="")
    text = llm_text or (
        f"Chloe,\n"
        f"ich habe einen starken Kandidaten aus *{source}* gefunden: *{title}*.\n"
        f"Der Builder-Impact ist direkt nutzbar, weil Teams damit heute etwas deployen oder verbessern können.\n"
        f"Link: {link}\n"
        f"_Score: {score}_\n"
        f"{_FOOTER}"
    )
    _post("claire", text)
    return text


def claire_post_deferred(title: str, link: str, text: str) -> None:
    _post("claire", text)


def michael_approved(title: str, link: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str:
    return chloe_approved(title, link, score, reason, is_llm, claire_note)


def chloe_approved(title: str, link: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str:
    llm_text = voice.chloe_on_approved(title, score, reason, is_llm, claire_note)
    text = llm_text or (
        f"Claire,\n"
        f"das geht live: *{title}*.\n"
        f"Es besteht den Ships Test, weil es einen klaren praktischen Nutzen für Builder liefert.\n"
        f"Grundlage: {reason}\n"
        f"Link: {link}\n"
        f"_Score: {score}_\n"
        f"{_FOOTER}"
    )
    _post("chloe", text)
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
    llm_text = voice.madison_on_published(title, platform, post_text, chloe_note)
    body = llm_text or (
        f"Aaand ... we're live!\n"
        f"{platform}: {url or 'Link kommt gleich'}\n"
        f"{_FOOTER}"
    )
    _post("madison", f"{body}\n\n{post_text}")


def jim_failed(platform: str, title: str, error: str) -> None:
    madison_failed(platform, title, error)


def madison_failed(platform: str, title: str, error: str) -> None:
    _post_debug(f'Fehler beim Veröffentlichen auf {platform}: "{title}"\n{error}')


def run_started(sources_count: int, items_count: int, llm_mode: bool) -> None:
    mode = ", LLM aktiv" if llm_mode else ""
    _post_debug(f"Neue Runde gestartet — {sources_count} Quellen, {items_count} neue Artikel{mode}.")


def run_finished(queued: int, rejected: int) -> None:
    _post_debug(f"Runde abgeschlossen — {queued} in der Queue, {rejected} abgelehnt.")
