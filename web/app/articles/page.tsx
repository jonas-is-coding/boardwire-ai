import Link from "next/link";
import type { Metadata } from "next";
import { getAllArticles } from "./lib";
import styles from "./articles.module.css";

export const metadata: Metadata = {
  title: "Daybreak — Articles",
  description:
    "Full long-form features from Daybreak: good, well-reported news — progress, recovery and solutions that actually work.",
};

function formatDate(value: string): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "long" }).format(parsed);
}

export default async function ArticlesPage() {
  const articles = await getAllArticles();

  return (
    <main className={styles.wrap}>
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <Link href="/" className={styles.backLink}>
            ← Back to Daybreak
          </Link>
          <Link href="/changelog" className={styles.repoLink}>
            Changelog
          </Link>
        </div>
      </header>

      <section className={styles.hero}>
        <p className={styles.eyebrow}>ARTICLES</p>
        <h1>Good news, in full.</h1>
        <p className={styles.heroSub}>
          The stories behind the headlines — progress, recovery and solutions
          that actually work, researched and written out in long form.
        </p>
      </section>

      {articles.length === 0 ? (
        <section className={styles.empty}>
          <p>No articles yet. They appear here as the newsroom publishes them.</p>
        </section>
      ) : (
        <section className={styles.list}>
          {articles.map((a) => (
            <article key={a.slug} className={styles.card}>
              <div className={styles.cardMeta}>
                <span className={styles.beat}>{a.beat}</span>
                {a.date && <span>{formatDate(a.date)}</span>}
                <span>{a.reading_time} min read</span>
                {a.verified === true && (
                  <span className={styles.verified}>multi-source verified</span>
                )}
              </div>
              <Link href={`/articles/${a.slug}`} className={styles.cardTitle}>
                {a.title}
              </Link>
              {a.description && <p className={styles.cardSub}>{a.description}</p>}
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
