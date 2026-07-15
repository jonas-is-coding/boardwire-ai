import Image from "next/image";
import Link from "next/link";
import { SiBluesky, SiGithub } from "react-icons/si";
import styles from "./page.module.css";
import Workflow from "./_workflow";

const stats = [
  { value: "20", label: "active sources" },
  { value: "3", label: "reputation tiers" },
  { value: "local", label: "embeddings" },
  { value: "2", label: "LLM passes" },
  { value: "2/day", label: "publish cap" },
];

const trustBadges = [
  "dry-run default",
  "daily cap",
  "release dedupe",
  "hard quality gates",
  "review queue",
  "source tiers",
  "engagement windows",
];

const runMetrics = [
  { label: "Last run", value: "~15 min ago" },
  { label: "New candidates", value: "40-70" },
  { label: "Story clusters", value: "12-20" },
  { label: "Published today", value: "0-2" },
];

const sourceRows = [
  { name: "OpenAI News", tier: "T1" },
  { name: "Google DeepMind Blog", tier: "T1" },
  { name: "Claude Code Releases", tier: "T1" },
  { name: "Anthropic Python SDK Releases", tier: "T1" },
  { name: "MCP Spec Releases", tier: "T1" },
  { name: "Hugging Face Blog", tier: "T2" },
  { name: "GitHub Blog AI", tier: "T2" },
  { name: "Simon Willison", tier: "T2" },
  { name: "Import AI (Jack Clark)", tier: "T2" },
  { name: "SemiAnalysis", tier: "T2" },
  { name: "Nathan Lambert (Interconnects)", tier: "T2" },
  { name: "Sebastian Raschka (Ahead of AI)", tier: "T2" },
  { name: "MCP Servers Releases", tier: "T2" },
  { name: "Ollama Releases", tier: "T2" },
  { name: "vLLM Releases", tier: "T2" },
  { name: "LlamaIndex Releases", tier: "T2" },
  { name: "LangChain Releases", tier: "T2" },
  { name: "The Gradient", tier: "T3" },
];

const pillars = [
  {
    no: "01",
    title: "Cross-source truth over single-link hype",
    body: "Boardwire does not rank links in isolation anymore. It groups overlapping reports across 18 RSS/Atom feeds, Hacker News, and GitHub Trending and promotes stories corroborated by multiple independent signals.",
    meta: "corroboration · clustering · story score",
  },
  {
    no: "02",
    title: "Reputation-aware ranking",
    body: "Every source is weighted by tier (Tier-1, Tier-2, Tier-3), then combined with recency and engagement. That means DeepMind/OpenAI updates are contextualized differently than random long-tail posts.",
    meta: "tier weights · engagement · recency",
  },
  {
    no: "03",
    title: "Cheap compute, strict editorial gate",
    body: "Embeddings run locally on GitHub Actions CPU runners to avoid burning API quota. LLM calls stay focused on final editorial choices before a reviewed publish step.",
    meta: "local embeddings · batch LLM · review gate",
  },
];

const principles = [
  "No isolated links without cross-source context.",
  "One story, one implication, one actionable takeaway.",
  "Review before publish. Always.",
];

