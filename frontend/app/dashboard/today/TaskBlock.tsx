// frontend/app/dashboard/today/TaskBlock.tsx
"use client";

import { useRef, useState } from "react";
import { type ScheduledItem } from "./TodayPage";
import TaskCard from "./TaskCard";

const GRID_START_HOUR = 8;
const PX_PER_HOUR = 72;
const MIN_HEIGHT = 22;

function blockTop(startIso: string): number {
  const d = new Date(startIso);
  return (d.getHours() + d.getMinutes() / 60 - GRID_START_HOUR) * PX_PER_HOUR;
}

function blockHeight(minutes: number): number {
  return Math.max(MIN_HEIGHT, (minutes / 60) * PX_PER_HOUR);
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

interface TaskBlockProps {
  item: ScheduledItem;
}

export default function TaskBlock({ item }: TaskBlockProps) {
  const blockRef = useRef<HTMLDivElement>(null);
  const [cardOpen, setCardOpen] = useState(false);
  const [hovered, setHovered] = useState(false);

  const top = blockTop(item.start_time);
  const height = blockHeight(item.duration_minutes);
  const showTimeLabel = height >= 36;

  return (
    <>
      <div
        ref={blockRef}
        role="button"
        tabIndex={0}
        aria-label={`${item.task_name}, ${fmtTime(item.start_time)}`}
        onClick={() => setCardOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") setCardOpen(true);
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          position: "absolute",
          top,
          left: 4,
          right: 4,
          height,
          background: hovered ? "var(--accent-light-hover, #eedabb)" : "var(--accent-light)",
          border: "1px solid var(--accent-border)",
          borderRadius: 6,
          padding: "3px 6px",
          overflow: "hidden",
          cursor: "pointer",
          boxSizing: "border-box",
          zIndex: hovered ? 6 : 4,
          boxShadow: hovered ? "0 2px 10px rgba(192,122,47,0.2)" : "none",
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
