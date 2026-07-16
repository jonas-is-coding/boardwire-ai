# Boardwire AI

Boardwire AI is a CLI-first MVP for an autonomous AI news channel with safe defaults.

## Branded image cards

Boardwire generates square editorial image cards for review/publish flows. The
card must **add** information — never repeat the post hook.

Output path:
- `generated/cards/<review_id>.png`

Brand system (all templates):
- 1200x1200, background `#0a0a0a`, white type, accent `#FFD21E`
- monospace source kicker with an accent dot (top)
- `BOARDWIRE` wordmark bottom-left (accent, letter-spaced) + date bottom-right
- optional light `visual_theme`
- no external assets; ALT text is always generated from the card content

### Card fields (Sarah package)

The packaging LLM emits three card-specific fields, validated in Python
(`src/cards/card_data.py`) — never truncated on the card:

| Field | Budget | Rule |
|---|---|---|
| `card_stat` | ≤ 8 chars | The one hero number/token (`70B`, `+607★`, `104 pts`, `1-bit`, `RCE`). Empty if the story has no number. |
| `card_claim` | ≤ 8 words | The sharp takeaway. Rejected if it shares > 60% of its tokens with the post title (falls back to a distinct source line). |
| `card_context` | ≤ 90 chars | One complete sentence or `·`-separated fragments. Over-budget context is rejected and replaced by a complete leading fragment — never a mid-sentence cut. |

### Layout templates

Selected deterministically by content type (`src/cards/html_template.py`):

- **stat** (default when `card_stat` is present): huge hero stat → claim → context.
- **claim** (no stat): claim as display type, capped at 2–3 lines.
- **quote** (HN discussion / opinion sources): oversized accent quotation mark → claim in editorial italic → attribution.

### Card A/B variant

For GitHub-sourced items, a deterministic 50/50 split (by hash of item id)
chooses between the editorial card and the repo's GitHub Open Graph preview
(`opengraph.githubassets.com`, verified to return an image before use; falls
back to the editorial card on any failure). The chosen `card_variant`
(`editorial_stat` | `editorial_claim` | `editorial_quote` | `github_og`) is
persisted in `data/published_posts.json` and reported under
"Engagement by card variant" in `--engagement-report`.

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

## Posting schedule: engagement windows

Under 1,000 followers, 1-2 quality posts/day outperform high volume on Bluesky
(impressions get spread too thin), and the Discover feed rewards early
engagement velocity — most engagement happens in the first 1-2 hours. Boardwire
therefore posts into the proven engagement windows instead of spraying every
2 hours into dead air:

| Slot | UTC (cron) | US Eastern (EDT) | CET (summer) |
|---|---|---|---|
| Weekday morning (Mon-Fri) | 13:30 | 9:30 AM | 15:30 |
| Weekday midday (Mon-Fri) | 17:30 | 1:30 PM | 19:30 |
| Sunday evening spike | 22:00 | 6:00 PM | 00:00 (Mon) |

Collection (`collect-llm.yml`) runs ~1.5h before each publish slot
(`publish-bluesky.yml`): weekdays 12:00 & 16:00 UTC, Sunday 20:30 UTC.

Notes:
- GitHub cron is UTC and can fire up to ~15-30 min late — acceptable, the
  windows are 2 hours wide.
- The crons assume US Eastern **daylight** time (EDT, UTC-4). In US winter
  (EST, UTC-5) shift each cron +1h; there is a reminder comment in both
  workflow files.
- `BOARDWIRE_MAX_POSTS_PER_DAY` defaults to `2` in the workflow; per publish
  run at most one post goes out (`BOARDWIRE_MAX_PUBLISH_PER_RUN=1`).

## Post format

The Bluesky post is composed budget-aware (300 graphemes; budgeted
conservatively in UTF-8 bytes, see `src/composer.py`) — never hard-truncated:

```
<hook line (Sarah title)>

<supporting fact line (Sarah subtitle)>

<optional closing question — ~40% of posts (A/B variant)>

<hashtag line: 2-3 tags>

🔗 <source link (facet, appended by the publisher)>
```

- The link suffix and the hashtag line are reserved **first**; the fact line is
  shortened at a word boundary (clean sentence or ellipsis) when space is
  tight. Priority: link > hashtags > hook > question > fact.
- The Sarah `description` field stays on the image card only — it no longer
  enters the post text.
- The closing question is LLM-drafted per item, validated in code (max ~60
  chars, must end with `?`, no engagement bait) and applied to a deterministic
  ~40% of items (hash of the source link). Published posts record
  `format_variant`, `hashtags_used`, `published_hour_utc` and
  `published_weekday` in `data/published_posts.json` for the A/B analysis in
  the engagement report and the virality model.

### Composed at publish time (single source of truth)

The Bluesky text is **always composed at publish time from the package fields**
(title/subtitle/hashtags/question) — the stored `proposed_post` is an Editor
draft, never published verbatim. Each queue item and published post carries a
`composer_version` (`src/composer.py::COMPOSER_VERSION`) proving it was built by
the current composer; no pre-refactor 3-block text can publish again.

