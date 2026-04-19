import { describe, it, expect } from "vitest";
import { durationTier } from "./durationTier";

describe("durationTier", () => {
  it("returns sm for exactly 20 minutes", () => {
    expect(durationTier(20)).toBe("sm");
  });
  it("returns sm for less than 20 minutes", () => {
    expect(durationTier(10)).toBe("sm");
    expect(durationTier(1)).toBe("sm");
  });
  it("returns md for 21 minutes", () => {
    expect(durationTier(21)).toBe("md");
  });
  it("returns md for exactly 60 minutes", () => {
    expect(durationTier(60)).toBe("md");
  });
  it("returns lg for 61 minutes", () => {
    expect(durationTier(61)).toBe("lg");
  });
  it("returns lg for 120 minutes", () => {
    expect(durationTier(120)).toBe("lg");
  });
});
