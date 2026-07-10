/**
 * Normalize collapsed Markdown tables (common LLM / transport glitch)
 * into row-per-line format for remark-gfm.
 *
 * IMPORTANT: Do NOT rewrite `|\s+|` inside a row — that is normal cell
 * separation (`| 列A | 列B |`). Only split true row boundaries.
 *
 * Handles:
 * - `| a || b |`     (double pipe between rows)
 * - `| a ||| b |`    (multiple pipes between rows)
 * - `如下：| 列 |`   (table glued after punctuation, no blank line)
 */
export function normalizeMarkdownTables(text: string): string {
  if (!text || !text.includes("|")) {
    return text;
  }

  let result: string = text;

  // Row boundary: two or more consecutive pipes (newlines were dropped)
  result = result.replace(/\|{2,}/g, "|\n|");

  // Table glued after end-of-sentence punctuation on the same line.
  // Do NOT include )］] — they appear inside cells like 余额(元).
  result = result.replace(
    /(^|[^\n|])([：:。；;！!？?])[ \t]*(\|(?=[^|\n]*\|))/gm,
    "$1$2\n\n$3",
  );

  // Single newline before a table that follows non-pipe text → blank line
  result = result.replace(
    /([^\n|])\n(\|(?:[^|\n]+\|){1,}\s*(?:\n|$))/g,
    "$1\n\n$2",
  );

  return result;
}
