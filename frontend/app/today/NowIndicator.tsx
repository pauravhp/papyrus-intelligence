// frontend/app/dashboard/today/NowIndicator.tsx
"use client";

import { useEffect, useState } from "react";

const PX_PER_HOUR = 72;
const GUTTER_WIDTH = 44;

function fmtTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function nowTop(d: Date, gridStartHour: number): number {
  return (d.getHours() + d.getMinutes() / 60 - gridStartHour) * PX_PER_HOUR;
}

interface Props {
  gridStart: number;
}

export default function NowIndicator({ gridStart }: Props) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const hour = now.getHours();
  // Only show when current time is within the grid span
  if (hour < gridStart || hour >= 25) return null;

  const top = nowTop(now, gridStart);

  return (
    <div
      role="separator"
      aria-label={`Current time: ${fmtTime(now)}`}
      style={{
        position: "absolute",
        top,
        left: -GUTTER_WIDTH,
        right: 0,
        height: 1.5,
        background: "var(--accent)",
        zIndex: 10,
        pointerEvents: "none",
      }}
    >
      {/* Amber dot on left edge */}
      <div
        style={{
          position: "absolute",
          left: GUTTER_WIDTH - 4,
          top: -3,
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: "var(--accent)",
        }}
      />
      {/* Time label on right */}
      <span
        style={{
          position: "absolute",
          right: 4,
          top: -9,
          fontSize: 10,
          color: "var(--accent)",
          fontFamily: "var(--font-literata)",
          whiteSpace: "nowrap",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {fmtTime(now)} →
      </span>
    </div>
  );
}
