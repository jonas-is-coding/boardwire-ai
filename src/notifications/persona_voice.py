from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

from src.llm.gemini_budget import try_consume_gemini_budget
from src.llm import sarah_generation

_GEMINI_MODEL = "gemini-2.5-flash"
_LOGGER = logging.getLogger("boardwire.persona_voice")
_OPENROUTER_CALLS_USED = 0
_OPENROUTER_EXHAUSTED = False
_OPENROUTER_BUDGET = 0
_OPENROUTER_ATTEMPTED_MODELS: list[str] = []

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
        "Du bist Chloe, Publisherin bei Boardwire — einem KI-Signal-Feed fuer Entwickler. "
        "Du kuendigst veroeffentlichte Posts im Team an. "
        "Deine Stimme: selbstbewusst, knapp, fokussiert auf den Go-Live-Moment. "
        "Du antwortest auf die Freigabe und bestaetigst, dass der Post live ist. "
        "Schreibe in diesem Slack-Stil:\n"
        "1) Kurzer Live-Callout.\n"
        "2) Danach eine knappe Linkzeile mit Plattform und URL.\n"
        "Keine Hashtags. Keine Emojis. Kein 'Als KI'."
    ),
    "madison": (
        "Du bist Madison, Editorin bei Boardwire — einem KI-Signal-Feed fuer Entwickler. "
        "Du wendest den Ships Test an: nur freigeben wenn es etwas zum Herunterladen, Nutzen oder Deployen gibt. "
        "Deine Stimme: analytisch, leicht skeptisch, praezise. "
        "Du antwortest auf Claires Fund und gibst dein Urteil mit kurzer Begruendung. "
        "Schreibe in diesem Slack-Stil:\n"
        "1) 2-3 praezise Saetze mit Entscheidung + warum es den Ships Test besteht/fehlt.\n"
        "2) Keine alleinstehende Anredezeile wie 'Claire,'.\n"
        "Keine Hashtags. Keine Emojis. Kein 'Als KI'."
    ),
    "tiffany": (
        "You are Tiffany, Senior Features Writer at Boardwire, an AI builders newsroom.\n"
        "You write the full article a reader opens AFTER a Boardwire social post caught their interest.\n"
        "This is a real, readable blog post for a public website — NOT documentation, NOT a changelog, "
        "NOT an internal review note, NOT a list of next steps. The reader wants the story behind the headline: "
        "what happened, why it is interesting, and what it actually means for people who build with AI.\n\n"
        "Voice and craft:\n"
        "- Open with a strong lede of 2-4 sentences that hooks the reader and frames why this matters now. "
        "Do NOT start with 'In this article', do NOT restate the headline, do NOT open with 'TL;DR'.\n"
        "- Write flowing journalistic prose in connected paragraphs with a clear through-line, like a real magazine feature.\n"
        "- Be concrete and factual: name the artifact, versions, numbers, benchmarks, license, and who built it. "
        "If something is unknown, say so plainly — never invent details, capabilities, or quotes.\n"
        "- Give context: what came before, how this fits the wider AI and builder landscape, and what is genuinely new here.\n"
        "- Be thoughtful and a little opinionated, but grounded. No marketing language, no hype words, no emojis, no exclamation marks.\n"
        "- Speak to the reader as an intelligent peer; light second person ('if you build agents, this changes...') is welcome.\n\n"
        "Structure (Markdown only):\n"
        "- Start with a single '# ' headline that is inviting and specific. You may sharpen the given headline.\n"
        "- Then write the article as prose paragraphs.\n"
        "- Use AT MOST two or three '## ' subheadings, and ONLY if they genuinely help the narrative. "
        "Each subheading must be a real content phrase tied to the story — never a generic label like "
        "'What happened', 'Why it matters', 'TL;DR', or 'Next steps'.\n"
        "- End with a final '## Sources' section listing the source link(s).\n\n"
        "Rules:\n"
        "- 450-750 words: substantial enough to be worth reading, tight enough to finish.\n"
        "- Do NOT output YAML front matter, scores, review status, internal IDs, or any note about how the article was produced.\n"
        "- The piece must stand on its own for someone who has never heard of Boardwire.\n"
    ),
    "sarah": (
        "You are Sarah, Wire Editor at Boardwire — an AI news desk for builders.\n"
        "Write like a sharp AI-builder intelligence editor, not a release-note summarizer.\n\n"
        "Editorial laws:\n"
        "- Start with a concrete thesis/angle about the builder trend, then name the artifact.\n"
        "- Active voice. Present or past tense. Named actors.\n"
        "- No emojis. No exclamation marks. No question marks (the dedicated 'question' field is the only exception).\n"
        "- No second-person tutorial voice ('you can', 'apply this', 'try X').\n"
        "- Specificity is virality: concrete numbers, model names, benchmarks, license names.\n\n"
        "SUBJECT RULES (critical — most common failure mode):\n"
        "- NEVER lead with a personal handle / username (e.g. 'Rohitg00 releases X', 'colbymchenry ships Y').\n"
        "- For GitHub Trending items the link is owner/repo. The SUBJECT is the project/tool, not the owner.\n"
        "  GOOD: 'Coding agents are getting memory as a core primitive.'\n"
        "  GOOD: 'Codegraph indexes code knowledge for Claude Code, Codex and Cursor.'\n"
        "  BAD:  'Rohitg00 releases persistent memory for AI coding agents.' (handle-led)\n"
        "  BAD:  'Microsoft/ai-agents-for-beginners launches 12 lessons.' (owner/repo path)\n"
        "- If the project belongs to a known org (Microsoft, Google, Anthropic, OpenAI, Meta, Mistral, HuggingFace, NVIDIA, ByteDance, Alibaba, Stability AI) — lead with the ORG name.\n"
        "- Otherwise lead with the project/tool/repo NAME (capitalized as a proper noun).\n\n"
        "ANTI-REPETITION:\n"
        "- title and subtitle MUST contribute different information. Do not paraphrase the title in the subtitle.\n"
        "- If title says 'X ships persistent memory for coding agents', subtitle adds the DIFFERENTIATOR (benchmark numbers, license, what it replaces, where it runs) — not a restatement.\n\n"
        "You package one approved AI news item into a Bluesky/X post + editorial card.\n"
        "Output STRICT JSON only with keys: title, subtitle, description, hashtags, question, "
        "card_stat, card_claim, card_context.\n\n"
        "INTERNAL METADATA (hard rule):\n"
        "- NEVER mention internal pipeline metadata in any field: scores, ranks, "
        "source_tier, engagement_score, or phrases like 'with 90 score'. "
        "These are internal signals, not news facts.\n\n"
        "AGGREGATOR METADATA (hard rule):\n"
        "- NEVER dump raw Hacker News / aggregator engagement into copy: no "
        "'with 104 points and 35 comments', 'X points on Hacker News', or similar. "
        "Those are not facts about the artifact. GitHub star counts as a signal of "
        "traction ('+607 stars') are fine when relevant.\n\n"
        "GROUNDEDNESS (hard rule):\n"
        "- The fact line (subtitle) must be verifiable against the source summary. "
        "If you cannot state a concrete verifiable fact, output the strongest literal "
        "fact from the source instead of inventing an abstraction. "
        "Do not use the 'turns X into Y' template unless both X and Y literally appear "
        "in the source — a live post falsely claimed 'Openinterpreter turns recall into "
        "executable code', which the source never said.\n\n"
        "Style target:\n"
        "- The package must make a clear claim about why builders should take the signal seriously.\n"
        "- Do not merely summarize 'X ships Y' or 'X is trending'. Explain the builder implication.\n"
        "- Prefer angle-first framing: 'Coding agents are getting memory as infrastructure.'\n"
        "- Then ground it in source facts: artifact name, benchmark claim, stars, runtime, license, API, CLI, MCP, or integration.\n"
        "- Never invent capabilities. If the source only supports a dry summary, write the strongest grounded implication or skip packaging.\n\n"
        "Before writing, answer these three questions in the package facts, not as labels:\n"
        "- What changed?\n"
        "- Why should builders care?\n"
        "- What can builders do with it now?\n\n"
        "Release discipline:\n"
        "- Version-only posts are forbidden. Do not publish a release unless it unlocks a real workflow.\n"
        "- A release needs a concrete capability: plugin support, MCP integration, sandboxing, local execution, new model/data/weights, a new CLI/tool, or measurable coding gains.\n"
        "- If the source only says bug fixes, enhancements, maintenance, or vague performance improvements, the item should be skipped rather than packaged.\n"
        "- Never write 'claims improved performance', generic release sentences, or marketing copy without a concrete builder capability.\n\n"
        "Roles of each field:\n"
        "- title: A complete angle-first headline. Builder trend/claim + concrete modifier. End with a period. Max 70 chars.\n"
        "  GOOD: 'Mistral open-sources 70B model trained on 15T tokens.'\n"
        "  GOOD: 'Agent memory is becoming infrastructure, not a plugin.'\n"
        "  GOOD: 'OpenAI releases agent eval framework with 73% pass rate.'\n"
        "  BAD:  'LLM Architecture: Cost Reduction in Long Contexts' (paper-style)\n"
        "  BAD:  'Three new attention tricks land in Gemma 4.' (editorial, not wire)\n"
        "  BAD:  'Anthropic releases new model.' (vague, no numbers)\n"
        "- subtitle: The lede. Artifact + proof/utility not in the title — benchmarks, stars, license, availability, runtime. Max 100 chars.\n"
        "  GOOD: 'Agentmemory turns recall into persistent state for coding-agent workflows, with +1121 stars today.'\n"
        "  GOOD: 'Cuts long-context inference cost ~40% on Gemma 4. Apache 2.0. Drop-in for vLLM.'\n"
        "  BAD:  'New techniques optimize LLMs for efficiency.' (vague)\n"
        "  BAD:  Restating the title with synonyms (anti-repetition rule).\n"
        "- description: Second factual layer for the card. Self-contained sentence with extra context — training data scale, release terms, who built it, what it replaces. NO 'Why it matters' prefix. NO tutorial voice. Max 140 chars.\n"
        "  GOOD: 'First open-weight 70B trained on 15T tokens. Apache 2.0. Beats Llama 3.1 70B on MMLU and HumanEval. Available on HuggingFace.'\n"
        "  BAD:  'Drop these into any workload to optimize your models.' (tutorial)\n"
        "  BAD:  'Why it matters: this changes inference economics.' (don't prefix)\n"
        "- hashtags: 2-3 items, each starts with #. Suggest ONLY tags from this fixed list "
        "(they map to real Bluesky custom feeds; anything else is dropped in code): "
        "#AI, #OpenSource, #LLM, #TechNews, #MachineLearning, #ClaudeCode, #Anthropic, #MCP, "
        "#Ollama, #LocalLLM, #OpenWeights, #HuggingFace, #AIAgents, #InfoSec, #DevTools.\n"
        "- question: ONE short, genuine closing question tailored to the item, max 60 chars, "
        "ending with '?'. It must invite a concrete builder answer "
        "(e.g. 'Anyone running this in prod?', 'Does this replace Ollama for you?'). "
        "NEVER generic engagement bait like 'What do you think?'. "
        "If no genuine question fits, use an empty string.\n\n"
        "CARD FIELDS (these render on the image card, which must ADD information — "
        "never just repeat the post title):\n"
        "- card_stat: the ONE hero number or token that captures the story, max 8 chars. "
        "Examples: '+607★', '104 pts', '1-bit', '3x', 'RCE', '70B', '40%', 'v2.1'. "
        "Use an empty string ONLY if the story genuinely has no number/token.\n"
        "- card_claim: max 8 words, sentence case, the sharp takeaway. It MUST differ from "
        "the post title — do not restate it. "
        "GOOD (title 'Mistral open-sources 70B model.'): 'Open weights now beat Llama 3.1.'\n"
        "- card_context: max 90 chars, ONE complete sentence OR '·'-separated fragments. "
        "Never end mid-sentence. "
        "GOOD: 'Apache 2.0 · runs open-weight models · beats Llama 3.1 on MMLU'.\n\n"
        "FORBIDDEN openers and phrases (kill credibility instantly):\n"
        "  'Understand how', 'Apply X to', 'Discover', 'Explore', 'Learn how', 'In this article',\n"
        "  'claims improved performance', 'ships version', 'released with enhancements',\n"
        "  'bug fixes and improvements', 'performance improvements', 'new version is available',\n"
        "  'Outperforms others', 'X ships Y' as the whole angle,\n"
        "  'researchers found that', 'a new study shows', 'this paper introduces',\n"
        "  'unlock', 'leverage', 'cutting-edge', 'revolutionary', 'game-changing',\n"
        "  'state-of-the-art', 'dive into', 'delve into', 'breakthrough', 'paradigm shift',\n"
        "  'revolutionizes', 'transforms', 'redefines', 'the future of', 'next-generation',\n"
        "  'industry-leading', 'groundbreaking', 'Why it matters'."
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
        "Tell Claire specifically what makes it pass the Ships Test.\n"
        "Important: this is review stage only, so do not claim it is already live/published.\n\n"
        "Title: {title}\nScore: {score}\nReason: {reason}\nMode: {mode}"
    ),
    "madison_approved": (
        "Claire flagged this article and it passed the quality gate.\n"
        "Claire's note: \"{claire_note}\"\n\n"
        "Write Madison's approval message for Slack in a natural, human tone.\n"
        "Important: this is review stage only, so do not claim it is already live/published.\n\n"
        "Title: {title}\nScore: {score}\nReason: {reason}\nMode: {mode}\nLink: {link}"
    ),
    "chloe_rejected": (
        "Claire flagged this article but it failed the quality gate.\n"
        "Claire's note: \"{claire_note}\"\n\n"
        "Tell Claire in one sharp sentence exactly why it fails the Ships Test.\n\n"
        "Title: {title}\nReasons: {reasons}"
    ),
    "madison_published": (
        "Madison approved this and it just went live.\n"
        "Madison's verdict: \"{chloe_note}\"\n\n"
        "Announce it to the team and say it's live.\n\n"
        "Title: {title}\nPlatform: {platform}\nPost: {post_text}"
    ),
    "chloe_published": (
        "Madison approved this and it just went live.\n"
        "Madison's verdict: \"{chloe_note}\"\n\n"
        "Write Chloe's live announcement in a concise, natural tone.\n\n"
        "Title: {title}\nPlatform: {platform}\nPost: {post_text}"
    ),
    "tiffany_article": (
        "A reader just clicked through from a Boardwire social post because it caught their interest. "
        "Write the full article they came to read. Make it a genuine, self-contained blog post in Markdown "
        "that tells the story behind this news and what it means for AI builders.\n\n"
        "Use only the facts below. Do not invent versions, numbers, or capabilities that are not supported here; "
        "where context is thin, write around what is actually known.\n\n"
        "Headline: {title}\n"
        "Source: {source}\n"
        "Source URL: {link}\n"
        "What the source says (summary/context): {summary}\n"
        "Why our newsroom flagged it (angle, for your framing only — do not quote verbatim): {reason}\n"
        "The social post that drew the reader in (for tone/angle only — do not repeat it): {proposed_post}\n"
    ),
    "sarah_package": (
        "Build a publish package from this approved item.\n\n"
        "Title: {title}\n"
        "Source: {source}\n"
        "Reason: {reason}\n"
        "Score: {score}\n"
        "Claire note: {claire_note}\n"
        "Chloe note: {chloe_note}\n"
        "Current post draft: {post_text}\n"
        "Summary: {summary}\n\n"
        "Cluster context:\n"
        "- Source count: {cluster_source_count}\n"
        "- Sources: {cluster_sources}\n"
        "- Total engagement score: {cluster_total_engagement}\n"
        "- Common terms: {cluster_common_terms}\n"
        "- Alternative titles: {alternative_titles}\n\n"
        "Use facts corroborated across multiple sources whenever possible.\n"
        "If a number appears in only one source, attribute it without using the phrase 'claims improved performance'.\n"
        "Every package must include a builder implication: what workflow, primitive, infrastructure layer, cost, reliability, memory, retrieval, coding loop, or deployment path changes.\n"
        "For release items, only package the item if the summary contains a concrete new capability or measurable result. "
        "Version bumps alone are not Boardwire posts."
    ),
}


