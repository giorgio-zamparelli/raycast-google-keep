import type { GoogleKeepListItem, GoogleKeepListResponse, GoogleKeepNote, KeepNote } from "./types";

const GOOGLE_KEEP_NOTES_URL = "https://keep.googleapis.com/v1/notes";
const PAGE_SIZE = "100";

export class GoogleKeepApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "GoogleKeepApiError";
  }
}

export async function listGoogleKeepNotes(accessToken: string, fetcher: typeof fetch = fetch): Promise<KeepNote[]> {
  const notes = new Map<string, KeepNote>();
  let pageToken: string | undefined;
  let fallbackIndex = 0;

  do {
    const url = new URL(GOOGLE_KEEP_NOTES_URL);
    url.searchParams.set("pageSize", PAGE_SIZE);

    if (pageToken) {
      url.searchParams.set("pageToken", pageToken);
    }

    const response = await fetcher(url, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });

    if (!response.ok) {
      throw new GoogleKeepApiError(response.status, await responseMessage(response));
    }

    const payload = (await response.json()) as GoogleKeepListResponse;

    for (const note of payload.notes ?? []) {
      const searchableNote = toKeepNote(note, fallbackIndex);
      fallbackIndex += 1;
      notes.set(searchableNote.name, searchableNote);
    }

    pageToken = payload.nextPageToken;
  } while (pageToken);

  return [...notes.values()];
}

export function toKeepNote(note: GoogleKeepNote, fallbackIndex = 0): KeepNote {
  const title = note.title?.trim() || "Untitled note";
  const text = extractNoteText(note);

  return {
    createdAt: note.createTime,
    isList: Boolean(note.body?.list),
    name: note.name ?? `local-${fallbackIndex}-${title}`,
    text,
    title,
    updatedAt: note.updateTime,
  };
}

export function extractNoteText(note: GoogleKeepNote): string {
  const text = note.body?.text?.text?.trim();
  const listItems = note.body?.list?.listItems;

  return [text, ...(listItems ? flattenListItems(listItems) : [])].filter(Boolean).join("\n");
}

export function flattenListItems(items: GoogleKeepListItem[], depth = 0): string[] {
  return items.flatMap((item) => {
    const text = item.text?.text?.trim();
    const prefix = "  ".repeat(depth);
    const itemText = text ? [`${prefix}${item.checked ? "[x]" : "[ ]"} ${text}`] : [];
    const children = item.childListItems ? flattenListItems(item.childListItems, depth + 1) : [];

    return [...itemText, ...children];
  });
}

async function responseMessage(response: Response): Promise<string> {
  const defaultMessage = `Google Keep API request failed with status ${response.status}.`;

  try {
    const text = await response.text();
    if (!text) return defaultMessage;

    const json = JSON.parse(text) as { error?: { message?: string } };
    return json.error?.message || text.slice(0, 500);
  } catch {
    return defaultMessage;
  }
}
