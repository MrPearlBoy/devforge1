import { useMemo, type ReactNode } from "react";

/** Minimal markdown renderer for docs artifacts (headings, lists, tables,
 *  code fences, quotes, hr, inline code/bold). */

function inline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) {
      nodes.push(
        <code key={`${keyBase}-c${i++}`} className="rounded bg-ink-800 px-1 py-0.5 text-[0.85em] text-emerald-300">
          {tok.slice(1, -1)}
        </code>
      );
    } else {
      nodes.push(
        <strong key={`${keyBase}-b${i++}`} className="font-semibold text-slate-100">
          {tok.slice(2, -2)}
        </strong>
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function Markdown({ source, className = "" }: { source: string; className?: string }) {
  const blocks = useMemo(() => renderBlocks(source), [source]);
  return <div className={`space-y-2.5 text-sm leading-relaxed text-slate-300 ${className}`}>{blocks}</div>;
}

function renderBlocks(md: string): ReactNode[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i++;
      continue;
    }

    // code fence
    if (line.trim().startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // closing fence
      out.push(
        <pre
          key={key++}
          className="overflow-x-auto rounded-lg border border-ink-700/60 bg-ink-950 p-3 font-mono text-xs leading-relaxed text-slate-300"
        >
          {buf.join("\n")}
        </pre>
      );
      continue;
    }

    // table
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|[\s|:-]+\|\s*$/.test(lines[i + 1])) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      out.push(
        <div key={key++} className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-ink-700 text-slate-400">
                {header.map((h, j) => (
                  <th key={j} className="px-2 py-1.5 font-semibold">
                    {inline(h, `h${key}-${j}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri} className="border-b border-ink-800/60">
                  {r.map((c, ci) => (
                    <td key={ci} className="px-2 py-1.5 align-top">
                      {inline(c, `t${key}-${ri}-${ci}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // headings
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const content = inline(h[2], `h${key}`);
      if (level === 1)
        out.push(
          <h1 key={key++} className="pt-1 text-xl font-bold text-slate-50">
            {content}
          </h1>
        );
      else if (level === 2)
        out.push(
          <h2 key={key++} className="pt-2 text-base font-semibold text-slate-100">
            {content}
          </h2>
        );
      else
        out.push(
          <h3 key={key++} className="pt-1 text-sm font-semibold text-slate-200">
            {content}
          </h3>
        );
      i++;
      continue;
    }

    // hr
    if (/^\s*---+\s*$/.test(line)) {
      out.push(<hr key={key++} className="border-ink-700/60" />);
      i++;
      continue;
    }

    // blockquote
    if (line.trim().startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        buf.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      out.push(
        <blockquote key={key++} className="border-l-2 border-indigo-500/60 pl-3 text-slate-400">
          {inline(buf.join(" "), `q${key}`)}
        </blockquote>
      );
      continue;
    }

    // lists (bulleted / numbered / task)
    const isLi = (s: string) => /^\s*(?:[-*]|\d+\.)\s+/.test(s);
    if (isLi(line)) {
      const items: string[] = [];
      while (i < lines.length && isLi(lines[i])) {
        items.push(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/, ""));
        i++;
      }
      out.push(
        <ul key={key++} className="space-y-1">
          {items.map((it, j) => (
            <li key={j} className="flex gap-2">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-400/70" />
              <span>{inline(it, `l${key}-${j}`)}</span>
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // paragraph (merge consecutive plain lines)
    const buf: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !/^(#|>|```|\||\s*[-*]\s|\s*\d+\.\s)/.test(lines[i])) {
      buf.push(lines[i]);
      i++;
    }
    out.push(
      <p key={key++} className="text-slate-300">
        {inline(buf.join(" "), `p${key}`)}
      </p>
    );
  }
  return out;
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}
