import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import MobilePlanningSheet from "../MobilePlanningSheet";

describe("MobilePlanningSheet", () => {
  it("renders the wrapped child", () => {
    render(
      <MobilePlanningSheet onClose={vi.fn()}>
        <div>panel content</div>
      </MobilePlanningSheet>
    );
    expect(screen.getByText("panel content")).toBeInTheDocument();
  });

  it("starts at low snap (data-snap='low')", () => {
    render(
      <MobilePlanningSheet onClose={vi.fn()}>
        <textarea aria-label="refine input" />
      </MobilePlanningSheet>
    );
    expect(screen.getByTestId("mobile-planning-sheet")).toHaveAttribute("data-snap", "low");
  });

  it("snaps to 'high' when an inner textarea takes focus", () => {
    render(
      <MobilePlanningSheet onClose={vi.fn()}>
        <textarea aria-label="refine input" />
      </MobilePlanningSheet>
    );
    fireEvent.focusIn(screen.getByLabelText("refine input"));
    expect(screen.getByTestId("mobile-planning-sheet")).toHaveAttribute("data-snap", "high");
  });

  it("returns to 'low' when the textarea blurs", () => {
    render(
      <MobilePlanningSheet onClose={vi.fn()}>
        <textarea aria-label="refine input" />
      </MobilePlanningSheet>
    );
    const ta = screen.getByLabelText("refine input");
    fireEvent.focusIn(ta);
    fireEvent.focusOut(ta);
    expect(screen.getByTestId("mobile-planning-sheet")).toHaveAttribute("data-snap", "low");
  });

  it("calls onClose when the drag-handle close button is clicked", () => {
    const onClose = vi.fn();
    render(<MobilePlanningSheet onClose={onClose}><div>x</div></MobilePlanningSheet>);
    fireEvent.click(screen.getByLabelText(/dismiss planning/i));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
