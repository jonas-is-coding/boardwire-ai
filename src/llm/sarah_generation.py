from __future__ import annotations

import logging
import os
import time

import requests

_LOGGER = logging.getLogger("boardwire.sarah_generation")

_PROVIDERS = ("groq", "cerebras", "mistral")
_STATE = {
    "used": {p: 0 for p in _PROVIDERS},
    "exhausted": {p: False for p in _PROVIDERS},
    "attempted_models": [],
}


def reset_state() -> None:
    _STATE["used"] = {p: 0 for p in _PROVIDERS}
    _STATE["exhausted"] = {p: False for p in _PROVIDERS}
    _STATE["attempted_models"] = []


def attempt_cursor() -> int:
    return len(_STATE["attempted_models"])


def attempted_models_since(cursor: int) -> list[str]:
    if cursor < 0:
        cursor = 0
    return list(_STATE["attempted_models"][cursor:])


def runtime_stats() -> dict[str, object]:
    exhausted = [p for p, v in _STATE["exhausted"].items() if v]
    return {
        "groq_used": int(_STATE["used"]["groq"]),
        "cerebras_used": int(_STATE["used"]["cerebras"]),
        "mistral_used": int(_STATE["used"]["mistral"]),
        "exhausted": exhausted,
    }


def _provider_spec(provider: str) -> tuple[str, str, str]:
    if provider == "groq":
        return (
            "GROQ_API_KEY",
            "BOARDWIRE_GROQ_MODEL",
            "llama-3.3-70b-versatile",
        )
    if provider == "cerebras":
        return (
            "CEREBRAS_API_KEY",
            "BOARDWIRE_CEREBRAS_MODEL",
            "qwen-3-32b",
        )
    return (
        "MISTRAL_API_KEY",
        "BOARDWIRE_MISTRAL_MODEL",
        "mistral-small-latest",
    )


def _provider_endpoint(provider: str) -> str:
    if provider == "groq":
        return "https://api.groq.com/openai/v1/chat/completions"
    if provider == "cerebras":
        return "https://api.cerebras.ai/v1/chat/completions"
    return "https://api.mistral.ai/v1/chat/completions"


def _call_provider(provider: str, system: str, user: str, max_output_tokens: int) -> str | None:
    key_env, model_env, model_default = _provider_spec(provider)
    api_key = os.getenv(key_env, "").strip()
    if not api_key:
        _LOGGER.info("Sarah provider skipped: %s missing API key", provider)
        return None
    if _STATE["used"][provider] >= 1 or _STATE["exhausted"][provider]:
        _STATE["exhausted"][provider] = True
        _LOGGER.warning("Sarah provider exhausted: %s", provider)
        return None

    model = os.getenv(model_env, model_default).strip() or model_default
    _STATE["attempted_models"].append(f"{provider}:{model}")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _once() -> tuple[int | None, str | None]:
        _STATE["used"][provider] += 1
        try:
            resp = requests.post(_provider_endpoint(provider), headers=headers, json=body, timeout=20)
        except Exception as exc:
            _LOGGER.warning("Sarah provider request exception: provider=%s type=%s", provider, type(exc).__name__)
            return None, None
        status = int(resp.status_code)
        if status >= 400:
            _LOGGER.warning("Sarah provider request failed: provider=%s model=%s status=%d", provider, model, status)
            return status, None
        try:
            content = str(resp.json()["choices"][0]["message"]["content"]).strip()
        except Exception:
            _LOGGER.warning("Sarah provider parse failed: provider=%s model=%s", provider, model)
            return status, None
        if len(content) < 30:
            _LOGGER.warning("Sarah provider response rejected: provider=%s model=%s reason=too_short", provider, model)
            return status, None
        return status, content

    status, content = _once()
    if content:
        return content
    if status in {429, 401, 403}:
        _STATE["exhausted"][provider] = True
        _LOGGER.warning("Sarah provider exhausted: %s", provider)
        return None
    if status == 503:
        time.sleep(0.35)
        _, retry_content = _once()
        return retry_content
    return None


def generate_with_provider_chain(system: str, user: str, max_output_tokens: int = 420) -> str | None:
    for provider in _PROVIDERS:
        text = _call_provider(provider, system, user, max_output_tokens=max_output_tokens)
        if text:
            return text
    return None
