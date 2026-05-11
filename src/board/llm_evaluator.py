from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from src.board.evaluator import evaluate_item
from src.llm.client import GeminiClient, LLMConfig, LLMError, OpenAIClient
from src.llm.schemas import LLMBoardResult
from src.models import EvaluationResult, FeedItem, Persona
from src.writer.post_writer import generate_post


@dataclass(slots=True)
class Decision:
    evaluation: EvaluationResult
    post_text: str
    source_angle: str
    used_llm: bool


def _fallback(item: FeedItem, personas: list[Persona], reason: str, logger: Logger) -> Decision:
    logger.warning("Falling back to rule-based evaluator: %s", reason)
    evaluation = evaluate_item(item, personas)
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
        try:
            result = GeminiClient(api_key=llm_config.gemini_api_key, model=llm_config.gemini_model).evaluate_item(item)
        except LLMError as exc:
            return _fallback(item, personas, str(exc), logger)
        except Exception as exc:  # noqa: BLE001
            return _fallback(item, personas, f"Unexpected LLM error: {exc}", logger)
        return _from_llm_result(result)

    if force_llm:
        return _fallback(item, personas, f"Unsupported LLM provider: {llm_config.provider}", logger)
    else:
        return _fallback(item, personas, f"Unsupported LLM provider: {llm_config.provider}", logger)


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
