import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import MobileActionBar from "../MobileActionBar";

describe("MobileActionBar primary state matrix", () => {
  function setup(overrides: Partial<React.ComponentProps<typeof MobileActionBar>> = {}) {
    const props: React.ComponentProps<typeof MobileActionBar> = {
      isConfirmed: false,
      nowHour: 9,
      autoShiftToTomorrow: false,
      reviewAvailable: false,
      planningOpen: false,
      onPlan: vi.fn(),
      onReplan: vi.fn(),
      onPlanTomorrow: vi.fn(),
      onReview: vi.fn(),
      ...overrides,
    };
    return { props, ...render(<MobileActionBar {...props} />) };
  }

  it("unconfirmed AM → '+ Plan today'", () => {
    setup({ isConfirmed: false, nowHour: 9 });
    expect(screen.getByRole("button", { name: /Plan today/i })).toBeInTheDocument();
  });

  it("confirmed && nowHour >= 12 → '↻ Replan afternoon'", () => {
    setup({ isConfirmed: true, nowHour: 14 });
    expect(screen.getByRole("button", { name: /Replan afternoon/i })).toBeInTheDocument();
  });

  it("autoShiftToTomorrow → '+ Plan tomorrow'", () => {
    setup({ isConfirmed: false, nowHour: 23, autoShiftToTomorrow: true });
    expect(screen.getByRole("button", { name: /Plan tomorrow/i })).toBeInTheDocument();
  });

  it("autoShiftToTomorrow takes precedence over confirmed-replan", () => {
    setup({ isConfirmed: true, nowHour: 23, autoShiftToTomorrow: true });
    expect(screen.getByRole("button", { name: /Plan tomorrow/i })).toBeInTheDocument();
  });

  it("clicking primary calls the right handler per state", () => {
    const onPlan = vi.fn();
    const onReplan = vi.fn();
    const onPlanTomorrow = vi.fn();
    const { unmount } = render(
      <MobileActionBar
        isConfirmed={false} nowHour={9} autoShiftToTomorrow={false} reviewAvailable={false}
        planningOpen={false} onPlan={onPlan} onReplan={onReplan} onPlanTomorrow={onPlanTomorrow}
        onReview={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Plan today/i }));
    expect(onPlan).toHaveBeenCalledOnce();
    unmount();

    render(
      <MobileActionBar
        isConfirmed autoShiftToTomorrow={false} nowHour={14} reviewAvailable={false}
        planningOpen={false} onPlan={vi.fn()} onReplan={onReplan} onPlanTomorrow={onPlanTomorrow}
        onReview={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Replan afternoon/i }));
    expect(onReplan).toHaveBeenCalledOnce();
  });

  it("⋯ menu shows 'Review yesterday' iff reviewAvailable", () => {
    const { rerender } = render(
      <MobileActionBar
        isConfirmed={false} nowHour={9} autoShiftToTomorrow={false} reviewAvailable={false}
        planningOpen={false} onPlan={vi.fn()} onReplan={vi.fn()} onPlanTomorrow={vi.fn()} onReview={vi.fn()}
      />
    );
    fireEvent.click(screen.getByLabelText(/More actions/i));
    expect(screen.queryByText(/Review yesterday/i)).toBeNull();

    rerender(
      <MobileActionBar
        isConfirmed={false} nowHour={9} autoShiftToTomorrow={false} reviewAvailable
        planningOpen={false} onPlan={vi.fn()} onReplan={vi.fn()} onPlanTomorrow={vi.fn()} onReview={vi.fn()}
      />
    );
    fireEvent.click(screen.getByLabelText(/More actions/i));
    expect(screen.getByText(/Review yesterday/i)).toBeInTheDocument();
  });

  it("hides the bar entirely when planningOpen is true", () => {
    setup({ planningOpen: true });
    expect(screen.queryByRole("button", { name: /Plan today/i })).toBeNull();
  });
});