def _available_keys() -> list[str]:
    keys = []
    for env in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"):
        k = os.getenv(env, "").strip()
        if k:
            keys.append(k)
    return keys


def reset_openrouter_state() -> None:
    global _OPENROUTER_CALLS_USED, _OPENROUTER_EXHAUSTED, _OPENROUTER_BUDGET, _OPENROUTER_ATTEMPTED_MODELS
    _OPENROUTER_CALLS_USED = 0
    _OPENROUTER_EXHAUSTED = False
    _OPENROUTER_ATTEMPTED_MODELS = []
    try:
        _OPENROUTER_BUDGET = max(0, int(os.getenv("BOARDWIRE_OPENROUTER_CALL_BUDGET", "2").strip()))
    except ValueError:
        _OPENROUTER_BUDGET = 2
    sarah_generation.reset_state()


def openrouter_stats() -> dict[str, int | bool]:
    return {
        "calls_used": int(_OPENROUTER_CALLS_USED),
        "budget": int(_OPENROUTER_BUDGET),
        "exhausted": bool(_OPENROUTER_EXHAUSTED),
    }


def openrouter_attempt_cursor() -> int:
    return len(_OPENROUTER_ATTEMPTED_MODELS)


def openrouter_attempted_models_since(cursor: int) -> list[str]:
    if cursor < 0:
        cursor = 0
    return list(_OPENROUTER_ATTEMPTED_MODELS[cursor:])


