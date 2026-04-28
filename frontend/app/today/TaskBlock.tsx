"use client";

import { useRef, useState } from "react";
import { type ScheduledItem } from "./TodayPage";
import { durationTier } from "./utils/durationTier";
import TaskCard from "./TaskCard";

const PX_PER_HOUR = 72;
const MIN_HEIGHT = 22;

/**
 * Position relative to the column's local midnight (not the task's local
 * hour-of-day). A task at "2026-04-26T00:30:00-07:00" in a column for
 * 2026-04-25 sits 24.5 hours past column midnight — the old `getHours()`
 * approach returned 0 here and pushed the block off-screen above the grid.
 */
function blockTop(startIso: string, columnDateIso: string, gridStartHour: number): number {
  const start = new Date(startIso);
  const colMidnight = new Date(columnDateIso + "T00:00:00");
  const hoursFromColMidnight = (start.getTime() - colMidnight.getTime()) / 3_600_000;
  return (hoursFromColMidnight - gridStartHour) * PX_PER_HOUR;
}

const BLOCK_GAP = 2; // visual breathing room between adjacent blocks

function blockHeight(minutes: number): number {
  return Math.max(MIN_HEIGHT, (minutes / 60) * PX_PER_HOUR - BLOCK_GAP);
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

const CATEGORY_STYLES: Record<
  "deep_work" | "admin" | "untagged",
  { border: string; fills: Record<"sm" | "md" | "lg", string> }
> = {
  deep_work: {
    border: "#7a6250",
    fills: {
      sm: "rgba(122,98,80,0.10)",
      md: "rgba(122,98,80,0.20)",
      lg: "rgba(122,98,80,0.35)",
    },
  },
  admin: {
    border: "#c4821a",
    fills: {
      sm: "rgba(196,130,26,0.08)",
      md: "rgba(196,130,26,0.18)",
      lg: "rgba(196,130,26,0.30)",
    },
  },
  untagged: {
    border: "rgba(44,26,14,0.28)",
    fills: {
      sm: "rgba(44,26,14,0.05)",
      md: "rgba(44,26,14,0.05)",
      lg: "rgba(44,26,14,0.07)",
    },
  },
};

interface TaskBlockProps {
  item: ScheduledItem;
  columnDate: string;  // YYYY-MM-DD; the date this column represents
  gridStart: number;   // grid's first hour — DayColumn extends this earlier when needed
  isProposed?: boolean;
}

export default function TaskBlock({ item, columnDate, gridStart, isProposed = false }: TaskBlockProps) {
  const blockRef = useRef<HTMLDivElement>(null);
  const [cardOpen, setCardOpen] = useState(false);
  const [hovered, setHovered] = useState(false);

  const top = blockTop(item.start_time, columnDate, gridStart);
  const height = blockHeight(item.duration_minutes);
  const showTimeLabel = height >= 36;

  const categoryKey =
    item.category === "deep_work" ? "deep_work"
    : item.category === "admin" ? "admin"
    : "untagged";
  const tier = durationTier(item.duration_minutes);
  const styles = CATEGORY_STYLES[categoryKey];
  const bgColor = hovered
    ? styles.fills[tier].replace(/,\s*([\d.]+)\)$/, (_, n) => `, ${Math.min(1, parseFloat(n) + 0.08).toFixed(2)})`)
    : styles.fills[tier];

  return (
    <>
      <div
        ref={blockRef}
        role="button"
        tabIndex={0}
        aria-label={`${item.task_name}, ${fmtTime(item.start_time)}`}
        onClick={() => setCardOpen(true)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setCardOpen(true); }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          position: "absolute",
          top,
          left: 4,
          right: 4,
          height,
          background: bgColor,
          borderLeft: `3px solid ${styles.border}`,
          borderTop: "none",
          borderRight: "none",
          borderBottom: "none",
          borderRadius: 6,
          padding: "3px 6px",
          overflow: "hidden",
          cursor: "pointer",
          boxSizing: "border-box",
          zIndex: hovered ? 6 : 4,
          boxShadow: isProposed
            ? `0 0 0 1px rgba(196,130,26,0.18), ${hovered ? "0 2px 10px rgba(44,26,14,0.12)" : "none"}`
            : hovered ? "0 2px 10px rgba(44,26,14,0.12)" : "none",
          transition: "background 0.12s, box-shadow 0.12s",
        }}
      >
        <span
          style={{
            display: "block",
            fontSize: 11,
            fontWeight: 500,
            color: "var(--text)",
            fontFamily: "var(--font-literata)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            lineHeight: 1.4,
          }}
        >
          {item.task_name}
        </span>
        {showTimeLabel && (
          <span
            style={{
              display: "block",
              fontSize: 10,
              color: "var(--text-muted)",
              fontFamily: "var(--font-literata)",
            }}
          >
            {fmtTime(item.start_time)}
          </span>
        )}
      </div>

      {cardOpen && blockRef.current && (
        <TaskCard
          item={item}
          anchorRect={blockRef.current.getBoundingClientRect()}
          onClose={() => setCardOpen(false)}
        />
      )}
    </>
  );
}
