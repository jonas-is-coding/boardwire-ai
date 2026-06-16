import Link from "next/link";
import type { Metadata } from "next";
import styles from "./page.module.css";

type CommitAuthor = {
  date?: string;
  name?: string;
};

type CommitItem = {
  sha: string;
  html_url: string;
  commit: {
    message: string;
    author?: CommitAuthor;
  };
  author?: {
    login?: string;
  } | null;
};

const OWNER = "jonas-is-coding";
const REPO = "boardwire-ai";
const PER_PAGE = 100;

export const metadata: Metadata = {
  title: "Boardwire Changelog",
  description: "Commit changelog for the boardwire-ai repository.",
};

function formatDate(value?: string) {
  if (!value) return "Unknown date";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function parsePage(raw?: string) {
  const page = Number(raw);
  if (!Number.isFinite(page) || page < 1) return 1;
  return Math.floor(page);
}

async function getCommits(page: number): Promise<CommitItem[]> {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/commits?per_page=${PER_PAGE}&page=${page}`;
  const response = await fetch(url, {
    next: { revalidate: 300 },
    headers: {
      Accept: "application/vnd.github+json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to load commits (${response.status})`);
  }

  return (await response.json()) as CommitItem[];
}

type ChangelogProps = {
  searchParams: Promise<{
    page?: string;
  }>;
};

export default async function ChangelogPage({ searchParams }: ChangelogProps) {
  const resolved = await searchParams;
  const page = parsePage(resolved.page);
  const commits = await getCommits(page);
  const hasNextPage = commits.length === PER_PAGE;

  return (
    <main className={styles.wrap}>
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <Link href="/" className={styles.backLink}>
            ← Back to Boardwire
          </Link>
          <a
            href={`https://github.com/${OWNER}/${REPO}`}
            target="_blank"
            rel="noreferrer"
            className={styles.repoLink}
          >
            {OWNER}/{REPO}
          </a>
        </div>
      </header>

      <section className={styles.hero}>
        <p className={styles.eyebrow}>CHANGELOG</p>
        <h1>Boardwire AI Commits</h1>
        <p>
          Alle Commit-Nachrichten mit Datum aus dem Repository. Seite {page}
          {hasNextPage ? " (weitere vorhanden)" : ""}.
        </p>
      </section>

      <section className={styles.list}>
        {commits.map((commit) => {
          const firstLine = commit.commit.message.split("\n")[0] ?? "No message";
          const author = commit.author?.login ?? commit.commit.author?.name ?? "unknown";
          const date = formatDate(commit.commit.author?.date);

          return (
            <article key={commit.sha} className={styles.item}>
              <div className={styles.itemMeta}>
                <span>{date}</span>
                <span>{author}</span>
                <span>{commit.sha.slice(0, 7)}</span>
              </div>
              <a
                href={commit.html_url}
                target="_blank"
                rel="noreferrer"
                className={styles.itemTitle}
              >
                {firstLine}
              </a>
            </article>
          );
        })}
      </section>

      <nav className={styles.pager} aria-label="Changelog pages">
        {page > 1 ? (
          <Link href={`/changelog?page=${page - 1}`} className={styles.pageBtn}>
            ← Newer
          </Link>
        ) : (
          <span className={styles.pageBtnDisabled}>← Newer</span>
        )}
        {hasNextPage ? (
          <Link href={`/changelog?page=${page + 1}`} className={styles.pageBtn}>
            Older →
          </Link>
        ) : (
          <span className={styles.pageBtnDisabled}>Older →</span>
        )}
      </nav>
    </main>
  );
}
