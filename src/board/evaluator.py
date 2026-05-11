from __future__ import annotations

from src.models import EvaluationResult, FeedItem, Persona

KEYWORDS = {
    "ai": 3,
    "model": 2,
    "agent": 3,
    "benchmark": 2,
    "robotics": 2,
    "open source": 2,
    "research": 2,
    "llm": 3,
}


def evaluate_item(item: FeedItem, personas: list[Persona]) -> EvaluationResult:
    _ = personas
    haystack = f"{item.title} {item.summary}".lower()

    score = 0
    matched: list[str] = []
    for keyword, weight in KEYWORDS.items():
        if keyword in haystack:
            score += weight
            matched.append(keyword)

    should_post = score >= 3
    if should_post:
        reason = f"Matched keywords: {', '.join(matched[:4])}" if matched else "General relevance"
    else:
        reason = "Low relevance score for current AI/tech focus"

    return EvaluationResult(should_post=should_post, score=score, reason=reason)
