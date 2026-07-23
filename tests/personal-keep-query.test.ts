import { describe, expect, it } from "vitest";
import { initialPersonalKeepQuery } from "../src/personal-keep-query";

describe("initialPersonalKeepQuery", () => {
  it("uses the Root Search fallback text", () => {
    expect(initialPersonalKeepQuery(undefined, "DodoDentist LLC")).toBe("DodoDentist LLC");
  });

  it("prefers an explicitly supplied command argument", () => {
    expect(initialPersonalKeepQuery("Appointment", "DodoDentist LLC")).toBe("Appointment");
  });

  it("uses fallback text when an optional argument is blank", () => {
    expect(initialPersonalKeepQuery("", "DodoDentist LLC")).toBe("DodoDentist LLC");
  });
});
