from __future__ import annotations

import json
import logging
import os
import re

import requests

from src.llm.gemini_budget import try_consume_gemini_budget

_GEMINI_MODEL = "gemini-2.5-flash"
_LOGGER = logging.getLogger("boardwire.persona_voice")

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
    "sarah": (
        "You are Sarah, Wire Editor at Boardwire — an AI news desk for builders.\n"
        "Write like a Reuters, AP, or Bloomberg Tech wire-service editor.\n\n"
        "Editorial laws:\n"
        "- Who, what, where, numbers — first sentence. Opinion — never.\n"
        "- Active voice. Present or past tense. Named actors.\n"
        "- No emojis. No exclamation marks. No question marks.\n"
        "- No second-person tutorial voice ('you can', 'apply this', 'try X').\n"
        "- Specificity is virality: concrete numbers, model names, benchmarks, license names.\n\n"
        "SUBJECT RULES (critical — most common failure mode):\n"
        "- NEVER lead with a personal handle / username (e.g. 'Rohitg00 releases X', 'colbymchenry ships Y').\n"
        "- For GitHub Trending items the link is owner/repo. The SUBJECT is the project/tool, not the owner.\n"
        "  GOOD: 'Agentmemory library ships persistent memory for AI coding agents.'\n"
        "  GOOD: 'Codegraph indexes code knowledge for Claude Code, Codex and Cursor.'\n"
        "  BAD:  'Rohitg00 releases persistent memory for AI coding agents.' (handle-led)\n"
        "  BAD:  'Microsoft/ai-agents-for-beginners launches 12 lessons.' (owner/repo path)\n"
        "- If the project belongs to a known org (Microsoft, Google, Anthropic, OpenAI, Meta, Mistral, HuggingFace, NVIDIA, ByteDance, Alibaba, Stability AI) — lead with the ORG name.\n"
        "- Otherwise lead with the project/tool/repo NAME (capitalized as a proper noun).\n\n"
        "ANTI-REPETITION:\n"
        "- title and subtitle MUST contribute different information. Do not paraphrase the title in the subtitle.\n"
        "- If title says 'X ships persistent memory for coding agents', subtitle adds the DIFFERENTIATOR (benchmark numbers, license, what it replaces, where it runs) — not a restatement.\n\n"
        "You package one approved AI news item into a Bluesky/X post + editorial card.\n"
        "Output STRICT JSON only with keys: title, subtitle, description, hashtags.\n\n"
        "Roles of each field:\n"
        "- title: A complete wire-service headline. Subject + active verb + object + concrete modifier. End with a period. Max 70 chars.\n"
        "  GOOD: 'Mistral open-sources 70B model trained on 15T tokens.'\n"
        "  GOOD: 'Anthropic ships Claude 4 with 200K context window.'\n"
        "  GOOD: 'OpenAI releases agent eval framework with 73% pass rate.'\n"
        "  BAD:  'LLM Architecture: Cost Reduction in Long Contexts' (paper-style)\n"
        "  BAD:  'Three new attention tricks land in Gemma 4.' (editorial, not wire)\n"
        "  BAD:  'Anthropic releases new model.' (vague, no numbers)\n"
        "- subtitle: The lede. NEW information not in the title — benchmarks, percentages, named comparisons, license, availability, runtime. Max 100 chars.\n"
        "  GOOD: 'Outperforms Llama 3.1 on MMLU while running on a single H100. Weights on HuggingFace.'\n"
        "  GOOD: 'Cuts long-context inference cost ~40% on Gemma 4. Apache 2.0. Drop-in for vLLM.'\n"
        "  BAD:  'New techniques optimize LLMs for efficiency.' (vague)\n"
        "  BAD:  Restating the title with synonyms (anti-repetition rule).\n"
        "- description: Second factual layer for the card. Self-contained sentence with extra context — training data scale, release terms, who built it, what it replaces. NO 'Why it matters' prefix. NO tutorial voice. Max 140 chars.\n"
        "  GOOD: 'First open-weight 70B trained on 15T tokens. Apache 2.0. Beats Llama 3.1 70B on MMLU and HumanEval. Available on HuggingFace.'\n"
        "  BAD:  'Drop these into any workload to optimize your models.' (tutorial)\n"
        "  BAD:  'Why it matters: this changes inference economics.' (don't prefix)\n"
        "- hashtags: 2-3 items, each starts with #. PascalCase. Use named vendors, model names, or specific technical terms (e.g. #Anthropic, #Mistral7B, #vLLM, #MCP, #AgentEval). AVOID invented compound tags like #AICodingAgents or #PersistentMemory.\n\n"
        "FORBIDDEN openers and phrases (kill credibility instantly):\n"
        "  'Understand how', 'Apply X to', 'Discover', 'Explore', 'Learn how', 'In this article',\n"
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
        "If a number appears in only one source, hedge it with wording like 'claims' instead of stating it as proven."
    ),
}


