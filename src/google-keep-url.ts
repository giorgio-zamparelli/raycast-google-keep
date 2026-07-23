export function googleKeepSearchUrl(query: string): string {
  return `https://keep.google.com/u/0/#search/text=${encodeURIComponent(query.trim())}`;
}
