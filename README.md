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

## Newsroom: deep multi-source research (experimental)

Instead of "one source → one post", the newsroom works like a real agency: a
**news desk** picks story leads from clusters (assigning a *beat* and *angle*),
and a **reporter** researches each lead in depth — reading the **full text** of
every source in the cluster (not just the RSS summary), optionally searching the
web for background, and synthesising a structured **research dossier** (facts,
checkable claims with a support level, numbers, quotes, open questions). A
persistent **story memory** (`data/stories.json`) tracks running storylines so
developments can be framed as follow-ups.

This is fully opt-in and runs alongside — never instead of — the existing
pipeline. Without `BOARDWIRE_ENABLE_NEWSROOM`, nothing changes.

Run it:
```bash
BOARDWIRE_ENABLE_NEWSROOM=true python -m src.main --newsroom-research --llm-provider gemini
```

Dossiers are written to `data/dossiers/<lead_id>.json`. With no LLM configured
the reporter still produces an extractive dossier from the fetched text.

Config (`.env`):

| Variable | Default | Purpose |
|---|---|---|
| `BOARDWIRE_ENABLE_NEWSROOM` | `false` | Master switch for the newsroom pipeline |
| `BOARDWIRE_NEWSROOM_MAX_STORIES` | `2` | How many top leads to research per run (budget guard) |
| `BOARDWIRE_NEWSROOM_FETCH_FULLTEXT` | `true` | Download & read article bodies |
| `BOARDWIRE_NEWSROOM_MAX_FETCH` | `5` | Max source fetches per story |
| `BOARDWIRE_NEWSROOM_FETCH_CHARS` | `8000` | Per-article text cap |
| `BOARDWIRE_NEWSROOM_WEB_SEARCH` | `false` | Allow web search for background |
| `BOARDWIRE_NEWSROOM_WEB_RESULTS` | `4` | Web results per story when enabled |
| `BOARDWIRE_WEB_SEARCH_PROVIDER` | `none` | `none` or `gemini` (Google-Search grounding) |

> Roadmap: fact-check gate, multi-format editor (short post / long article /
> thread) and follow-up framing build on the dossier produced here.

## Publishing platforms

Boardwire publishes via pluggable backends selected with `BOARDWIRE_PUBLISHER`
(or `--publisher`). Real publishing additionally requires
`BOARDWIRE_REAL_PUBLISH_ENABLED=true` and the `--confirm-real-publish` flag.

| Publisher | Cost | Image | Credentials (`.env`) |
|---|---|---|---|
| `dry_run` | — | — | none (default) |
| `bluesky` | free | required | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` |
| `mastodon` | free | optional | `MASTODON_API_BASE_URL`, `MASTODON_ACCESS_TOKEN` |
| `instagram` | free API | required | `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_IMAGE_BASE_URL` |
| `threads` | free API | optional | `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN`, (`THREADS_IMAGE_BASE_URL`) |

Notes:
- Instagram and Threads fetch the card by URL (the Graph API does not accept a
  binary upload), so `*_IMAGE_BASE_URL` must point at where `generated/cards/`
  is served publicly. For Instagram this is mandatory; for Threads it is optional
  (text-only posts otherwise).
- Instagram requires a Business/Creator account linked to a Facebook Page, and
  both Instagram and Threads require Meta app review before posting to production.

Example:
```bash
BOARDWIRE_PUBLISHER=mastodon BOARDWIRE_REAL_PUBLISH_ENABLED=true \
  python -m src.main --publish-approved --confirm-real-publish
