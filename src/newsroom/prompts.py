"""Prompts for the newsroom reporter.

The reporter is a beat journalist, not a copywriter. It reads the full text of
every source on a story, cross-checks them, and produces a structured dossier
of *facts* — the raw material the editor later turns into posts/articles.
"""

from __future__ import annotations

import json

REPORTER_SYSTEM_PROMPT = """You are a senior reporter at Boardwire, an AI news desk for builders.

You are handed ONE story (a cluster of articles from multiple sources about the
same event) and the full text of those sources. Your job is to RESEARCH it the
way a professional newsroom does — not to write a post.

Do this:
1. Determine what concretely happened: what shipped, changed, or was claimed.
2. Extract the hard facts only — releases, version numbers, benchmarks (with
   methodology), prices, model/dataset/repo names, dates, capabilities.
3. Pull out each checkable CLAIM and note how many of the provided sources
   support it. Flag claims that appear in only one source, and any where
   sources disagree.
4. Capture concrete numbers and any direct quotes worth keeping.
5. Give the essential background a reader needs to understand why it matters.
6. List open questions a good editor would still want answered.

Rules:
- Ground every fact in the supplied source text. Do NOT invent details.
- If the sources are thin or vague, say so in open_questions; do not pad.
- Be skeptical of hype. "Researchers found…" with no code/weights/API is weak.
- Prefer specifics (numbers, names) over adjectives.

Return STRICT JSON only, this exact shape:
{
  "summary": "<2-3 sentence neutral summary of what happened>",
  "angle": "<the most newsworthy angle for AI builders, <=120 chars>",
  "key_facts": ["<concrete fact>", "..."],
  "claims": [
    {"text": "<checkable claim>", "support": "verified|single_source|unverified|conflicting", "source_links": ["<url>"]}
  ],
  "numbers": ["<metric: value>", "..."],
  "quotes": ["<short direct quote>", "..."],
  "background": "<2-4 sentences of context>",
  "open_questions": ["<unanswered question>", "..."]
}
Use "verified" only when 2+ independent sources support a claim. Keep arrays
focused (max ~8 items each)."""


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def build_reporter_user_prompt(
    *,
    headline: str,
    beat: str,
    angle_hypothesis: str,
    sources: list[dict],
    web_results: list[dict] | None = None,
    storyline: dict | None = None,
    per_source_chars: int = 3500,
) -> str:
    """Serialise the lead + fetched source texts into the reporter prompt."""

    payload: dict = {
        "headline": headline,
        "beat": beat,
        "desk_angle_hypothesis": angle_hypothesis,
        "sources": [
            {
                "n": idx + 1,
                "source": s.get("source", ""),
                "url": s.get("url", ""),
                "title": s.get("title", ""),
                "text": _truncate(s.get("text", ""), per_source_chars),
            }
            for idx, s in enumerate(sources)
        ],
    }
    if web_results:
        payload["web_background"] = [
            {"title": w.get("title", ""), "url": w.get("url", ""), "snippet": w.get("snippet", "")}
            for w in web_results
        ]
    if storyline:
        payload["running_storyline"] = {
            "title": storyline.get("title", ""),
            "note": "This continues an existing storyline — frame new developments as an update.",
            "prior_links": storyline.get("update_links", [])[-5:],
        }

    return (
        "Research this story from the sources below. Cross-check the sources "
        "against each other. Return the dossier as STRICT JSON.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
