from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from urllib.parse import urlparse

from src.board.evaluator import evaluate_item
from src.llm.gemini_budget import (
    mark_gemini_provider_exhausted,
    mark_gemini_provider_temporarily_unavailable,
    try_consume_gemini_budget,
)
from src.llm.client import GeminiClient, LLMConfig, LLMError, OpenAIClient
from src.llm.schemas import LLMBoardResult
from src.models import EvaluationResult, FeedItem, Persona
from src.writer.post_writer import generate_post

from logging import Logger as _Logger


@dataclass(slots=True)
class Decision:
    evaluation: EvaluationResult
    post_text: str
    source_angle: str
    used_llm: bool


_FALLBACK_MIN_SCORE = 60
_FALLBACK_RELEASE_KEYWORDS = {
    "released",
    "ships",
    "launched",
    "open-sourced",
    "api",
    "sdk",
    "cli",
    "weights",
    "dataset",
    "benchmark",
    "playground",
}
_FALLBACK_BLOCK_TERMS = {
    "workflow",
    "understanding",
    "lessons",
    "approaches",
    "guide",
    "tutorial",
    "how to",
    "introduction",
    "introducing",
    "perspective",
    "opinion",
}


def _has_artifact_link(item: FeedItem) -> bool:
    link = (item.link or "").strip().lower()
    if not link:
        return False
    try:
        parsed = urlparse(link)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
    except Exception:
        return False
    if "github.com" in host:
        return "/releases" in path or "/tag/" in path or len([p for p in path.split("/") if p]) >= 2
    if "huggingface.co" in host:
        return any(seg in path for seg in ("/models/", "/datasets/", "/spaces/"))
    return False


def _has_release_signal(item: FeedItem) -> bool:
    haystack = f"{item.title} {item.summary}".lower()
    return any(k in haystack for k in _FALLBACK_RELEASE_KEYWORDS)


def _is_blocked_blog_opinion(item: FeedItem) -> bool:
    title = (item.title or "").lower()
    return any(term in title for term in _FALLBACK_BLOCK_TERMS)


def _enforce_conservative_fallback(item: FeedItem, evaluation: EvaluationResult) -> EvaluationResult:
    if _is_blocked_blog_opinion(item):
        return EvaluationResult(
            should_post=False,
            score=evaluation.score,
            reason="fallback blocked: blog/opinion/education pattern",
        )

    if evaluation.score < _FALLBACK_MIN_SCORE:
        return EvaluationResult(
            should_post=False,
            score=evaluation.score,
            reason="fallback score below publish threshold",
        )

    if item.source_tier in {2, 3}:
        has_extra_signal = (
            _has_artifact_link(item)
            or _has_release_signal(item)
            or float(item.engagement_score) >= 500
        )
        if not has_extra_signal:
            return EvaluationResult(
                should_post=False,
                score=evaluation.score,
                reason="fallback missing artifact/release signal for tier 2/3",
            )

    return EvaluationResult(
        should_post=bool(evaluation.should_post),
        score=evaluation.score,
        reason=evaluation.reason,
    )


def _fallback(item: FeedItem, personas: list[Persona], reason: str, logger: Logger) -> Decision:
    logger.warning("Falling back to rule-based evaluator: %s", reason)
    evaluation = evaluate_item(item, personas)
    evaluation = _enforce_conservative_fallback(item, evaluation)
    if not evaluation.should_post:
        logger.warning(
            "Rule fallback rejected: %s score=%d reason=%s",
            item.title,
            int(evaluation.score),
            evaluation.reason,
        )
    post_text = generate_post(item, evaluation)
    return Decision(
        evaluation=evaluation,
        post_text=post_text,
        source_angle="Rule-based fallback",
        used_llm=False,
    )


