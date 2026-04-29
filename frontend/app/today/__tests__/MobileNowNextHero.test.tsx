import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MobileNowNextHero from "../MobileNowNextHero";
import type { NowNextState } from "../useNowNext";
import { task } from "./fixtures";

describe("MobileNowNextHero", () => {
  it("renders 'Now' state with title, time-remaining, and next-up", () => {
    const state: NowNextState = {
      kind: "now",
      current: task({ task_name: "API refactor", start_time: "2026-04-28T13:30:00-07:00", end_time: "2026-04-28T15:00:00-07:00" }),
      minutes_left: 52,
      next: task({ task_name: "PR review" }),
    };
    render(<MobileNowNextHero state={state} />);
    expect(screen.getByText(/Now/i)).toBeInTheDocument();
    expect(screen.getByText("API refactor")).toBeInTheDocument();
    expect(screen.getByText(/52m left/)).toBeInTheDocument();
    expect(screen.getByText(/Next.*PR review/)).toBeInTheDocument();
  });

  it("renders 'Free until' state with the next block name", () => {
    const state: NowNextState = {
      kind: "free",
      until: "2026-04-28T15:00:00-07:00",
      next: task({ task_name: "API refactor" }),
    };
    render(<MobileNowNextHero state={state} />);
    expect(screen.getByText(/Free until/i)).toBeInTheDocument();
    expect(screen.getByText(/API refactor/)).toBeInTheDocument();
  });

  it("renders 'Done' state when nothing left today", () => {
    const state: NowNextState = { kind: "done" };
    render(<MobileNowNextHero state={state} />);
    expect(screen.getByText(/Nothing left today/i)).toBeInTheDocument();
  });

  it("has data-sticky=\"true\" so the integration knows it's pinnable", () => {
    const state: NowNextState = { kind: "done" };
    render(<MobileNowNextHero state={state} />);
    expect(screen.getByTestId("now-hero")).toHaveAttribute("data-sticky", "true");
  });
});
