import type { KeepNote } from "./types";

const SNIPPET_LENGTH = 150;

export function searchNotes(notes: KeepNote[], query: string): KeepNote[] {
  const normalizedQuery = normalize(query);
  const terms = normalizedQuery.split(" ").filter(Boolean);

  return notes
    .map((note) => {
      const title = normalize(note.title);
      const text = normalize(note.text);
      const searchableText = `${title} ${text}`.trim();

      if (terms.some((term) => !searchableText.includes(term))) return null;

      return {
        note,
        score: scoreMatch(title, text, normalizedQuery, terms),
      };
    })
    .filter((result): result is { note: KeepNote; score: number } => result !== null)
    .sort(
      (left, right) =>
        right.score - left.score ||
        timestamp(right.note) - timestamp(left.note) ||
        left.note.title.localeCompare(right.note.title),
    )
    .map(({ note }) => note);
}

export function noteSnippet(note: KeepNote, query: string): string {
  const text = collapseWhitespace(note.text);
  if (!text) return "Empty note";

  const normalizedQuery = normalize(query);
  const matchingTerm = normalizedQuery.split(" ").find(Boolean);
  const matchIndex = matchingTerm ? text.toLocaleLowerCase().indexOf(matchingTerm) : 0;
  const start = Math.max(0, matchIndex > 0 ? matchIndex - 45 : 0);
  const end = Math.min(text.length, start + SNIPPET_LENGTH);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < text.length ? "…" : "";

  return `${prefix}${text.slice(start, end)}${suffix}`;
}

export function formatNote(note: KeepNote): string {
  return note.text ? `${note.title}\n\n${note.text}` : note.title;
}

function scoreMatch(title: string, text: string, query: string, terms: string[]): number {
  if (!query) return 0;

  let score = 0;

  if (title === query) score += 3_000;
  else if (title.startsWith(query)) score += 2_000;
  else if (title.includes(query)) score += 1_000;
  else if (text.includes(query)) score += 400;

  for (const term of terms) {
    if (title.startsWith(term)) score += 160;
    else if (title.includes(term)) score += 80;
    else if (text.includes(term)) score += 20;
  }

  return score;
}

function timestamp(note: KeepNote): number {
  const value = note.updatedAt ?? note.createdAt;
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalize(value: string): string {
  return collapseWhitespace(value).toLocaleLowerCase();
}

function collapseWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}
