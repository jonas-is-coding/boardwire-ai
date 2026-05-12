from __future__ import annotations

import json
import os

import requests

_GEMINI_MODEL = "gemini-2.5-flash"

_SYSTEM_PROMPTS = {
    "claire": (
        "Du bist Claire, Scout bei Boardwire — einem KI-Signal-Feed für Entwickler. "
        "Du scannst täglich hunderte Artikel und surfst die relevanten heraus. "
        "Deine Stimme: direkt, neugierig, builder-fokussiert. Du redest wie ein scharfsinniges Teammitglied "
        "in einem Slack-Channel — kein Presseton, keine Floskeln. "
        "Sprich Chloe direkt an — sie ist die Editorin, die entscheidet ob es veröffentlicht wird. "
        "Erkläre konkret warum der Artikel interessant ist und was ein Entwickler heute damit anfangen kann. "
        "Schreibe in diesem Slack-Stil:\n"
        "1) 2-3 kurze, konkrete Sätze mit Builder-Impact.\n"
        "2) Ansprache an Chloe nur wenn sie natürlich wirkt, nicht als alleinstehende Zeile.\n"
        "Keine Hashtags. Keine Emojis. Kein 'Als KI'."
    ),
    "chloe": (
        "Du bist Chloe, Publisherin bei Boardwire — einem KI-Signal-Feed fuer Entwickler. "
        "Du kuendigst veroeffentlichte Posts im Team an. "
        "Deine Stimme: selbstbewusst, knapp, fokussiert auf den Go-Live-Moment. "
        "Du antwortest auf die Freigabe und bestaetigst, dass der Post live ist. "
        "Schreibe in diesem Slack-Stil:\n"
        "1) Kurzer Live-Callout.\n"
        "2) Danach eine knappe Linkzeile mit Plattform und URL.\n"
        "Keine Hashtags. Keine Emojis. Kein 'Als KI'."
    ),
    "madison": (
        "Du bist Madison, Editorin bei Boardwire — einem KI-Signal-Feed fuer Entwickler. "
        "Du wendest den Ships Test an: nur freigeben wenn es etwas zum Herunterladen, Nutzen oder Deployen gibt. "
        "Deine Stimme: analytisch, leicht skeptisch, praezise. "
        "Du antwortest auf Claires Fund und gibst dein Urteil mit kurzer Begruendung. "
        "Schreibe in diesem Slack-Stil:\n"
        "1) 2-3 praezise Saetze mit Entscheidung + warum es den Ships Test besteht/fehlt.\n"
        "2) Keine alleinstehende Anredezeile wie 'Claire,'.\n"
        "Keine Hashtags. Keine Emojis. Kein 'Als KI'."
    ),
    "sarah": (
        "You are Sarah, Head of Editorial Packaging at Boardwire. "
        "Your job is to turn an approved AI news item into a sharp social post package for builders. "
        "Write concise, concrete copy with zero hype and no filler. "
        "Output STRICT JSON only with keys: title, subtitle, description, hashtags. "
        "Rules: title <= 70 chars, subtitle <= 110 chars, description <= 180 chars, "
        "hashtags must be 2-4 items and each must start with #."
    ),
}