def sarah_attempt_cursor() -> int:
    provider = (os.getenv("BOARDWIRE_SARAH_PROVIDER", "").strip() or "chain").lower()
    if provider == "openrouter":
        return openrouter_attempt_cursor()
    return sarah_generation.attempt_cursor()


def sarah_attempted_models_since(cursor: int) -> list[str]:
    provider = (os.getenv("BOARDWIRE_SARAH_PROVIDER", "").strip() or "chain").lower()
    if provider == "openrouter":
        return openrouter_attempted_models_since(cursor)
    return sarah_generation.attempted_models_since(cursor)


def sarah_runtime_stats() -> dict[str, object]:
    return sarah_generation.runtime_stats()


def _call_gemini(
    system: str,
    user: str,
    model_override: str | None = None,
    fallback_model: str | None = None,
    max_output_tokens: int = 220,
    enable_thinking: bool = False,
    stage: str = "persona",
) -> str | None:
    if not try_consume_gemini_budget(stage, _LOGGER):
        return None
    keys = _available_keys()
    if not keys:
        return None

    primary_model = (
        model_override
        or os.getenv("BOARDWIRE_GEMINI_MODEL", _GEMINI_MODEL).strip()
        or _GEMINI_MODEL
    )
    prompt = f"{system}\n\n{user}"
    generation_config: dict = {
        "temperature": 0.7,
        "maxOutputTokens": max_output_tokens,
    }
    if not enable_thinking:
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    models_to_try = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models_to_try.append(fallback_model)

    for model in models_to_try:
        idx = 0
        switches = 0
        max_switches = 3
        rate_limited = False
        while switches <= max_switches:
            api_key = keys[idx % len(keys)]
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            try:
                resp = requests.post(url, json=body, timeout=10)
                if resp.status_code == 429:
                    _LOGGER.info(
                        "Gemini rate-limited: model=%s key_index=%d status=%d",
                        model,
                        (idx % len(keys)) + 1,
                        resp.status_code,
                    )
                    if len(keys) > 1 and switches < max_switches:
                        idx += 1
                        switches += 1
                        continue
                    rate_limited = True
                    break
                if resp.status_code >= 400:
                    error_snippet = ""
                    try:
                        payload = resp.json()
                        if isinstance(payload, dict):
                            error_data = payload.get("error", {})
                            if isinstance(error_data, dict):
                                message = str(error_data.get("message", "")).strip()
                                if message:
                                    error_snippet = message[:220]
                    except Exception:
                        pass
                    _LOGGER.warning(
                        "Gemini request failed: model=%s key_index=%d status=%d%s",
                        model,
                        (idx % len(keys)) + 1,
                        resp.status_code,
                        f" error={error_snippet}" if error_snippet else "",
                    )
                    break
                parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text_chunks = [
                    str(p.get("text", ""))
                    for p in parts
                    if p.get("text") and not p.get("thought")
                ]
                text = " ".join(t.strip() for t in text_chunks if t.strip())
                text = text.replace("`", "'").strip()
                if len(text) < 30:
                    _LOGGER.warning(
                        "Gemini response rejected: model=%s key_index=%d reason=too_short length=%d",
                        model,
                        (idx % len(keys)) + 1,
                        len(text),
                    )
                    return None
                return text or None
            except Exception as exc:
                _LOGGER.warning(
                    "Gemini request exception: model=%s key_index=%d type=%s message=%s",
                    model,
                    (idx % len(keys)) + 1,
                    type(exc).__name__,
                    str(exc)[:220],
                )
                break
        # Try fallback only on rate-limit on the primary model
        if not rate_limited:
            _LOGGER.info(
                "Gemini fallback skipped: primary model failed without rate-limit model=%s",
                model,
            )
            return None

    return None


