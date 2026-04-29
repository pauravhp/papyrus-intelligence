"use client";

import { useState } from "react";
import MobileOverflowMenu from "./MobileOverflowMenu";

export interface MobileActionBarProps {
  isConfirmed: boolean;
  nowHour: number;
  autoShiftToTomorrow: boolean;
  reviewAvailable: boolean;
  planningOpen: boolean;
  onPlan: () => void;
  onReplan: () => void;
  onPlanTomorrow: () => void;
  onReview: () => void;
}

type Primary =
  | { kind: "plan-today"; label: string; onClick: () => void }
  | { kind: "replan"; label: string; onClick: () => void }
  | { kind: "plan-tomorrow"; label: string; onClick: () => void };

function pickPrimary(props: MobileActionBarProps): Primary {
  if (props.autoShiftToTomorrow) {
    return { kind: "plan-tomorrow", label: "+ Plan tomorrow", onClick: props.onPlanTomorrow };
  }
  if (props.isConfirmed && props.nowHour >= 12) {
    return { kind: "replan", label: "↻ Replan afternoon", onClick: props.onReplan };
  }
  return { kind: "plan-today", label: "+ Plan today", onClick: props.onPlan };
}

export default function MobileActionBar(props: MobileActionBarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  if (props.planningOpen) return null;

  const primary = pickPrimary(props);

  const items = [
    ...(props.reviewAvailable
      ? [{ label: "✓ Review yesterday", onSelect: props.onReview, emphasis: "primary" as const }]
      : []),
    { label: "Settings", onSelect: () => { window.location.href = "/settings"; }, emphasis: "default" as const },
  ];

  return (
    <>
      <div
        data-testid="mobile-action-bar"
        style={{
          position: "fixed",
          left: 0,
          right: 0,
          bottom: 0,
          padding: "10px 14px calc(12px + env(safe-area-inset-bottom))",
          background: "var(--bg)",
          borderTop: "1px solid var(--border)",
          boxShadow: "0 -2px 12px rgba(44,26,14,0.06)",
          display: "flex",
          gap: 8,
          zIndex: 30,
        }}
      >
        <button
          type="button"
          onClick={primary.onClick}
          style={{
            flex: 1,
            background: "var(--accent)",
            color: "var(--bg)",
            border: "none",
            padding: "12px",
            borderRadius: 9,
            fontFamily: "var(--font-literata)",
            fontSize: 14,
            fontWeight: 500,
            minHeight: 48,
          }}
        >
          {primary.label}
        </button>
        <button
          type="button"
          aria-label="More actions"
          onClick={() => setMenuOpen(true)}
          style={{
            background: "transparent",
            border: "1px solid var(--border)",
            color: "var(--text)",
            width: 44,
            borderRadius: 9,
            fontSize: 18,
            minHeight: 48,
          }}
        >
          ⋯
        </button>
      </div>
      <MobileOverflowMenu open={menuOpen} items={items} onClose={() => setMenuOpen(false)} />
    </>
  );
}
