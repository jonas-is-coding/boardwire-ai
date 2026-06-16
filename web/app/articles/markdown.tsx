import type { ReactNode } from "react";

// A small, safe Markdown renderer for the constrained subset the Daybreak
// exporter produces: #/##/### headings, paragraphs, "- " unordered lists,
// [text](url) links and **bold**. Text is rendered as React children, so it is
// escaped by default (no dangerouslySetInnerHTML, no injection surface).

function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let idx = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[1] && m[2]) {
      const href = m[2].trim();
      const external = /^https?:\/\//.test(href);
      nodes.push(
        <a
          key={`${keyBase}-a-${idx}`}
          href={href}
          {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
        >
          {m[1]}
        </a>
      );
    } else if (m[3]) {
      nodes.push(<strong key={`${keyBase}-b-${idx}`}>{m[3]}</strong>);
    }
    last = re.lastIndex;
    idx++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function renderMarkdown(md: string): ReactNode[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i++;
      continue;
    }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2].trim();
      const inner = renderInline(text, `h-${key}`);
      if (level === 1) blocks.push(<h1 key={key++}>{inner}</h1>);
      else if (level === 2) blocks.push(<h2 key={key++}>{inner}</h2>);
      else blocks.push(<h3 key={key++}>{inner}</h3>);
      i++;
      continue;
    }

    if (/^-\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^-\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^-\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++}>
          {items.map((it, n) => (
            <li key={n}>{renderInline(it, `li-${key}-${n}`)}</li>
          ))}
        </ul>
      );
      continue;
    }

    // Paragraph: collect until a blank line, heading or list.
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^(#{1,3})\s+/.test(lines[i]) &&
      !/^-\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(<p key={key++}>{renderInline(para.join(" "), `p-${key}`)}</p>);
  }

  return blocks;
}