On each publish run, `migrate_review_queue_composition` brings the queue to the
current composer: items with a stored Sarah package are recomposed and stamped;
items whose stored text is detectably old-format with no package to rebuild from
are expired; fresh Editor drafts are left for publish to regenerate.

### Composed-text validation (reject → regenerate once → skip)

After composing, the text is validated (`src/quality/gates.py`) and, on failure,
the package is regenerated **once**; if it still fails the item is skipped
(never published) and the reason is logged to `data/gate_rejections.json`:

- **Aggregator-metadata dumps** — `with N points and M comments` and truncated
  `...35 comm` fragments are blocked. Intentional star counts (`+607 stars`) are
  allowed.
- **Mid-word truncation** — the composed text must end with sentence
  punctuation, `?`, a complete hashtag, or the link.
- **Fact-line groundedness** — the fact line must carry a concrete
  source-traceable token (number, version, license, or artifact name), and the
  `turns X into Y` template is banned unless both nouns appear in the source.

## Hashtags: config-driven, custom-feed targeted

Bluesky discovery runs through custom feeds that match posts by
hashtag/keyword. Tags are selected deterministically in Python from
`config/hashtags.json` — always exactly 1 broad tag + 1-2 specific tags matched
from the item's title/summary/source (`src/hashtags.py`). LLM-suggested tags
are only candidates: anything not in the config is dropped, so invented tags
never reach Bluesky.

## Threads for top stories

Items with score ≥ 92 (the breaking threshold) publish as a 2-3 post
reply-chained thread instead of one crammed post — threads generate ~3x more
replies:

1. Hook + image card + hashtags
2. Strongest concrete facts (newsroom dossier `key_facts` when available, else
   subtitle + description)
3. Source link + optional question

Reply refs (`root`/`parent` with `uri`+`cid`) are chained in
`src/publisher/bluesky_publisher.py::publish_thread`. If post N fails the rest
is aborted and the partial state is recorded (`thread_uris`,
`thread_partial`) so nothing is double-posted. The dry-run publisher simulates
threads too.

## Hard quality gates

Enforced in code (`src/quality/gates.py`), not just asked for in the prompt:

- **Version-only block:** titles like `ollama v0.30.11` are rejected unless the
  summary/dossier names a concrete capability (configurable
  `capability_keywords` in `config/quality.json`: plugin, MCP, sandbox, local,
  weights, API, CLI, benchmark, … or a numeric %/x-factor claim).
- **Release dedupe:** the same (project, version) tuple is never published
  twice within 14 days (ledger: `data/published_releases.json`).
- **Internal-metadata leak:** posts matching `\d+ score|rank` or containing
  internal field names (`source_tier`, `engagement_score`, …) are rejected; the
  Sarah prompt additionally forbids mentioning internal scores.
- Every gate rejection is logged with its reason to
  `data/gate_rejections.json` and rendered in `reports/review_queue.md`.

## Reply digest (human-in-the-loop, no auto-posting)

```bash
python -m src.main --reply-digest
```

Queries the public Bluesky search API (`app.bsky.feed.searchPosts`, no auth)
for recent high-engagement posts matching the niche keywords in
`config/reply_digest.json`, drafts one substantive reply suggestion per post
via the existing LLM chain, and sends the digest to the Slack webhook.

**This tool never posts replies itself** — it only suggests; a human reads the
digest and posts manually. Replies are the strongest visibility signal on
Bluesky, which is exactly why they must stay human.

## Staying current & breaking-news burst

Routine output is bounded by `BOARDWIRE_MAX_POSTS_PER_DAY` (workflow default 2)
to keep the feed from turning into release-notes spam. But a **breaking** item
is allowed to exceed that cap:

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

- `--publish-approved` composes hook + fact + optional question + hashtags,
  with the source link appended by the publisher (see "Post format").
- Items with score ≥ 92 go out as a 2-3 post thread (see "Threads for top stories").
- If `card_path` exists on the review item, the card image is attached on publish.
- `dry_run` stays the safe default publisher; real publishing always requires
  `BOARDWIRE_REAL_PUBLISH_ENABLED=true` **and** `--confirm-real-publish`.
- Supported publishers: `dry_run`, `bluesky`.
- To remove published Bluesky posts from the live account and mark them as deleted in `data/published_posts.json`, run for example:

  ```bash
  python -m src.main --delete-published --publisher bluesky --delete-older-than-hours 1 --confirm-real-delete
  ```

  Add `--delete-limit N` to cap the number of stored post records deleted in one run. Thread replies are deleted in reverse order, and real deletion requires `BOARDWIRE_REAL_PUBLISH_ENABLED=true`, `BLUESKY_HANDLE`, and `BLUESKY_APP_PASSWORD`.

## Engagement report

```bash
python -m src.main --engagement-report
```

`reports/engagement_report.md` answers the strategy questions: engagement by
published hour (UTC) and weekday, by `format_variant` (question vs plain vs
thread), by hashtag combination, and version-release posts vs others (should
trend to n=0 after the version-only gate). Sections with fewer than 5 posts
print `insufficient data (n<5)` instead of misleading averages.
