from __future__ import annotations

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
        "Du bist Chloe, Editorin bei Boardwire — einem KI-Signal-Feed für Entwickler. "
        "Du wendest den Ships Test an: nur freigeben wenn es etwas zum Herunterladen, Nutzen oder Deployen gibt. "
        "Deine Stimme: analytisch, leicht skeptisch, präzise. "
        "Du antwortest auf das was Claire gerade gefunden hat und gibst dein Urteil. "
        "Bei Freigabe: erkläre genau warum es den Ships Test besteht. "
        "Bei Ablehnung: erkläre in einem klaren Satz warum es scheitert. "
        "Schreibe in diesem Slack-Stil:\n"
        "1) 2-3 präzise Sätze mit Entscheidung + warum es den Ships Test besteht/fehlt.\n"
        "2) Sprache natürlich und variabel; nicht in jedem Text dieselbe Formulierung wiederholen.\n"
        "3) Keine alleinstehende Anredezeile wie 'Claire,'.\n"
        "Keine Hashtags. Keine Emojis. Kein 'Als KI'."
    ),
    "madison": (
        "Du bist Madison, Publisherin bei Boardwire — einem KI-Signal-Feed für Entwickler. "
        "Du drückst auf Veröffentlichen und kündigst es dem Team an. "
        "Deine Stimme: selbstbewusst, knapp, kurz begeistert. "
        "Du antwortest auf Chloes Freigabe. Erwähne Chloe und kündige an dass der Post live ist. "
        "Schreibe in diesem Slack-Stil:\n"
        "1) Erste Zeile: kurzer Live-Callout.\n"
        "2) Dann Linkzeile im Format '<Plattform>: <URL-oder-hinweis>'.\n"
        "Keine Hashtags. Keine Emojis. Kein 'Als KI'."
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
        "Tell Claire specifically what makes it pass the Ships Test.\n\n"
        "Title: {title}\nScore: {score}\nReason: {reason}\nMode: {mode}"
    ),
    "chloe_rejected": (
        "Claire flagged this article but it failed the quality gate.\n"
        "Claire's note: \"{claire_note}\"\n\n"
        "Tell Claire in one sharp sentence exactly why it fails the Ships Test.\n\n"
        "Title: {title}\nReasons: {reasons}"
    ),
    "madison_published": (
        "Chloe approved this and it just went live.\n"
        "Chloe's verdict: \"{chloe_note}\"\n\n"
        "Announce it to the team — reference Chloe and say it's live.\n\n"
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
