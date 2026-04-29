import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import MobileDayList from "../MobileDayList";
import { busyAfternoonDay, FIXED_NOW, dayData } from "./fixtures";

describe("MobileDayList", () => {
  it("renders the Now/Next hero", () => {
    render(<MobileDayList dayData={busyAfternoonDay()} isToday now={FIXED_NOW} planningStatus="idle" />);
    expect(screen.getByTestId("now-hero")).toBeInTheDocument();
  });

  it("renders 'Earlier today (3) — Morning workout, Spec review, Email triage'", () => {
    render(<MobileDayList dayData={busyAfternoonDay()} isToday now={FIXED_NOW} planningStatus="idle" />);
    expect(screen.getByTestId("earlier-disclosure")).toHaveTextContent(/Earlier today \(3\)/);
    expect(screen.getByTestId("earlier-disclosure")).toHaveTextContent(/Morning workout/);
  });

  it("expands earlier-today on tap", () => {
    render(<MobileDayList dayData={busyAfternoonDay()} isToday now={FIXED_NOW} planningStatus="idle" />);
    expect(screen.queryByText("Spec review")).toBeNull(); // collapsed
    fireEvent.click(screen.getByTestId("earlier-disclosure"));
    expect(screen.getByText("Spec review")).toBeInTheDocument();
  });

  it("does NOT render Earlier disclosure when no past blocks", () => {
    const morning = new Date("2026-04-28T07:00:00-07:00");
    render(<MobileDayList dayData={busyAfternoonDay()} isToday now={morning} planningStatus="idle" />);
    expect(screen.queryByTestId("earlier-disclosure")).toBeNull();
  });

  it("renders the pushed-tasks footer when pushed.length > 0", () => {
    render(<MobileDayList dayData={busyAfternoonDay()} isToday now={FIXED_NOW} planningStatus="idle" />);
    expect(screen.getByText(/Couldn't place — duration missing/)).toBeInTheDocument();
  });

  it("does NOT render pushed-tasks footer when pushed is empty", () => {
    const day = busyAfternoonDay();
    day.pushed = [];
    render(<MobileDayList dayData={day} isToday now={FIXED_NOW} planningStatus="idle" />);
    expect(screen.queryByText(/Didn't make the cut/i)).toBeNull();
  });

  it("renders the 'Proposed' pill when planningStatus === 'proposal'", () => {
    render(<MobileDayList dayData={busyAfternoonDay()} isToday now={FIXED_NOW} planningStatus="proposal" />);
    expect(screen.getByText(/Proposed/i)).toBeInTheDocument();
  });

  it("renders empty-state for a future day with no schedule", () => {
    render(<MobileDayList dayData={dayData()} isToday={false} now={FIXED_NOW} planningStatus="idle" />);
    expect(screen.getByText(/No schedule planned/i)).toBeInTheDocument();
  });
});