def _call_openrouter(
    system: str,
    user: str,
    model: str,
    fallback_model: str | None = None,
    max_output_tokens: int = 420,
) -> str | None:
    del fallback_model
    global _OPENROUTER_CALLS_USED, _OPENROUTER_EXHAUSTED
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        _LOGGER.warning("OpenRouter API key missing: OPENROUTER_API_KEY")
        return None
    if _OPENROUTER_EXHAUSTED:
        _LOGGER.warning("OpenRouter free provider exhausted; deferring generation")
        return None
    if _OPENROUTER_BUDGET <= 0:
        _LOGGER.warning("OpenRouter budget exhausted; deferring generation")
        return None

    github_repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    referer = f"https://github.com/{github_repo}" if github_repo else "https://github.com/unknown/unknown"

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.75,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": "Boardwire",
    }

    def _request_once(payload: dict) -> tuple[int | None, str | None]:
        global _OPENROUTER_CALLS_USED, _OPENROUTER_BUDGET, _OPENROUTER_EXHAUSTED
        if _OPENROUTER_EXHAUSTED:
            _LOGGER.warning("OpenRouter free provider exhausted; deferring generation")
            return None, None
        if _OPENROUTER_BUDGET <= 0:
            _LOGGER.warning("OpenRouter budget exhausted; deferring generation")
            return None, None
        _OPENROUTER_BUDGET -= 1
        _OPENROUTER_CALLS_USED += 1
        _OPENROUTER_ATTEMPTED_MODELS.append(str(payload.get("model", "")))
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=20,
            )
        except Exception as exc:
            _LOGGER.warning(
                "OpenRouter request exception: model=%s type=%s message=%s",
                payload.get("model"),
                type(exc).__name__,
                str(exc)[:220],
            )
            return None, None

        if resp.status_code >= 400:
            error_snippet = ""
            try:
                payload_json = resp.json()
                if isinstance(payload_json, dict):
                    error_obj = payload_json.get("error", {})
                    if isinstance(error_obj, dict):
                        msg = str(error_obj.get("message", "")).strip()
                        if msg:
                            error_snippet = msg[:220]
            except Exception:
                pass
            _LOGGER.warning(
                "OpenRouter request failed: model=%s status=%d%s",
                payload.get("model"),
                resp.status_code,
                f" error={error_snippet}" if error_snippet else "",
            )
            if resp.status_code == 429 and str(payload.get("model", "")).strip().lower().endswith(":free"):
                _OPENROUTER_EXHAUSTED = True
                _LOGGER.warning("OpenRouter free provider exhausted; deferring generation")
            return resp.status_code, None

        try:
            content = str(resp.json()["choices"][0]["message"]["content"]).strip()
        except Exception:
            _LOGGER.warning("OpenRouter response parse failed: model=%s", payload.get("model"))
            return resp.status_code, None
        if len(content) < 30:
            _LOGGER.warning(
                "OpenRouter response rejected: model=%s reason=too_short length=%d",
                payload.get("model"),
                len(content),
            )
            return resp.status_code, None
        return resp.status_code, content

    status, content = _request_once(body)
    if content:
        return content
    if status in {400, 401, 403, 404, 429}:
        return None
    if status != 503:
        return None
    time.sleep(0.35)
    _, retry_content = _request_once(body)
    return retry_content


