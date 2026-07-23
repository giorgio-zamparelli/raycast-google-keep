export function initialPersonalKeepQuery(argumentQuery?: string, fallbackText?: string): string {
  return argumentQuery?.trim() ? argumentQuery : (fallbackText ?? "");
}
