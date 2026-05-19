from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests

from src.llm.prompts import (
    RANKING_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_ranking_user_prompt,
    build_user_prompt,
)
from src.llm.schemas import LLMBoardResult, validate_llm_result
from src.models import FeedItem


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class LLMConfig:
    provider: str
    openai_model: str
    gemini_model: str
    openai_api_key: str | None
    gemini_api_key: str | None
    max_items: int


class OpenAIClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def evaluate_item(self, item: FeedItem) -> LLMBoardResult:
        body = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "input_text", "text": build_user_prompt(item)}]},
            ],
            "text": {"format": {"type": "json_object"}},
        }

        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=20,
        )

        if response.status_code >= 400:
            raise LLMError(f"OpenAI API error {response.status_code}: {response.text[:220]}")

        data = response.json()
        text_output = data.get("output_text", "").strip()
        if not text_output:
            raise LLMError("Model returned empty output")

        try:
            parsed = json.loads(text_output)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Invalid JSON from model: {exc}") from exc

        try:
            return validate_llm_result(parsed)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Invalid schema in model output: {exc}") from exc


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def rank_candidates(self, items: list[FeedItem], top_k: int) -> list[dict]:
        prompt = f"{RANKING_SYSTEM_PROMPT}\n\n{build_ranking_user_prompt(items, top_k)}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            },
        }
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        response = requests.post(url, json=body, timeout=30)
        if response.status_code >= 400:
            raise LLMError(f"Gemini ranking error {response.status_code}: {response.text[:220]}")
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise LLMError("Gemini ranking returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise LLMError("Gemini ranking returned empty content")
        text_output = str(parts[0].get("text", "")).strip()
        if not text_output:
            raise LLMError("Gemini ranking returned empty text")
        try:
            parsed = json.loads(text_output)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Invalid JSON from Gemini ranking: {exc}") from exc
        ranked = parsed.get("ranked")
        if not isinstance(ranked, list):
            raise LLMError("Gemini ranking JSON missing 'ranked' array")
        return ranked

    def evaluate_item(self, item: FeedItem) -> LLMBoardResult:
        prompt = f"{SYSTEM_PROMPT}\n\n{build_user_prompt(item)}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        response = requests.post(url, json=body, timeout=20)
        if response.status_code >= 400:
            raise LLMError(f"Gemini API error {response.status_code}: {response.text[:220]}")

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise LLMError("Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise LLMError("Gemini returned empty content")
        text_output = str(parts[0].get("text", "")).strip()
        if not text_output:
            raise LLMError("Gemini returned empty text")

        try:
            parsed = json.loads(text_output)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Invalid JSON from Gemini: {exc}") from exc

        try:
            return validate_llm_result(parsed)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Invalid schema in Gemini output: {exc}") from exc


def load_llm_config() -> LLMConfig:
    provider = os.getenv("BOARDWIRE_LLM_PROVIDER", "none").strip().lower()
    openai_model = os.getenv("BOARDWIRE_LLM_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    gemini_model = os.getenv("BOARDWIRE_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    openai_api_key = os.getenv("OPENAI_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    try:
        max_items = int(os.getenv("BOARDWIRE_MAX_LLM_ITEMS", "3"))
    except ValueError:
        max_items = 3
    max_items = max(1, max_items)

    return LLMConfig(
        provider=provider,
        openai_model=openai_model,
        gemini_model=gemini_model,
        openai_api_key=openai_api_key,
        gemini_api_key=gemini_api_key,
        max_items=max_items,
    )
