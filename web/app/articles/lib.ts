import { promises as fs } from "fs";
import path from "path";

// Articles are exported by the Daybreak backend to <repo>/articles/*.md.
// The web app lives in <repo>/web, so default to ../articles; allow override.
const ARTICLES_DIR =
  process.env.ARTICLES_DIR || path.join(process.cwd(), "..", "articles");

export type ArticleMeta = {
  slug: string;
  title: string;
  date: string;
  source: string;
  source_url: string;
  description: string;
  beat: string;
  reading_time: number;
  hero_image: string;
  verified: boolean | null; // null = no dossier / unknown
  sources: string[];
};

export type Article = {
  meta: ArticleMeta;
  content: string;
};

function stripQuotes(value: string): string {
  const v = value.trim();
  if (v.length >= 2 && v.startsWith('"') && v.endsWith('"')) {
    return v.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
  return v;
}

type FrontMatter = { data: Record<string, string | string[]>; content: string };

function parseFrontMatter(raw: string): FrontMatter {
  const text = raw.replace(/\r\n/g, "\n");
  if (!text.startsWith("---\n")) {
    return { data: {}, content: text };
  }
  const lines = text.split("\n");
  const data: Record<string, string | string[]> = {};
  let i = 1;
  for (; i < lines.length; i++) {
    if (lines[i].trim() === "---") {
      i++;
      break;
    }
    const m = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(lines[i]);
    if (!m) continue;
    const key = m[1];
    const value = m[2];
    // A YAML list: "key:" followed by indented "- item" lines.
    if (value === "" && /^\s+-\s+/.test(lines[i + 1] ?? "")) {
      const list: string[] = [];
      while (/^\s+-\s+/.test(lines[i + 1] ?? "")) {
        i++;
        list.push(stripQuotes(lines[i].replace(/^\s+-\s+/, "")));
      }
      data[key] = list;
    } else {
      data[key] = stripQuotes(value);
    }
  }
  return { data, content: lines.slice(i).join("\n").replace(/^\n+/, "") };
}

function toMeta(slug: string, data: Record<string, string | string[]>): ArticleMeta {
  const str = (k: string) => (typeof data[k] === "string" ? (data[k] as string) : "");
  const verifiedRaw = data["verified"];
  const verified =
    typeof verifiedRaw === "string"
      ? verifiedRaw.trim().toLowerCase() === "true"
      : null;
  const readingTime = Number(str("reading_time"));
  return {
    slug,
    title: str("title") || "Untitled",
    date: str("date"),
    source: str("source"),
    source_url: str("source_url"),
    description: str("description"),
    beat: str("beat") || "news",
    reading_time: Number.isFinite(readingTime) && readingTime > 0 ? readingTime : 1,
    hero_image: str("hero_image"),
    verified,
    sources: Array.isArray(data["sources"]) ? (data["sources"] as string[]) : [],
  };
}

async function listFiles(): Promise<string[]> {
  try {
    const entries = await fs.readdir(ARTICLES_DIR);
    return entries.filter((f) => f.endsWith(".md"));
  } catch {
    return [];
  }
}

export async function getArticleSlugs(): Promise<string[]> {
  return (await listFiles()).map((f) => f.replace(/\.md$/, ""));
}

export async function getArticle(slug: string): Promise<Article | null> {
  // Guard against path traversal — slugs map 1:1 to files in ARTICLES_DIR.
  if (!slug || slug.includes("/") || slug.includes("..")) return null;
  try {
    const raw = await fs.readFile(path.join(ARTICLES_DIR, `${slug}.md`), "utf-8");
    const { data, content } = parseFrontMatter(raw);
    return { meta: toMeta(slug, data), content };
  } catch {
    return null;
  }
}

export async function getAllArticles(): Promise<ArticleMeta[]> {
  const slugs = await getArticleSlugs();
  const articles = await Promise.all(slugs.map((s) => getArticle(s)));
  return articles
    .filter((a): a is Article => a !== null)
    .map((a) => a.meta)
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}
