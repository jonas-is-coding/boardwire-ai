# Boardwire AI

Boardwire AI is a CLI-first MVP for an autonomous AI news channel with safe defaults.

## LLM providers

Supported providers:
- `none` (default fallback)
- `openai`
- `gemini`

Gemini is the recommended low-cost/free provider for manual LLM collection.

Codex is used for development assistance only, not for runtime automation.

### Env vars

```bash
BOARDWIRE_LLM_PROVIDER=none
BOARDWIRE_LLM_MODEL=gpt-5-mini
BOARDWIRE_GEMINI_MODEL=gemini-2.5-flash
BOARDWIRE_MAX_LLM_ITEMS=3
BOARDWIRE_MAX_POSTS_PER_DAY=3
OPENAI_API_KEY=
GEMINI_API_KEY=
```

If key/provider/network is unavailable, Boardwire falls back to rule-based evaluation.

## Core safety

- LLM is optional and capped by `BOARDWIRE_MAX_LLM_ITEMS`.
- Only compact item fields are sent to LLM (title/source/link/published_at/short summary).
- Max approved posts per day is enforced by `BOARDWIRE_MAX_POSTS_PER_DAY`.
- Publisher defaults to `dry_run`.

## GitHub Actions automation

- `Boardwire Collect` (hourly): safe rule-based collection only
  - command: `python -m src.main --limit 5 --review --llm-provider none`

- `Boardwire Collect with LLM` (manual): recommended Gemini settings
  - `limit`: `8`
  - `max_llm_items`: `3`
  - `max_posts_per_day`: `3`
  - `llm_provider`: `gemini`

- `Boardwire Publish Dry Run` (manual)
- `Boardwire Publish Bluesky` (manual + production environment protection)

## Local commands

Rule-based review run:
```bash
python -m src.main --use-fixtures --limit 8 --llm-provider none --review --quality-report
```

Gemini review run:
```bash
python -m src.main --use-fixtures --limit 8 --llm-provider gemini --review --quality-report
```

Optional overrides:
```bash
python -m src.main --use-fixtures --limit 8 --llm-provider gemini --max-llm-items 3 --max-posts-per-day 3 --review --quality-report
```

## GitHub Secrets

For Gemini LLM collection:
- `GEMINI_API_KEY`

Optional for OpenAI provider:
- `OPENAI_API_KEY`

For real Bluesky publishing:
- `BLUESKY_HANDLE`
- `BLUESKY_APP_PASSWORD`
