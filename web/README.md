# Boardwire Web

Marketing and changelog site for the open-source `boardwire-ai` pipeline

## Workflow shown on the site

The website now documents the new Boardwire pipeline direction:

1. Multi-source collection beyond plain RSS (18 RSS/Atom feeds + HN + GitHub Trending).
2. Reputation tiers (Tier-1/2/3) per source instead of flat scoring.
3. Cross-source corroboration and clustering before final ranking.
4. Story-level ranking (tier weight + recency + engagement).
5. AI-agent communication via Slack before publishing.

## Local embedding note (cost control)

For clustering, the recommended setup is local embeddings on GitHub Actions CPU runners (for example via `fastembed` + `bge-small-en-v1.5`) and only a small number of LLM calls for final editorial ranking. This keeps free-tier API usage low.

## Getting Started

Run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) to view the site.

Main pages:

- `app/page.tsx` - landing page
- `app/_workflow.tsx` - workflow visualization
- `app/changelog/page.tsx` - live commit changelog for `boardwire-ai`

## Data source for changelog

The changelog page fetches commits from:

`https://api.github.com/repos/jonas-is-coding/boardwire-ai/commits`

with incremental revalidation in Next.js.

## Deploy on Vercel

Use the Vercel project connected to this repository and deploy via `vercel deploy` or GitHub integration.
