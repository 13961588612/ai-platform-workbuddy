/**
 * Normalize collapsed Markdown tables (common LLM output) into row-per-line format.
 *
 * Handles:
 * - `| a | | b |`  (space between row-ending/starting pipes)
 * - `| a || b |`   (double pipe between rows)
 * - `| a ||| b |`  (multiple pipes)
 */
export function normalizeMarkdownTables(text: string): string {
  if (!text || !text.includes("|")) {
    return text;
  }

  return text
    .replace(/\|\s+\|/g, "|\n|")
    .replace(/\|{2,}/g, "|\n|");
}