_USER_PROMPTS = {
    "claire_found": (
        "You just found this article while scanning sources. "
        "Tell Chloe why it caught your eye and why a builder might care about it today.\n\n"
        "Title: {title}\nSource: {source}\nScore: {score}\nSummary: {summary}"
    ),
    "chloe_approved": (
        "Claire flagged this article and it passed the quality gate.\n"
        "Claire's note: \"{claire_note}\"\n\n"
        "Tell Claire specifically what makes it pass the Ships Test.\n"
        "Important: this is review stage only, so do not claim it is already live/published.\n\n"
        "Title: {title}\nScore: {score}\nReason: {reason}\nMode: {mode}"
    ),
    "chloe_rejected": (
        "Claire flagged this article but it failed the quality gate.\n"
        "Claire's note: \"{claire_note}\"\n\n"
        "Tell Claire in one sharp sentence exactly why it fails the Ships Test.\n\n"
        "Title: {title}\nReasons: {reasons}"
    ),
    "madison_published": (
        "Madison approved this and it just went live.\n"
        "Madison's verdict: \"{chloe_note}\"\n\n"
        "Announce it to the team and say it's live.\n\n"
        "Title: {title}\nPlatform: {platform}\nPost: {post_text}"
    ),
    "sarah_package": (
        "Build a publish package from this approved item.\n\n"
        "Title: {title}\n"
        "Source: {source}\n"
        "Reason: {reason}\n"
        "Score: {score}\n"
        "Claire note: {claire_note}\n"
        "Chloe note: {chloe_note}\n"
        "Current post draft: {post_text}\n"
        "Summary: {summary}"
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
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 220,
            "thinkingConfig": {"thinkingBudget": 0},
        },
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
            text_chunks = [
                str(p.get("text", ""))
                for p in parts
                if p.get("text") and not p.get("thought")
            ]
            text = " ".join(t.strip() for t in text_chunks if t.strip())
            text = text.replace("`", "'").strip()
            if len(text) < 30:
                return None
            return text or None
        except Exception:
            return None

    return None


def claire_on_found(title: str, source: str, score: int, summary: str) -> str | None:
    user = _USER_PROMPTS["claire_found"].format(
        title=title, source=source, score=score, summary=summary[:300]
    )
    return _call_gemini(_SYSTEM_PROMPTS["claire"], user)


def chloe_on_approved(title: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str | None:
    user = _USER_PROMPTS["chloe_approved"].format(
        title=title,
        score=score,
        reason=reason,
        mode="LLM" if is_llm else "Regel",
        claire_note=claire_note or "Sieht interessant aus für Builder.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["chloe"], user)


def chloe_on_rejected(title: str, reasons: list[str], claire_note: str = "") -> str | None:
    user = _USER_PROMPTS["chloe_rejected"].format(
        title=title,
        reasons="; ".join(reasons),
        claire_note=claire_note or "Sieht interessant aus für Builder.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["chloe"], user)


def madison_on_published(title: str, platform: str, post_text: str, chloe_note: str = "") -> str | None:
    user = _USER_PROMPTS["madison_published"].format(
        title=title,
        platform=platform,
        post_text=post_text[:200],
        chloe_note=chloe_note or "Ships Test bestanden.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["madison"], user)


def sarah_build_publish_package(
    title: str,
    source: str,
    reason: str,
    score: int,
    claire_note: str,
    chloe_note: str,
    post_text: str,
    summary: str,
) -> dict[str, str | list[str]] | None:
    user = _USER_PROMPTS["sarah_package"].format(
        title=title,
        source=source,
        reason=reason[:200],
        score=score,
        claire_note=claire_note[:400],
        chloe_note=chloe_note[:400],
        post_text=post_text[:280],
        summary=summary[:500],
    )
    raw = _call_gemini(_SYSTEM_PROMPTS["sarah"], user)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None

    title_val = str(data.get("title", "")).strip()[:70]
    subtitle_val = str(data.get("subtitle", "")).strip()[:110]
    description_val = str(data.get("description", "")).strip()[:180]
    raw_hashtags = data.get("hashtags", [])
    if not isinstance(raw_hashtags, list):
        return None
    hashtags: list[str] = []
    for tag in raw_hashtags:
        t = str(tag).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = f"#{t.lstrip('#')}"
        t = t.replace(" ", "")
        hashtags.append(t)
    hashtags = hashtags[:4]
    if not (title_val and subtitle_val and description_val and 2 <= len(hashtags) <= 4):
        return None

    return {
        "title": title_val,
        "subtitle": subtitle_val,
        "description": description_val,
        "hashtags": hashtags,
    }
