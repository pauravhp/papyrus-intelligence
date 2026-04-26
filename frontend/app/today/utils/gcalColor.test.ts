import { describe, it, expect } from "vitest";
import { gcalColorToPapyrus } from "./gcalColor";

describe("gcalColorToPapyrus", () => {
  it("returns valid hsl strings for a blue hex", () => {
    const result = gcalColorToPapyrus("#4285F4");
    expect(result.border).toMatch(/^hsl\(\d+,\s*35%,\s*38%\)$/);
    expect(result.fill).toMatch(/^hsl\(\d+,\s*30%,\s*88%\)$/);
  });
  it("same hex always produces same result (deterministic)", () => {
    const a = gcalColorToPapyrus("#0F9D58");
    const b = gcalColorToPapyrus("#0F9D58");
    expect(a.border).toBe(b.border);
    expect(a.fill).toBe(b.fill);
  });
  it("returns neutral fallback for missing/invalid hex", () => {
    const result = gcalColorToPapyrus("");
    expect(result.border).toBe("rgba(44,26,14,0.25)");
    expect(result.fill).toBe("rgba(44,26,14,0.05)");
  });
  it("different hues produce different border colors", () => {
    const blue = gcalColorToPapyrus("#4285F4");
    const green = gcalColorToPapyrus("#0F9D58");
    expect(blue.border).not.toBe(green.border);
  });
});
