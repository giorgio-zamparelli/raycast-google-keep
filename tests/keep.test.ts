import { describe, expect, it } from "vitest";
import { extractNoteText, listGoogleKeepNotes } from "../src/keep";

describe("extractNoteText", () => {
  it("flattens text and nested checklist items", () => {
    expect(
      extractNoteText({
        body: {
          list: {
            listItems: [
              {
                checked: false,
                text: { text: "Buy supplies" },
                childListItems: [{ checked: true, text: { text: "Coffee" } }],
              },
            ],
          },
        },
      }),
    ).toBe("[ ] Buy supplies\n  [x] Coffee");
  });
});

describe("listGoogleKeepNotes", () => {
  it("follows pages and sends the read-only bearer token", async () => {
    const requests: Array<{ authorization: string | null; url: URL }> = [];
    const fetcher = async (input: URL | RequestInfo, init?: RequestInit) => {
      const url = new URL(input.toString());
      requests.push({ authorization: new Headers(init?.headers).get("Authorization"), url });

      if (!url.searchParams.get("pageToken")) {
        return Response.json({
          nextPageToken: "page-2",
          notes: [{ name: "notes/one", title: "First", body: { text: { text: "DodoDentist" } } }],
        });
      }

      return Response.json({
        notes: [{ name: "notes/two", title: "Second", body: { text: { text: "Other" } } }],
      });
    };

    await expect(listGoogleKeepNotes("access-token", fetcher as typeof fetch)).resolves.toEqual([
      expect.objectContaining({ name: "notes/one", text: "DodoDentist" }),
      expect.objectContaining({ name: "notes/two", text: "Other" }),
    ]);
    expect(requests).toHaveLength(2);
    expect(requests[0]).toMatchObject({ authorization: "Bearer access-token" });
    expect(requests[0].url.searchParams.get("pageSize")).toBe("100");
    expect(requests[1].url.searchParams.get("pageToken")).toBe("page-2");
  });

  it("surfaces the API error message", async () => {
    const fetcher = async () => Response.json({ error: { message: "Permission denied" } }, { status: 403 });

    await expect(listGoogleKeepNotes("access-token", fetcher as typeof fetch)).rejects.toEqual(
      expect.objectContaining({ status: 403, message: "Permission denied" }),
    );
  });
});
