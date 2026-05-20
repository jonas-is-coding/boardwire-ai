from __future__ import annotations

import os
from logging import Logger

_BUDGET_TOTAL: int | None = None
_BUDGET_USED = 0


def configure_gemini_budget() -> int:
    global _BUDGET_TOTAL
    if _BUDGET_TOTAL is not None:
        return _BUDGET_TOTAL
    raw = os.getenv("BOARDWIRE_GEMINI_CALL_BUDGET", "3").strip()
    try:
        total = int(raw)
    except ValueError:
        total = 3
    _BUDGET_TOTAL = max(0, total)
    return _BUDGET_TOTAL


def remaining_gemini_budget() -> int:
    total = configure_gemini_budget()
    return max(0, total - _BUDGET_USED)


def try_consume_gemini_budget(stage: str, logger: Logger) -> bool:
    global _BUDGET_USED
    total = configure_gemini_budget()
    if _BUDGET_USED >= total:
        logger.warning("Gemini budget exhausted; using fallback for %s", stage)
        return False
    _BUDGET_USED += 1
    return True


def mark_gemini_provider_exhausted(stage: str, logger: Logger) -> None:
    global _BUDGET_USED
    total = configure_gemini_budget()
    _BUDGET_USED = total
    logger.warning("Gemini provider exhausted; using fallback for %s", stage)
