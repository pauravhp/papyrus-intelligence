import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MobileTimelineRow from "../MobileTimelineRow";
import { task, rhythm, gcal } from "./fixtures";

describe("MobileTimelineRow", () => {
  it("renders a scheduled task row with category stripe color", () => {
    const item = task({ task_name: "Write docs", category: "deep_work" });
    render(<MobileTimelineRow kind="task" item={item} />);
    expect(screen.getByText("Write docs")).toBeInTheDocument();
    const stripe = screen.getByTestId("row-stripe");
    expect(stripe).toHaveAttribute("data-category", "deep_work");
  });

  it("renders rhythm with green stripe and RHYTHM badge", () => {
    const item = rhythm({ task_name: "Gym" });
    render(<MobileTimelineRow kind="rhythm" item={item} />);
    expect(screen.getByText("Gym")).toBeInTheDocument();
    expect(screen.getByText("RHYTHM")).toBeInTheDocument();
    const stripe = screen.getByTestId("row-stripe");
    expect(stripe).toHaveAttribute("data-kind", "rhythm");
  });

  it("renders GCal with soft fill, italic title, GCAL badge, no stripe", () => {
    const ev = gcal({ summary: "Standup" });
    render(<MobileTimelineRow kind="gcal" item={ev} />);
    expect(screen.getByText("Standup")).toBeInTheDocument();
    expect(screen.getByText("GCAL")).toBeInTheDocument();
    expect(screen.queryByTestId("row-stripe")).toBeNull();
    expect(screen.getByTestId("row-root")).toHaveAttribute("data-kind", "gcal");
  });

  it("renders the start-time in HH:mm format", () => {
    const item = task({ start_time: "2026-04-28T15:00:00-07:00" });
    render(<MobileTimelineRow kind="task" item={item} />);
    // Locale-dependent; assert one of the two common formats
    const time = screen.getByTestId("row-time").textContent ?? "";
    expect(time).toMatch(/^(15:00|3:00 PM|3:00 pm)$/);
  });

  it("renders the duration label for non-gcal rows", () => {
    const item = task({ duration_minutes: 90 });
    render(<MobileTimelineRow kind="task" item={item} />);
    expect(screen.getByText("1h 30m")).toBeInTheDocument();
  });
});
