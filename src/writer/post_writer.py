from __future__ import annotations

from src.config import POST_CHAR_LIMIT
from src.models import EvaluationResult, FeedItem


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _topic(item: FeedItem) -> str:
    t = f"{item.title} {item.summary}".lower()
    if "open source" in t or "open-weight" in t or "open model" in t or "weights" in t:
        return "open_source"
    if "agent" in t or "agentic" in t or "workflow" in t or "tool use" in t:
        return "agent"
    if "benchmark" in t or "evaluation" in t or " eval " in t:
        return "benchmark"
    if "robotics" in t or "robot" in t:
        return "robotics"
    if "inference" in t or "deployment" in t or "serving" in t or "latency" in t:
        return "infra"
    if "fine-tun" in t or "training" in t or "dataset" in t:
        return "training"
    if "rag" in t or "retrieval" in t or "embedding" in t:
        return "retrieval"
    return "general"


def _builder_take(item: FeedItem) -> str:
    topic = _topic(item)
    title = item.title.strip().rstrip(".")

    takes = {
        "open_source": (
            f"{title}. "
            "Open weights mean you can inspect the model, run it locally, and fine-tune — "
            "worth evaluating against your current stack."
        ),
        "agent": (
            f"{title}. "
            "Agent reliability in production is still the hard part — "
            "check whether the evals reflect real task completion, not just capability demos."
        ),
        "benchmark": (
            f"{title}. "
            "A benchmark result only matters if the eval setup is public and "
            "the tasks map to something you actually need in production."
        ),
        "robotics": (
            f"{title}. "
            "Robotics progress is meaningful when it holds outside curated demos — "
            "look for generalization results across environments."
        ),
        "infra": (
            f"{title}. "
            "Inference and deployment improvements compound fast — "
            "check whether the numbers hold under sustained load, not just peak tests."
        ),
        "training": (
            f"{title}. "
            "Training improvements matter most when they reduce cost or data requirements — "
            "see whether the method is reproducible on smaller hardware."
        ),
        "retrieval": (
            f"{title}. "
            "Retrieval quality is the bottleneck most RAG systems hit first — "
            "check recall metrics on domain-specific data, not just generic benchmarks."
        ),
        "general": (
            f"{title}. "
            "The signal to watch: whether this changes measurable capability, "
            "reliability, or cost in real AI workloads."
        ),
    }
    return takes[topic]


def generate_post(item: FeedItem, evaluation: EvaluationResult) -> str:
    base = _builder_take(item)
    return _trim(base, POST_CHAR_LIMIT)
