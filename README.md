# Boardwire AI

Boardwire AI is a CLI-first MVP for an autonomous AI news channel with safe defaults.

## LLM providers

Supported providers:
- `none` (default fallback)
- `openai`
- `gemini`

Gemini is the recommended low-cost/free provider for manual LLM collection.

Codex is used for development assistance only, not for runtime automation.

## Duplicate lookback

Duplicate checks use configurable lookback windows from `config/quality.json`:
- `duplicate_lookback_hours` (normal runs, default `168`)
- `fixture_duplicate_lookback_hours` (fixture runs, default `1`)

This prevents long-lived test data from blocking local fixture/dev runs.

Timestamp behavior:
- normal mode: entries without timestamps are treated as relevant (safer)
- fixture mode: entries without timestamps are treated as old

## Fixture reset

Use fixture reset to clear fixture-linked runtime state:

```bash
python -m src.main --use-fixtures --reset-fixture-state
```

This removes fixture-related entries from:
- `data/seen_items.json`
- `data/drafts.json`
- `data/review_queue.json`

It does **not** modify `data/published_posts.json`.

## Local commands

```bash
python -m src.main --use-fixtures --limit 8 --llm-provider none --review --quality-report
python -m src.main --limit 8 --llm-provider gemini --max-llm-items 3 --max-posts-per-day 3 --review --quality-report
```

## GitHub Secrets

For Gemini LLM collection:
- `GEMINI_API_KEY`

Optional for OpenAI provider:
- `OPENAI_API_KEY`

For real Bluesky publishing:
- `BLUESKY_HANDLE`
- `BLUESKY_APP_PASSWORD`
