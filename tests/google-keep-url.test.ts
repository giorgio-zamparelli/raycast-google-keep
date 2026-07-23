import { describe, expect, it } from "vitest";
import { googleKeepSearchUrl } from "../src/google-keep-url";

describe("googleKeepSearchUrl", () => {
  it("uses Google Keep's native search route and safely encodes the query", () => {
    expect(googleKeepSearchUrl("DodoDentist & launch")).toBe(
      "https://keep.google.com/u/0/#search/text=DodoDentist%20%26%20launch",
    );
  });
});
