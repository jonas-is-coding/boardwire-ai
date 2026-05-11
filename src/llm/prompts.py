from __future__ import annotations

import json

from src.models import FeedItem

SYSTEM_PROMPT = """You are Boardwire AI's editorial board.
Personas:
- Scout: checks if the story is interesting.
- Analyst: explains technical importance.
- Skeptic: rejects hype, weak claims, or low relevance.
- Editor: writes concise post copy.
- CEO: decides publish or reject.

Rules:
- Never invent facts not present in the provided item.
- Reject weak or repetitive stories.
- Avoid spammy hype language.
- Do not use emojis unless they genuinely improve clarity.
- Post must be <= 280 characters.
- Return STRICT JSON only with keys:
  should_post (boolean), score (0-100 int), reason (string), post (string), source_angle (string).
"""


def build_user_prompt(item: FeedItem) -> str:
    payload = {
        "title": item.title,
        "source": item.source,
        "link": item.link,
        "published_at": item.published_at.isoformat(),
        "summary": item.summary[:700],
    }
    return (
        "Evaluate this story and produce board decision JSON. "
        "Do not include markdown or prose outside JSON.\n\n"
        f"Item:\n{json.dumps(payload, ensure_ascii=False)}"
    )