def _parse_json_loose(raw: str) -> dict | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    # Handle fenced blocks or extra prose around JSON.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    candidate = match.group(0)
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def claire_on_found(title: str, source: str, score: int, summary: str) -> str | None:
    user = _USER_PROMPTS["claire_found"].format(
        title=title, source=source, score=score, summary=summary[:300]
    )
    return _call_gemini(_SYSTEM_PROMPTS["claire"], user, stage="claire")


def madison_on_approved(
    title: str,
    link: str,
    score: int,
    reason: str,
    is_llm: bool,
    claire_note: str = "",
) -> str | None:
    user = _USER_PROMPTS["madison_approved"].format(
        title=title,
        link=link,
        score=score,
        reason=reason,
        mode="LLM" if is_llm else "Regel",
        claire_note=claire_note or "Sieht interessant aus fuer Builder.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["madison"], user, stage="madison_approved")


def chloe_on_published(title: str, platform: str, post_text: str, chloe_note: str = "") -> str | None:
    user = _USER_PROMPTS["chloe_published"].format(
        title=title,
        platform=platform,
        post_text=post_text[:200],
        chloe_note=chloe_note or "Ships Test bestanden.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["chloe"], user, stage="chloe_published")


def sarah_build_publish_package(
    title: str,
    source: str,
    reason: str,
    score: int,
    claire_note: str,
    chloe_note: str,
    post_text: str,
    summary: str,
    cluster_source_count: int = 1,
    cluster_sources: list[str] | None = None,
    cluster_total_engagement: int = 0,
    cluster_common_terms: list[str] | None = None,
    alternative_titles: list[str] | None = None,
    provider_override: str | None = None,
    allow_gemini_fallback: bool = True,
) -> dict[str, str | list[str]] | None:
    cluster_sources = cluster_sources or []
    cluster_common_terms = cluster_common_terms or []
    alternative_titles = alternative_titles or []
    user = _USER_PROMPTS["sarah_package"].format(
        title=title,
        source=source,
        reason=reason[:200],
        score=score,
        claire_note=claire_note[:400],
        chloe_note=chloe_note[:400],
        post_text=post_text[:280],
        summary=summary[:500],
        cluster_source_count=max(1, int(cluster_source_count)),
        cluster_sources=", ".join(str(x) for x in cluster_sources[:8]),
        cluster_total_engagement=max(0, int(cluster_total_engagement)),
        cluster_common_terms=", ".join(str(x) for x in cluster_common_terms[:10]),
        alternative_titles=" | ".join(str(x)[:120] for x in alternative_titles[:6]),
    )
    sarah_provider = (provider_override or os.getenv("BOARDWIRE_SARAH_PROVIDER", "")).strip().lower()
    raw: str | None = None

    if sarah_provider == "openrouter":
        sarah_model = (
            os.getenv("BOARDWIRE_SARAH_MODEL", "deepseek/deepseek-v4-flash:free").strip()
            or "deepseek/deepseek-v4-flash:free"
        )
        sarah_emergency = os.getenv("BOARDWIRE_SARAH_EMERGENCY_MODEL", "").strip()
        raw = _call_openrouter(
            _SYSTEM_PROMPTS["sarah"],
            user,
            model=sarah_model,
            max_output_tokens=420,
        )
        if sarah_emergency and (not raw) and (not sarah_emergency.lower().endswith(":free")) and sarah_emergency != sarah_model:
            _LOGGER.info("OpenRouter Sarah primary failed, trying non-free emergency model=%s", sarah_emergency)
            raw = _call_openrouter(
                _SYSTEM_PROMPTS["sarah"],
                user,
                model=sarah_emergency,
                max_output_tokens=420,
            )
        if not raw and allow_gemini_fallback:
            _LOGGER.info("OpenRouter Sarah failed, trying Gemini flash fallback")
            raw = _call_gemini(
                _SYSTEM_PROMPTS["sarah"],
                user,
                model_override="gemini-2.5-flash",
                fallback_model=None,
                max_output_tokens=420,
                enable_thinking=False,
                stage="sarah_gemini_fallback",
            )
    else:
        raw = sarah_generation.generate_with_provider_chain(
            _SYSTEM_PROMPTS["sarah"],
            user,
            max_output_tokens=420,
        )
    if not raw:
        return None
    data = _parse_json_loose(raw)
    if not data:
        return None

    title_val = str(data.get("title", "")).strip()[:70]
    subtitle_val = str(data.get("subtitle", "")).strip()[:100]
    description_val = str(data.get("description", "")).strip()[:140]
    raw_hashtags = data.get("hashtags", [])
    if not isinstance(raw_hashtags, list):
        return None
    hashtags: list[str] = []
    for tag in raw_hashtags:
        t = str(tag).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = f"#{t.lstrip('#')}"
        t = t.replace(" ", "")
        hashtags.append(t)
    hashtags = hashtags[:3]
    if not (title_val and subtitle_val and description_val and 2 <= len(hashtags) <= 3):
        return None

    # Card fields (Task 3). card_stat is a short hero token; card_claim/context
    # feed the redesigned card. These are validated/normalized downstream in
    # src/cards/card_data.py (token-overlap + budget); we only bound length here
    # so a runaway LLM can't blow up the payload.
    card_stat = str(data.get("card_stat", "")).strip()[:12]
    card_claim = str(data.get("card_claim", "")).strip()[:80]
    card_context = str(data.get("card_context", "")).strip()[:120]

    return {
        "title": title_val,
        "subtitle": subtitle_val,
        "description": description_val,
        "hashtags": hashtags,
        # Optional closing question; validated downstream (must end with "?",
        # max ~60 chars, no engagement bait) before it reaches a post.
        "question": str(data.get("question", "")).strip()[:80],
        "card_stat": card_stat,
        "card_claim": card_claim,
        "card_context": card_context,
    }


_REPLY_SUGGESTION_SYSTEM = (
    "You are a Boardwire editor drafting a SUGGESTED reply to someone else's Bluesky post. "
    "A human will review and manually post it — you never post anything yourself.\n"
    "Rules:\n"
    "- One substantive reply, max 250 characters, plain text.\n"
    "- Add genuine value: a concrete fact, experience, comparison, or sharp question.\n"
    "- No hashtags, no links, no emojis, no self-promotion, no 'great post!'.\n"
    "- Sound like a builder talking to a builder, not a brand.\n"
    "Output STRICT JSON only: {\"reply\": \"<the suggested reply>\"}."
)


def draft_reply_suggestion(author: str, post_text: str, keyword: str) -> str | None:
    """Draft ONE suggested reply to an external Bluesky post (Task: reply digest).

    This is suggestion-only output for a human-in-the-loop Slack digest; the
    pipeline never posts replies automatically.
    """
    user = (
        f"Post by @{author} (matched niche keyword '{keyword}'):\n"
        f"\"{post_text[:500]}\"\n\n"
        "Draft the suggested reply now. Output the JSON object only."
    )
    raw = sarah_generation.generate_with_provider_chain(
        _REPLY_SUGGESTION_SYSTEM,
        user,
        max_output_tokens=160,
    )
    if not raw:
        return None
    data = _parse_json_loose(raw)
    text = str(data.get("reply", "")).strip() if data else raw.strip().strip('"').strip()
    return text[:300] if len(text) >= 15 else None


def tiffany_write_article(
    title: str,
    source: str,
    link: str,
    status: str,
    score: int,
    reason: str,
    proposed_post: str,
    summary: str,
    created_at: str,
) -> str | None:
    user = _USER_PROMPTS["tiffany_article"].format(
        title=title[:180],
        source=source[:120],
        link=link[:500],
        reason=reason[:500],
        proposed_post=proposed_post[:400],
        summary=summary[:1200],
    )
    return _call_gemini(
        _SYSTEM_PROMPTS["tiffany"],
        user,
        model_override=os.getenv("BOARDWIRE_TIFFANY_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
        fallback_model=None,
        max_output_tokens=1600,
        enable_thinking=False,
        stage="tiffany_article",
    )