def evaluate_with_optional_llm(
    item: FeedItem,
    personas: list[Persona],
    llm_config: LLMConfig,
    force_llm: bool,
    logger: Logger,
) -> Decision:
    llm_enabled = llm_config.provider in {"openai", "gemini"} or force_llm
    if not llm_enabled:
        return _fallback(item, personas, "LLM disabled", logger)

    if llm_config.provider == "openai":
        if not llm_config.openai_api_key:
            return _fallback(item, personas, "OPENAI_API_KEY is missing", logger)
        try:
            result = OpenAIClient(api_key=llm_config.openai_api_key, model=llm_config.openai_model).evaluate_item(item)
        except LLMError as exc:
            return _fallback(item, personas, str(exc), logger)
        except Exception as exc:  # noqa: BLE001
            return _fallback(item, personas, f"Unexpected LLM error: {exc}", logger)
        return _from_llm_result(result)

    if llm_config.provider == "gemini":
        if not llm_config.gemini_api_key:
            return _fallback(item, personas, "GEMINI_API_KEY is missing", logger)
        if not try_consume_gemini_budget("evaluation", logger):
            return _fallback(item, personas, "Gemini budget exhausted", logger)
        try:
            result = GeminiClient(api_key=llm_config.gemini_api_key, model=llm_config.gemini_model).evaluate_item(item)
        except LLMError as exc:
            message = str(exc).lower()
            if " 503" in str(exc) or "error 503" in message:
                mark_gemini_provider_temporarily_unavailable("evaluation", logger)
            elif " 429" in str(exc) or "error 429" in message:
                mark_gemini_provider_exhausted("evaluation", logger)
            return _fallback(item, personas, str(exc), logger)
        except Exception as exc:  # noqa: BLE001
            return _fallback(item, personas, f"Unexpected LLM error: {exc}", logger)
        return _from_llm_result(result)

    if force_llm:
        return _fallback(item, personas, f"Unsupported LLM provider: {llm_config.provider}", logger)
    else:
        return _fallback(item, personas, f"Unsupported LLM provider: {llm_config.provider}", logger)


def rank_candidates_with_llm(
    items: list[FeedItem],
    top_k: int,
    llm_config: LLMConfig,
    logger: _Logger,
) -> list[FeedItem] | None:
    """Pre-filter a candidate pool down to top_k via a single LLM ranking call.

    Returns None on any failure so callers can fall back to the story_score order.
    Only Gemini is implemented (OpenAI uses the existing per-item flow).
    """
    if not items or top_k <= 0:
        return None
    if llm_config.provider != "gemini":
        return None
    if not llm_config.gemini_api_key:
        logger.warning("Batch ranking skipped: GEMINI_API_KEY missing")
        return None
    if not try_consume_gemini_budget("ranking", logger):
        return None

    client = GeminiClient(api_key=llm_config.gemini_api_key, model=llm_config.gemini_model)
    try:
        ranked = client.rank_candidates(items, top_k)
    except LLMError as exc:
        message = str(exc).lower()
        if " 503" in str(exc) or "error 503" in message:
            mark_gemini_provider_temporarily_unavailable("ranking", logger)
        elif " 429" in str(exc) or "error 429" in message:
            mark_gemini_provider_exhausted("ranking", logger)
        logger.warning("Batch ranking failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Batch ranking unexpected error: %s", exc)
        return None

    picked: list[FeedItem] = []
    seen_ids: set[int] = set()
    for entry in ranked:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        try:
            idx = int(str(raw_id))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(items) or idx in seen_ids:
            continue
        seen_ids.add(idx)
        picked.append(items[idx])
        if len(picked) >= top_k:
            break

    if not picked:
        logger.warning("Batch ranking returned no valid items, falling back")
        return None

    logger.info("Batch ranking: %d candidates -> %d picked by LLM", len(items), len(picked))
    return picked


def _from_llm_result(result: LLMBoardResult) -> Decision:
    evaluation = EvaluationResult(
        should_post=result.should_post,
        score=result.score,
        reason=result.reason,
    )
    return Decision(
        evaluation=evaluation,
        post_text=result.post,
        source_angle=result.source_angle,
        used_llm=True,
    )
