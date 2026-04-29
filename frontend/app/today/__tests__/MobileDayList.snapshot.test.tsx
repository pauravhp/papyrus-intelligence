import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MobileDayList from "../MobileDayList";
import { busyAfternoonDay, FIXED_NOW } from "./fixtures";

describe("MobileDayList — squeeze regression guard", () => {
  it("does not introduce horizontal-scroll-causing inline widths", () => {
    render(<MobileDayList dayData={busyAfternoonDay()} isToday now={FIXED_NOW} planningStatus="idle" />);
    // Rows are full-width by default. Assert that no row title element has a
    // hard width style that could clip below 200px.
    const titles = document.querySelectorAll('[data-testid="row-root"] > span:nth-child(3)');
    titles.forEach((t) => {
      const style = (t as HTMLElement).style;
      // No fixed pixel width (width:NNNpx). Flex:1 / width:auto is fine.
      expect(style.width).not.toMatch(/^\d+(\.\d+)?px$/);
    });
  });

  it("renders a stable HTML snapshot for the busy afternoon day", () => {
    const { container } = render(
      <MobileDayList dayData={busyAfternoonDay()} isToday now={FIXED_NOW} planningStatus="idle" />
    );
    expect(container).toMatchSnapshot();
  });
});
