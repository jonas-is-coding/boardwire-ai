# Boardwire AI

Boardwire AI is a CLI-first MVP for an autonomous AI news channel with safe defaults.

## Deferred queue prioritization

When daily cap blocks strong candidates, Boardwire stores them as `deferred_due_to_cap` instead of losing them.

Next runs automatically:
- load deferred items first,
- prioritize deferred items by score (highest first),
- process fresh unseen RSS items after deferred items.

This prevents strong stories from being dropped during high-volume periods.

### Deferred fields

Deferred items store:
- `deferred_at`
- `defer_count`
- `original_score`
- `original_reason`

### Retry and expiry

`config/quality.json` includes:
- `max_defer_count` (default `3`)

If `defer_count` exceeds the limit, item status becomes `expired_deferred` and it is skipped permanently.

## Commands

List deferred items:
```bash
python -m src.main --list-deferred
```

Run normal review flow:
```bash
python -m src.main --limit 8 --llm-provider none --review --quality-report
```

Generate markdown queue report:
```bash
python -m src.main --generate-review-report
```

## Review report

Boardwire maintains:
- `reports/review_queue.md`

It contains `pending_review` items only (newest first) with approve/reject commands.

## LLM providers

Supported providers:
- `none` (default fallback)
- `openai`
- `gemini`

Gemini is the recommended low-cost/free provider for manual LLM collection.

Codex is used for development assistance only, not for runtime automation.