```

## Markdown-Webartikel Export

Boardwire kann Review-Items als komplette Markdown-Artikel exportieren, damit `boardwire-web` sie direkt lesen/rendern kann. Die Artikel werden von der Persona **Tiffany** (Senior Features Writer) als echte, konstruktiv-journalistische Langform geschrieben (500–900 Wörter).

Output path:
- `articles/*.md`

Command:
```bash
python -m src.main --export-web-articles
```

Exportiert Items mit Status `pending_review`, `approved` und `published_dry_run`.

### Dossier-gestützte Artikel (empfohlen)

Wenn vorher die Newsroom-Deep-Research lief (`--newsroom-research`, siehe oben),
liegen **Dossiers** in `data/dossiers/`. Der Export verknüpft jedes Review-Item
über seinen Quell-Link automatisch mit dem passenden Dossier und schreibt den
Artikel dann aus **verifizierten Fakten, Zahlen, Zitaten, Hintergrund und
Claims mit Support-Level** statt aus der dünnen RSS-Zusammenfassung — sowohl im
LLM-Pfad (Tiffany) als auch im LLM-freien Fallback. Empfohlener Ablauf:

```bash
BOARDWIRE_ENABLE_NEWSROOM=true python -m src.main --newsroom-research --llm-provider gemini
python -m src.main --export-web-articles
```

### Front matter

Jeder Artikel trägt publizierbares Front matter für die Website: `title`, `date`,
`source`, `source_url`, `description` (SEO/Social-Preview), `beat`, `reading_time`
und einen `hero_image`-Slot. Liegt ein Dossier vor, kommen `verified` (sind die
Kernclaims mehrquellen-bestätigt?) und eine strukturierte `sources`-Liste dazu.

### Config (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `BOARDWIRE_TIFFANY_MODEL` | `gemini-2.5-flash` | Modell für die Langform-Artikel. Für hochwertigere Leitartikel auf ein stärkeres Modell zeigen lassen. |
| `BOARDWIRE_TIFFANY_CALL_BUDGET` | `3` | Wie viele Artikel pro Lauf via LLM geschrieben werden (Rest nutzt den dossier-gestützten Fallback). |

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

## Staying current & breaking-news burst

Boardwire collects every 2 hours (`collect-llm.yml`) and publishes every 2 hours
(`publish-bluesky.yml`, offset by ~1h), so a fast-developing story is picked up
and posted within hours instead of waiting for one of a few daily slots.

Routine output is still bounded by `BOARDWIRE_MAX_POSTS_PER_DAY` (default 3) to
keep the feed from turning into release-notes spam. But a **breaking** item is
allowed to exceed that cap:

- **What counts as breaking:** score ≥ `BOARDWIRE_BREAKING_SCORE_THRESHOLD`
  **and** (unless `BOARDWIRE_BREAKING_REQUIRE_CORROBORATION=false`) the story is
  corroborated — reported by more than one source in its cluster, or carrying
  community engagement ≥ `BOARDWIRE_BREAKING_MIN_ENGAGEMENT`.
- **Separate budget:** breaking items draw from `BOARDWIRE_BREAKING_MAX_EXTRA_PER_DAY`
  (default 3) *on top of* the normal daily cap, so a big day can post up to 6.
- **No early stop:** once the normal cap is hit the pipeline keeps running in
  breaking-only mode instead of short-circuiting, so a late-breaking story still
  gets evaluated.
- **Follow-ups aren't duplicates:** breaking items bypass the near-duplicate
  gate, so a development of an ongoing story (e.g. a model release followed by a
  suspension) isn't suppressed as a repeat of the original post.
- **Fast lane on publish:** the publish loop prefers breaking items, then newest,
  and a breaking item can trigger up to `BOARDWIRE_BREAKING_MAX_EXTRA_PER_RUN`
  extra posts within a single run.

Approved breaking items are flagged with `breaking: true` in
`data/review_queue.json` / `data/published_posts.json` and logged as `[BREAKING]`.

Config (`.env`):

| Variable | Default | Purpose |
|---|---|---|
| `BOARDWIRE_BREAKING_ENABLED` | `true` | Master switch for the breaking-news burst |
| `BOARDWIRE_BREAKING_SCORE_THRESHOLD` | `92` | Min score to qualify as breaking |
| `BOARDWIRE_BREAKING_MAX_EXTRA_PER_DAY` | `3` | Extra posts/day allowed beyond the normal cap |
| `BOARDWIRE_BREAKING_MAX_EXTRA_PER_RUN` | `2` | Extra publishes allowed within one publish run |
| `BOARDWIRE_BREAKING_REQUIRE_CORROBORATION` | `true` | Require multi-source / high engagement |
| `BOARDWIRE_BREAKING_MIN_ENGAGEMENT` | `100` | Engagement that counts as corroboration |

## Virality model: learning from comparable channels

Boardwire trains a small local model (`data/virality_model.json`) on the
engagement its own posts collect, used as a ranking signal for candidates. Early
on we have too few posts for this to learn anything useful (cold start).

To fix that, training can **also learn from larger comparable channels** in our
niche — fully opt-in. Their public posts are fetched via the same no-auth
Bluesky AppView the engagement collector already uses
(`app.bsky.feed.getAuthorFeed`), so no extra credentials are needed.

The key trick: a big channel naturally gets more likes than we do, so training
on raw counts would just teach "have more followers". Instead each account's
engagement is turned into a **per-account z-score** — *how well a post did for
that channel* — which is exactly the relative signal a ranking model needs. Our
own posts are additionally up-weighted (`OWN_WEIGHT`) so the model stays anchored
on our voice.

Enable it by listing handles in `.env`:

```bash
BOARDWIRE_VIRALITY_REFERENCE_HANDLES=handle1.bsky.social,handle2.bsky.social
python -m src.main --train-virality-model
```

Config (`.env`):

| Variable | Default | Purpose |
|---|---|---|
| `BOARDWIRE_VIRALITY_REFERENCE_HANDLES` | _(empty)_ | Comma-separated reference handles. Empty = train on our posts only (unchanged). |
| `BOARDWIRE_VIRALITY_REFERENCE_MAX_POSTS` | `100` | Max posts pulled per handle |
| `BOARDWIRE_VIRALITY_REFERENCE_MIN_POSTS` | `5` | Min mature posts an account needs before its posts are used |
| `BOARDWIRE_VIRALITY_OWN_WEIGHT` | `3.0` | Training weight for our posts vs. reference posts |

Pick channels in the **same topic area** as us — the model learns from their
content, so off-topic accounts would pull it in the wrong direction.

## Constructive editorial line (Good-News pivot)

Boardwire's editorial direction is constructive journalism: prioritise GOOD,
solution-oriented information and push doom, outrage and clickbait down — without
ever sacrificing truth.

When constructive mode is ON, the local newsworthiness ranking folds in a
constructive signal: items about progress, recovery and working solutions get
lifted, while overwhelmingly negative or clickbait items get buried. The signal
is keyword-heuristic and fully tunable in `config/editorial.json` (term lists,
weights, thresholds) — no code change needed.

Master switch (`.env`):

| Variable | Default | Purpose |
|---|---|---|
| `BOARDWIRE_CONSTRUCTIVE_MODE` | _(unset → config)_ | `true`/`false`. Overrides `constructive_mode` in `config/editorial.json`. Both default off; turn on once Good-News sources are in place. |

The scoring layer (`src/editorial/constructive.py`) exposes
`constructiveness_score()`, `is_doomscroll()` and `adjust_newsworthiness()` and
is unit-tested independently of the pipeline.

### Activating the Good-News pivot

The pivot is staged so the live pipeline stays stable until you flip it. Good-News
sources are present in `config/sources.json` but `enabled: false`, the constructive
LLM board and ranking are gated, and `constructive_mode` defaults off. To go live:

1. Set `BOARDWIRE_CONSTRUCTIVE_MODE=true` (or `constructive_mode: true` in `config/editorial.json`).
2. Enable the good-news sources (`"lens": "good_news"`) in `config/sources.json`, and disable the AI/builder sources you no longer want.

With the switch on, the editorial board, the ranking and the local newsworthiness
score all use the constructive line; with it off, behaviour is unchanged.

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
