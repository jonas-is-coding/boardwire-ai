from __future__ import annotations

from dataclasses import dataclass

from src.config import POST_CHAR_LIMIT


@dataclass(slots=True)
class LLMBoardResult:
    should_post: bool
    score: int
    reason: str
    post: str
    source_angle: str


def clamp_score(score: int) -> int:
    return max(0, min(100, score))


def trim_post(text: str) -> str:
    if len(text) <= POST_CHAR_LIMIT:
        return text
    return text[: max(0, POST_CHAR_LIMIT - 1)].rstrip() + "…"


def validate_llm_result(payload: dict) -> LLMBoardResult:
    should_post = bool(payload["should_post"])
    score = clamp_score(int(payload["score"]))
    reason = str(payload["reason"]).strip()[:240]
    post = trim_post(str(payload["post"]).strip())
    source_angle = str(payload["source_angle"]).strip()[:280]

    if not reason:
        reason = "No reason provided"
    if not post:
        post = "No post generated"
    if not source_angle:
        source_angle = "No source angle provided"

    return LLMBoardResult(
        should_post=should_post,
        score=score,
        reason=reason,
        post=post,
        source_angle=source_angle,
    )
