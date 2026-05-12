from __future__ import annotations

import os

import requests

_GEMINI_MODEL = "gemini-2.5-flash"

_SYSTEM_PROMPTS = {
    "claire": (
        "You are Claire, Scout at Boardwire — an AI signal feed for builders. "
        "You scan hundreds of articles daily and surface the ones that matter. "
        "Your voice: direct, curious, builder-focused. You talk like a sharp team member "
        "in a Slack channel, not a press release. 2-3 sentences max. "
        "No hashtags. No emojis. No 'As an AI'. Respond in the same language as the article title."
    ),
    "chloe": (
        "You are Chloe, Editor at Boardwire — an AI signal feed for builders. "
        "You apply the Ships Test: only approve if there's something to download, use, or deploy right now. "
        "Your voice: analytical, slightly skeptical, precise. You talk like a sharp team member "
        "in a Slack channel. 2-3 sentences max. "
        "No hashtags. No emojis. No 'As an AI'. Respond in the same language as the article title."
    ),
    "madison": (
        "You are Madison, Publisher at Boardwire — an AI signal feed for builders. "
        "You're the one who hits publish. "
        "Your voice: confident, punchy, briefly excited. You talk like a sharp team member "
        "in a Slack channel celebrating a post going live. 1-2 sentences max. "
        "No hashtags. No emojis. No 'As an AI'. Respond in the same language as the article title."
    ),
}

_USER_PROMPTS = {
    "claire_found": (
        "You just found this article while scanning sources. "
        "Tell the team why it caught your eye and why a builder might care about it today.\n\n"
        "Title: {title}\nSource: {source}\nScore: {score}\nSummary: {summary}"
    ),
    "chloe_approved": (
        "You just approved this article for the review queue. "
        "Tell the team specifically what makes it pass the Ships Test.\n\n"
        "Title: {title}\nScore: {score}\nReason: {reason}\nMode: {mode}"
    ),
    "chloe_rejected": (
        "You just rejected this article. "
        "Tell the team in one sharp sentence why it failed the Ships Test.\n\n"
        "Title: {title}\nReasons: {reasons}"
    ),
    "madison_published": (
        "This just went live. Announce it to the team.\n\n"
        "Title: {title}\nPlatform: {platform}\nPost: {post_text}"
    ),
}


def _available_keys() -> list[str]:
    keys = []
    for env in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
        k = os.getenv(env, "").strip()
        if k:
            keys.append(k)
    return keys


def _call_gemini(system: str, user: str) -> str | None:
    keys = _available_keys()
    if not keys:
        return None

    model = os.getenv("BOARDWIRE_GEMINI_MODEL", _GEMINI_MODEL).strip() or _GEMINI_MODEL
    prompt = f"{system}\n\n{user}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 120},
    }

    idx = 0
    switches = 0
    max_switches = 3

    while switches <= max_switches:
        api_key = keys[idx % len(keys)]
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        try:
            resp = requests.post(url, json=body, timeout=10)
            if resp.status_code == 429 and len(keys) > 1:
                idx += 1
                switches += 1
                continue
            if resp.status_code >= 400:
                return None
            parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = str(parts[0].get("text", "")).strip() if parts else ""
            return text or None
        except Exception:
            return None

    return None


def claire_on_found(title: str, source: str, score: int, summary: str) -> str | None:
    user = _USER_PROMPTS["claire_found"].format(
        title=title, source=source, score=score, summary=summary[:300]
    )
    return _call_gemini(_SYSTEM_PROMPTS["claire"], user)


def chloe_on_approved(title: str, score: int, reason: str, is_llm: bool) -> str | None:
    user = _USER_PROMPTS["chloe_approved"].format(
        title=title, score=score, reason=reason, mode="LLM" if is_llm else "Regel"
    )
    return _call_gemini(_SYSTEM_PROMPTS["chloe"], user)


def chloe_on_rejected(title: str, reasons: list[str]) -> str | None:
    user = _USER_PROMPTS["chloe_rejected"].format(
        title=title, reasons="; ".join(reasons)
    )
    return _call_gemini(_SYSTEM_PROMPTS["chloe"], user)


def madison_on_published(title: str, platform: str, post_text: str) -> str | None:
    user = _USER_PROMPTS["madison_published"].format(
        title=title, platform=platform, post_text=post_text[:200]
    )
    return _call_gemini(_SYSTEM_PROMPTS["madison"], user)
