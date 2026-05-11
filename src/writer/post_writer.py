from __future__ import annotations

from src.config import POST_CHAR_LIMIT
from src.models import EvaluationResult, FeedItem


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _topic(item: FeedItem) -> str:
    t = f"{item.title} {item.summary}".lower()
    if "open source" in t or "open-weight" in t or "open model" in t:
        return "open_source"
    if "agent" in t or "workflow" in t or "coding" in t:
        return "agent_workflow"
    if "benchmark" in t or "evaluation" in t or "eval" in t:
        return "benchmark_eval"
    if "robotics" in t or "robot" in t:
        return "robotics"
    if "arxiv" in t or "paper" in t or "research" in t:
        return "research"
    if "inference" in t or "deployment" in t or "serving" in t or "infrastructure" in t:
        return "infrastructure"
    return "default"


def _insight_sentence(item: FeedItem) -> str:
    topic = _topic(item)
    title = item.title.strip()

    templates = {
        "open_source": f"{title}. The key signal is whether teams can inspect, adapt, and run these models without black-box constraints.",
        "agent_workflow": f"{title}. The practical question is how much reliability improves when agent tooling is used in real developer workflows.",
        "benchmark_eval": f"{title}. Benchmark movement matters most when evaluation setup is transparent and results transfer to production tasks.",
        "robotics": f"{title}. Robotics progress is meaningful when performance generalizes beyond curated demos into messy real-world settings.",
        "research": f"{title}. The useful part is the method and evidence quality, not just headline claims from a single result.",
        "infrastructure": f"{title}. Cost and deployment improvements matter when they hold under sustained production load, not only lab tests.",
        "default": f"{title}. The main signal is whether this changes measurable capability, reliability, or cost in day-to-day AI work.",
    }
    return templates[topic]


def generate_post(item: FeedItem, evaluation: EvaluationResult) -> str:
    base = _insight_sentence(item)
    if not evaluation.should_post:
        base = f"{base} Current signal is weak, so this stays out of priority coverage for now."
    return _trim(base, POST_CHAR_LIMIT)