export default function Home() {
  return (
    <>
      <header className={styles.nav}>
        <div className={styles.navInner}>
          <div className={styles.brandCluster}>
            <Link href="/" className={styles.brand} aria-label="Boardwire home">
              <span className={styles.brandLogo}>
                <Image
                  src="/logo.png"
                  alt=""
                  width={26}
                  height={26}
                  priority
                />
              </span>
              <span className={styles.brandName}>Boardwire</span>
            </Link>
            <Link href="/changelog" className={styles.brandTag}>
              v0
            </Link>
          </div>
          <nav className={styles.navLinks} aria-label="Primary">
            <a href="#pipeline">Pipeline</a>
            <a href="#sources">Sources</a>
            <a href="#principles">Principles</a>
          </nav>
          <div className={styles.socialLinks} aria-label="External links">
            <a
              href="https://github.com/jonas-is-coding/boardwire-ai"
              className={styles.socialIcon}
              target="_blank"
              rel="noreferrer"
              aria-label="Boardwire on GitHub"
            >
              <SiGithub size={20} />
            </a>
            <a
              href="https://bsky.app/profile/boardwire.bsky.social"
              className={styles.socialIcon}
              target="_blank"
              rel="noreferrer"
              aria-label="Boardwire on Bluesky"
            >
              <SiBluesky size={20} />
            </a>
          </div>
        </div>
      </header>

      <main>
        <section className={`${styles.container} ${styles.hero}`}>
          <div className={styles.heroContent}>
            <p className={styles.eyebrow}>
              <span className={styles.eyebrowDot} aria-hidden />
              LIVE · AUTONOMOUS · BUILDER-FIRST
            </p>
            <h1 className={styles.heroTitle}>
              Signals over noise<span className={styles.period}>.</span>
            </h1>
            <p className={styles.heroSub}>
              20 active sources in, clustered stories out, up to 2 quality posts
              per day — timed into Bluesky&apos;s engagement windows. Boardwire
              runs as an autonomous AI newsroom with strict quality constraints.
            </p>
            <div className={styles.heroCta}>
              <a href="#pipeline" className={styles.btnPrimary}>
                See the pipeline
              </a>
              <a href="#today" className={styles.btnGhost}>
                See today&apos;s run →
              </a>
            </div>
            <div className={styles.heroStatBar}>
              {stats.map((s) => (
                <div key={s.label} className={styles.heroStatItem}>
                  <span className={styles.statValue}>{s.value}</span>
                  <span className={styles.statLabel}>{s.label}</span>
                </div>
              ))}
            </div>
            <div className={styles.trustStrip}>
              {trustBadges.map((badge) => (
                <span key={badge} className={styles.trustBadge}>{badge}</span>
              ))}
            </div>
          </div>
        </section>

        <section id="today" className={`${styles.container} ${styles.section}`}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.sectionLabel}>TODAY&apos;S RUN</p>
              <h2 className={styles.sectionTitle}>Live operational snapshot.</h2>
            </div>
            <p className={styles.sectionSub}>
              Quick health view of the collection and editorial loop. Numbers are
              intentionally compact and operator-focused.
            </p>
          </div>
          <div className={styles.runGrid}>
            {runMetrics.map((metric) => (
              <article key={metric.label} className={styles.runCard}>
                <span className={styles.runValue}>{metric.value}</span>
                <span className={styles.runLabel}>{metric.label}</span>
              </article>
            ))}
          </div>
        </section>

        <section
          id="pipeline"
          className={`${styles.container} ${styles.flowSection}`}
        >
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.sectionLabel}>PIPELINE</p>
              <h2 className={styles.sectionTitle}>
                The full workflow, live.
              </h2>
            </div>
            <p className={styles.sectionSub}>
              From raw firehose to approved publish artifact: source expansion,
              reputation tiers, local embedding-based clustering, story ranking,
              then a reviewed publish handoff.
            </p>
          </div>
          <Workflow />
        </section>

        <section id="sources" className={`${styles.container} ${styles.section}`}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.sectionLabel}>SOURCE TIERS</p>
              <h2 className={styles.sectionTitle}>Transparent input surface.</h2>
            </div>
            <p className={styles.sectionSub}>
              Core active inputs, grouped with tier context. Ranking uses these
              tiers as weighting signals before publish. Hacker News and GitHub
              Trending are collected as separate aggregator streams.
            </p>
          </div>
          <div className={styles.sourceGrid}>
            {sourceRows.map((source) => (
              <article key={source.name} className={styles.sourceCard}>
                <span className={styles.sourceName}>{source.name}</span>
                <span
                  className={`${styles.sourceTier} ${source.tier === "T1" ? styles.tier1 : source.tier === "T2" ? styles.tier2 : styles.tier3}`}
                >
                  {source.tier}
                </span>
              </article>
            ))}
          </div>
        </section>

        <section
          id="product"
          className={`${styles.container} ${styles.section}`}
        >
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.sectionLabel}>WHAT IT IS</p>
              <h2 className={styles.sectionTitle}>An editor that ships.</h2>
            </div>
            <p className={styles.sectionSub}>
              Boardwire is a fully automated editorial pipeline that behaves
              like a small newsroom. It compares competing narratives across
              sources before a post is selected, then ships only what survives
              ranking and review.
            </p>
          </div>
          <div className={styles.pillars}>
            {pillars.map((p) => (
              <article key={p.no} className={styles.pillar}>
                <span className={styles.pillarNo}>{p.no}</span>
                <h3>{p.title}</h3>
                <p>{p.body}</p>
                <span className={styles.pillarMeta}>{p.meta}</span>
              </article>
            ))}
          </div>
        </section>

        <section className={`${styles.container} ${styles.section}`}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.sectionLabel}>CHANGELOG</p>
              <h2 className={styles.sectionTitle}>Track shipping velocity.</h2>
            </div>
            <p className={styles.sectionSub}>
              Read the live commit stream with implementation context.
            </p>
          </div>
          <div className={styles.changelogCard}>
            <div className={styles.changelogTags}>
              <span>pipeline</span>
              <span>quality</span>
              <span>publisher</span>
              <span>sources</span>
            </div>
            <div className={styles.changelogCta}>
              <Link href="/changelog" className={styles.btnPrimary}>Open Changelog</Link>
              <a
                href="https://github.com/jonas-is-coding/boardwire-ai/blob/main/reports/review_queue.md"
                className={styles.btnGhost}
                target="_blank"
                rel="noreferrer"
              >
                View Review Report →
              </a>
            </div>
          </div>
        </section>

        <section
          id="principles"
          className={`${styles.container} ${styles.section}`}
        >
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.sectionLabel}>PRINCIPLES</p>
              <h2 className={styles.sectionTitle}>
                What Boardwire refuses to do.
              </h2>
            </div>
          </div>
          <ul className={styles.principles}>
            {principles.map((text, i) => (
              <li key={text}>
                <span className={styles.principleNo}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className={styles.principleText}>{text}</span>
              </li>
            ))}
          </ul>
        </section>

        <section
          id="follow"
          className={`${styles.container} ${styles.outro}`}
        >
          <div className={styles.outroCard}>
            <p className={styles.sectionLabel}>FOLLOW THE FEED</p>
            <h2 className={styles.outroTitle}>
              One or two concrete updates a day.
            </h2>
            <p className={styles.outroSub}>
              Boardwire publishes to Bluesky in the hours the network is
              actually awake — top stories as short threads. No newsletter,
              no roundups, no week-in-review — just the signal, when it lands.
            </p>
            <div className={styles.heroCta}>
              <a
                href="https://bsky.app/profile/boardwire.bsky.social"
                className={styles.btnPrimary}
                target="_blank"
                rel="noreferrer"
              >
                Follow on Bluesky
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <Image src="/logo.png" alt="" width={20} height={20} />
            <span>Boardwire</span>
          </div>
          <p>Signals over noise. © {new Date().getFullYear()}</p>
        </div>
      </footer>
    </>
  );
}
