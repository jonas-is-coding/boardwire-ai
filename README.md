# Boardwire AI

Boardwire AI is a CLI-first MVP for an autonomous AI news channel with safe defaults.

## Branded image cards

Boardwire can generate square editorial image cards for review/publish flows.

Output path:
- `generated/cards/<review_id>.png`

Card style:
- 1200x1200
- black/white
- minimal editorial layout
- no external assets

### Setup (one-time)

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### Commands

Generate one card by review item ID:
```bash
python -m src.main --generate-card <ID>
```

Generate cards for all `pending_review` + `approved` items without `card_path`:
```bash
python -m src.main --generate-cards
```

Regenerate cards for all `pending_review` + `approved` items even when `card_path` already exists:
```bash
python -m src.main --regenerate-cards
```

Cards are generated from `data/review_queue.json` and saved back via `card_path`.

## Markdown-Webartikel Export

Boardwire kann Review-Items als komplette Markdown-Artikel exportieren, damit `boardwire-web` sie direkt lesen/rendern kann.

Output path:
- `articles/*.md`

Command:
```bash
python -m src.main --export-web-articles
```

Exportiert Items mit Status `pending_review`, `approved` und `published_dry_run`.

## Dev-only testing commands

These commands are for local development/testing only.

Create a synthetic pending review item from fixtures:
```bash
python -m src.main --use-fixtures --create-test-review-item
```

Ignore daily cap in a local run:
```bash
python -m src.main --use-fixtures --limit 8 --review --ignore-daily-cap
```

Notes:
- `--ignore-daily-cap` logs `Daily cap ignored for this run`
- `--ignore-daily-cap` is blocked in scheduled GitHub workflows

## Review report

Boardwire maintains:
- `reports/review_queue.md`

It contains pending items only (newest first) and approve/reject commands.

## Deferred queue prioritization

When daily cap blocks strong candidates, Boardwire stores them as `deferred_due_to_cap`.
Deferred items are prioritized before fresh RSS items on the next run.

## LLM providers

Supported providers:
- `none`
- `openai`
- `gemini`

Gemini is recommended for low-cost/manual LLM collection.

## GitHub Secrets

For Gemini:
- `GEMINI_API_KEY`

Optional for OpenAI:
- `OPENAI_API_KEY`

For real Bluesky publishing:
- `BLUESKY_HANDLE`
- `BLUESKY_APP_PASSWORD`

## Publish behavior

- `--publish-approved` now sends a short caption + hashtags.
- If `card_path` exists on the review item, the card image is attached on publish.
- `dry_run` stays the safe default publisher.
- Supported publishers: `dry_run`, `bluesky`.
