import { describe, expect, it } from "vitest";
import { parseBridgeResponse, PersonalKeepBridgeError } from "../src/personal-keep-protocol";

describe("parseBridgeResponse", () => {
  it("reads a successful personal Keep note preview response", () => {
    const response = parseBridgeResponse(
      JSON.stringify({
        version: 1,
        ok: true,
        notes: [{ id: "note-1", title: "DodoDentist", snippet: "Call the dentist", isList: false }],
      }),
    );

    expect(response.notes).toEqual([
      { id: "note-1", title: "DodoDentist", snippet: "Call the dentist", isList: false },
    ]);
  });

  it("reads aggregate metadata after a successful Root Search mirror sync", () => {
    const response = parseBridgeResponse(
      JSON.stringify({
        version: 1,
        ok: true,
        mirror: {
          directory: "/Users/example/Google Keep Search",
          notes: 4,
          written: 2,
          removed: 1,
          unchanged: 2,
        },
      }),
    );

    expect(response.mirror).toEqual({
      directory: "/Users/example/Google Keep Search",
      notes: 4,
      written: 2,
      removed: 1,
      unchanged: 2,
    });
  });

  it("turns a safe bridge error into a typed error", () => {
    expect(() =>
      parseBridgeResponse(
        JSON.stringify({
          version: 1,
          ok: false,
          error: { code: "not-configured", message: "Connect personal Google Keep first." },
        }),
      ),
    ).toThrow(PersonalKeepBridgeError);
  });

  it("rejects malformed output", () => {
    expect(() => parseBridgeResponse("not-json")).toThrow("unreadable response");
  });
});
