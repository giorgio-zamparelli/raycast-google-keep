import { describe, expect, it } from "vitest";
import { noteSnippet, searchNotes } from "../src/search";
import type { KeepNote } from "../src/types";

const notes: KeepNote[] = [
  {
    name: "notes/title-match",
    title: "DodoDentist launch",
    text: "Coordinate the project launch with the clinic team.",
    isList: false,
    updatedAt: "2026-07-22T12:00:00Z",
  },
  {
    name: "notes/body-match",
    title: "Project notes",
    text: "Discuss DodoDentist onboarding next week.",
    isList: false,
    updatedAt: "2026-07-23T12:00:00Z",
  },
  {
    name: "notes/other",
    title: "Groceries",
    text: "Buy coffee.",
    isList: true,
  },
];

describe("searchNotes", () => {
  it("matches title and body text case-insensitively, prioritizing title matches", () => {
    expect(searchNotes(notes, "dododentist").map((note) => note.name)).toEqual([
      "notes/title-match",
      "notes/body-match",
    ]);
  });

  it("requires every query term to match", () => {
    expect(searchNotes(notes, "dodo onboarding").map((note) => note.name)).toEqual(["notes/body-match"]);
  });

  it("returns every note for an empty query ordered by recency", () => {
    expect(searchNotes(notes, "").map((note) => note.name)).toEqual([
      "notes/body-match",
      "notes/title-match",
      "notes/other",
    ]);
  });
});

describe("noteSnippet", () => {
  it("centers a snippet around the matching query", () => {
    expect(noteSnippet(notes[1], "dododentist")).toContain("DodoDentist onboarding");
  });

  it("labels an empty note", () => {
    expect(noteSnippet({ ...notes[0], text: "" }, "anything")).toBe("Empty note");
  });
});
