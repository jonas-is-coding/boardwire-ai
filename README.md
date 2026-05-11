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

For real X publishing:
- `X_CONSUMER_KEY`
- `X_CONSUMER_KEY_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

## Publish behavior

- `--publish-approved` now sends a short caption + hashtags.
- If `card_path` exists on the review item, the card image is attached on publish.
- `dry_run` stays the safe default publisher.
- Supported publishers: `dry_run`, `bluesky`, `x`.
- Experimental local publisher: `x_browser` (local only).

## X setup

- Create an app in the X Developer Portal.
- App permissions must be `Read and Write`.
- Use an app type suited for automation (Web App / Automated App / Bot).
- After enabling write access, generate OAuth 1.0a Access Token + Access Token Secret.
- Boardwire uses OAuth 1.0a for X publishing via Tweepy.
- Safety gates for real X posting:
  - `BOARDWIRE_REAL_PUBLISH_ENABLED=true`
  - `--confirm-real-publish`
  - all 4 OAuth env vars present

Current X media behavior:
- Text posting is enabled.
- If `image_path` exists, Boardwire logs: `X media upload not enabled yet, posting text-only`.

## Experimental: local X browser publisher

`x_browser` is an experimental local-only fallback when X API credits are unavailable.

- Recommended production path remains official X API (`--publisher x`).
- Must run locally; it is refused in GitHub Actions.
- Uses a persistent local profile at `.browser/x-profile`.
- First run: browser opens and you log in manually (including any captcha/2FA/security steps).
- No anti-detection tricks, no proxying, no bypass behavior.
- Default behavior prepares the post and waits for manual confirmation.
- Auto-clicking Post is disabled by default.

Required safety flags/env:
- `BOARDWIRE_REAL_PUBLISH_ENABLED=true`
- `BOARDWIRE_ALLOW_BROWSER_PUBLISH=true`
- `--confirm-real-publish`

Optional:
- `BOARDWIRE_BROWSER_AUTO_CLICK_POST=true` enables automatic click of Post.

Local command example:
```bash
BOARDWIRE_REAL_PUBLISH_ENABLED=true \
BOARDWIRE_ALLOW_BROWSER_PUBLISH=true \
python -m src.main --publish-approved --publisher x_browser --confirm-real-publish
```