def _available_keys() -> list[str]:
    keys = []
    for env in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"):
        k = os.getenv(env, "").strip()
        if k:
            keys.append(k)
    return keys


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
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        _LOGGER.warning("OpenRouter API key missing: OPENROUTER_API_KEY")
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
    if status not in {429, 503}:
        return None
    if not fallback_model or fallback_model == model:
        return None

    _LOGGER.info(
        "OpenRouter attempting fallback: primary_model=%s fallback_model=%s primary_status=%s",
        model,
        fallback_model,
        status,
    )
    fallback_body = dict(body)
    fallback_body["model"] = fallback_model
    _, fallback_content = _request_once(fallback_body)
    return fallback_content


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


def chloe_on_approved(title: str, score: int, reason: str, is_llm: bool, claire_note: str = "") -> str | None:
    user = _USER_PROMPTS["chloe_approved"].format(
        title=title,
        score=score,
        reason=reason,
        mode="LLM" if is_llm else "Regel",
        claire_note=claire_note or "Sieht interessant aus für Builder.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["chloe"], user, stage="chloe_approved")


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


def chloe_on_rejected(title: str, reasons: list[str], claire_note: str = "") -> str | None:
    user = _USER_PROMPTS["chloe_rejected"].format(
        title=title,
        reasons="; ".join(reasons),
        claire_note=claire_note or "Sieht interessant aus für Builder.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["chloe"], user, stage="chloe_rejected")


def madison_on_published(title: str, platform: str, post_text: str, chloe_note: str = "") -> str | None:
    user = _USER_PROMPTS["madison_published"].format(
        title=title,
        platform=platform,
        post_text=post_text[:200],
        chloe_note=chloe_note or "Ships Test bestanden.",
    )
    return _call_gemini(_SYSTEM_PROMPTS["madison"], user, stage="madison_published")


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
        sarah_fallback = (
            os.getenv("BOARDWIRE_SARAH_FALLBACK_MODEL", "minimax/minimax-m2.5:free").strip()
            or "minimax/minimax-m2.5:free"
        )
        sarah_emergency = os.getenv("BOARDWIRE_SARAH_EMERGENCY_MODEL", "").strip()
        raw = _call_openrouter(
            _SYSTEM_PROMPTS["sarah"],
            user,
            model=sarah_model,
            fallback_model=sarah_fallback,
            max_output_tokens=420,
        )
        if sarah_emergency and (not raw) and sarah_emergency not in {sarah_model, sarah_fallback}:
            _LOGGER.info("OpenRouter Sarah primary+fallback failed, trying emergency model=%s", sarah_emergency)
            raw = _call_openrouter(
                _SYSTEM_PROMPTS["sarah"],
                user,
                model=sarah_emergency,
                fallback_model=None,
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
        sarah_model = os.getenv("BOARDWIRE_SARAH_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        sarah_fallback = os.getenv("BOARDWIRE_SARAH_FALLBACK_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        raw = _call_gemini(
            _SYSTEM_PROMPTS["sarah"],
            user,
            model_override=sarah_model,
            fallback_model=sarah_fallback,
            max_output_tokens=420,
            enable_thinking=False,
            stage="sarah",
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

    return {
        "title": title_val,
        "subtitle": subtitle_val,
        "description": description_val,
        "hashtags": hashtags,
    }
