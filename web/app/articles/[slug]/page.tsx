import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getArticle, getArticleSlugs } from "../lib";
import { renderMarkdown } from "../markdown";
import styles from "../articles.module.css";

export async function generateStaticParams() {
  const slugs = await getArticleSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article) return { title: "Article not found — Daybreak" };
  const { meta } = article;
  const isUrl = /^https?:\/\//.test(meta.hero_image);
  return {
    title: `${meta.title} — Daybreak`,
    description: meta.description || undefined,
    openGraph: {
      title: meta.title,
      description: meta.description || undefined,
      type: "article",
      ...(isUrl ? { images: [{ url: meta.hero_image }] } : {}),
    },
  };
}

function formatDate(value: string): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "long" }).format(parsed);
}

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article) notFound();
  const { meta, content } = article;
  const heroIsUrl = /^https?:\/\//.test(meta.hero_image);

  return (
    <main className={styles.wrap}>
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <Link href="/articles" className={styles.backLink}>
            ← All articles
          </Link>
          <Link href="/" className={styles.repoLink}>
            Daybreak
          </Link>
        </div>
      </header>

      <article className={styles.article}>
        <div className={styles.articleMeta}>
          <span className={styles.beat}>{meta.beat}</span>
          {meta.date && <span>{formatDate(meta.date)}</span>}
          <span>{meta.reading_time} min read</span>
        </div>

        {heroIsUrl && (
          // Hero is an external CDN URL we do not control; plain img is intentional.
          // eslint-disable-next-line @next/next/no-img-element
          <img className={styles.hero} src={meta.hero_image} alt="" />
        )}

        {(meta.verified !== null || meta.sources.length > 0) && (
          <aside className={styles.factCheck} aria-label="Fact check">
            <span className={styles.factBadge}>
              {meta.verified === true
                ? "Multi-source verified"
                : meta.verified === false
                ? "Single-source — treat with care"
                : "Sourced"}
            </span>
            {meta.sources.length > 0 && (
              <span className={styles.factSources}>
                {meta.sources.length} source
                {meta.sources.length === 1 ? "" : "s"} cited
              </span>
            )}
          </aside>
        )}

        <div className={styles.prose}>{renderMarkdown(content)}</div>

        {meta.source_url && (
          <footer className={styles.articleFooter}>
            <a href={meta.source_url} target="_blank" rel="noreferrer">
              Original source: {meta.source || meta.source_url}
            </a>
          </footer>
        )}
      </article>
    </main>
  );
}
