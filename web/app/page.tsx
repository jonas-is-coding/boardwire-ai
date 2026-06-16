import Image from "next/image";
import Link from "next/link";
import { SiBluesky, SiGithub } from "react-icons/si";
import styles from "./page.module.css";
import Workflow from "./_workflow";

const stats = [
  { value: "good", label: "news first" },
  { value: "multi", label: "source verified" },
  { value: "full", label: "articles" },
  { value: "2", label: "LLM passes" },
  { value: "3/day", label: "publish cap" },
];

const trustBadges = [
  "constructive line",
  "truth guard",
  "multi-source verified",
  "no doom · no clickbait",
  "review queue",
  "sources cited",
];

const runMetrics = [
  { label: "Last run", value: "~15 min ago" },
  { label: "New candidates", value: "40-70" },
  { label: "Story clusters", value: "12-20" },
  { label: "Published today", value: "0-3" },
];

const sourceRows = [
  { name: "Positive News", tier: "T2" },
  { name: "Reasons to be Cheerful", tier: "T2" },
  { name: "Our World in Data", tier: "T2" },
  { name: "Good News Network", tier: "T3" },
  { name: "The Optimist Daily", tier: "T3" },
  { name: "Future Crunch", tier: "T3" },
];

const pillars = [
  {
    no: "01",
    title: "Good news, but only if it's true",
    body: "Daybreak foregrounds progress, recovery and solutions that actually work — then makes that the lede. A built-in truth guard rejects PR spin, toxic positivity and unverifiable feel-good claims. The optimism has to be earned by the evidence.",
    meta: "constructive line · integrity check",
  },
  {
    no: "02",
    title: "Cross-source truth over single-link hype",
    body: "Stories are grouped across many independent feeds and promoted only when corroborated by multiple sources. Every claim carries a support level, and every article cites where it came from.",
    meta: "corroboration · clustering · support levels",
  },
  {
    no: "03",
    title: "Real articles, not just posts",
    body: "Each story is researched into a dossier of verified facts, then written up as a full long-form feature you can read here — alongside the short social posts that point back to it.",
    meta: "research dossier · long-form · social",
  },
];

const principles = [
  "Good news, but never at the expense of the truth.",
  "Progress and solutions over doom, outrage and clickbait.",
  "Every claim sourced. Review before publish. Always.",
];

export default function Home() {
  return (
    <>
      <header className={styles.nav}>
        <div className={styles.navInner}>
          <div className={styles.brandCluster}>
            <Link href="/" className={styles.brand} aria-label="Daybreak home">
              <span className={styles.brandLogo}>
                <Image
                  src="/logo.png"
                  alt=""
                  width={26}
                  height={26}
                  priority
                />
              </span>
              <span className={styles.brandName}>Daybreak</span>
            </Link>
            <Link href="/changelog" className={styles.brandTag}>
              v0
            </Link>
          </div>
          <nav className={styles.navLinks} aria-label="Primary">
            <Link href="/articles">Articles</Link>
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
              aria-label="Daybreak on GitHub"
            >
              <SiGithub size={20} />
            </a>
            <a
              href="https://bsky.app/profile/boardwire.bsky.social"
              className={styles.socialIcon}
              target="_blank"
              rel="noreferrer"
              aria-label="Daybreak on Bluesky"
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
              LIVE · AUTONOMOUS · CONSTRUCTIVE
            </p>
            <h1 className={styles.heroTitle}>
              Good news, well reported<span className={styles.period}>.</span>
            </h1>
            <p className={styles.heroSub}>
              Verified good news in, full articles out, up to 3 posts per day.
              Daybreak runs as an autonomous, constructive newsroom — progress
              and solutions, never at the expense of the truth.
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
              then AI-agent coordination in Slack.
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
              A starter set of constructive, solutions-focused sources, grouped with
              tier context. Ranking uses these tiers, recency and corroboration
              before anything is published.
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
              <h2 className={styles.sectionTitle}>A newsroom for good news.</h2>
            </div>
            <p className={styles.sectionSub}>
              Daybreak is a fully automated editorial pipeline that behaves like a
              small newsroom for good news. It corroborates stories across
              sources, researches each into a verified dossier, then ships only
              what survives the constructive editorial gate and review.
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
                What Daybreak refuses to do.
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
              Up to three good things a day.
            </h2>
            <p className={styles.outroSub}>
              Daybreak publishes full articles here and short posts to Bluesky and X —
              progress and solutions worth your attention, when they land.
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
              <a
                href="https://x.com/boardwire_ai"
                className={styles.btnGhost}
                target="_blank"
                rel="noreferrer"
              >
                Follow on X →
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <Image src="/logo.png" alt="" width={20} height={20} />
            <span>Daybreak</span>
          </div>
          <p>Good news, well reported. © {new Date().getFullYear()}</p>
        </div>
      </footer>
    </>
  );
}
