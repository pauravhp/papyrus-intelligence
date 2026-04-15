// frontend/app/dashboard/today/NowIndicator.tsx
"use client";

import { useEffect, useState } from "react";
import { type ScheduledItem } from "./TodayPage";
import TaskBlock from "./TaskBlock";

function fmtTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

interface NowIndicatorProps {
  scheduled: ScheduledItem[];
}

export default function NowIndicator({ scheduled: items }: NowIndicatorProps) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  // Sort by start_time
  const sorted = [...items].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  );

  const firstStart = sorted.length > 0 ? new Date(sorted[0].start_time) : null;
  const lastEnd    = sorted.length > 0 ? new Date(sorted[sorted.length - 1].end_time) : null;

  // Determine insert position: index of first item whose start_time > now
  // now-line goes before that item (or at end if all have started)
  const insertBefore = sorted.findIndex(item => new Date(item.start_time) > now);
  // -1 means all tasks have started (insert after last), 0 means before first

  // Only show if now is within the schedule span
  const withinSpan = firstStart && lastEnd && now >= firstStart && now <= lastEnd;

  const NowLine = (
    <div
      role="separator"
      aria-label={`Current time: ${fmtTime(now)}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        margin: "4px 0",
      }}
    >
      <div style={{ flex: 1, height: 1, background: "var(--accent)" }} />
      <span
        style={{
          color: "var(--accent)",
          fontSize: 11,
          whiteSpace: "nowrap",
          fontFamily: "var(--font-literata)",
        }}
      >
        {fmtTime(now)} →
      </span>
    </div>
  );

  return (
    <div>
      {sorted.map((item, idx) => (
        <div key={item.task_id}>
          {/* Insert now-line before the first upcoming task */}
          {withinSpan && insertBefore === idx && NowLine}
          <TaskBlock item={item} />
        </div>
      ))}
      {/* If all tasks have started (insertBefore === -1), show at end */}
      {withinSpan && insertBefore === -1 && NowLine}
    </div>
  );
}
