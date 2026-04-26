// frontend/app/dashboard/today/TaskCard.tsx
"use client";

import { useEffect, useRef } from "react";
import { type ScheduledItem } from "./TodayPage";

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function fmtDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

interface TaskCardProps {
  item: ScheduledItem;
  anchorRect: DOMRect;   // getBoundingClientRect() of the block that was clicked
  onClose: () => void;
}

export default function TaskCard({ item, anchorRect, onClose }: TaskCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);

  // Escape key
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Click outside
  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (cardRef.current && !cardRef.current.contains(e.target as Node)) onClose();
    }
    // Delay so the opening click doesn't immediately close the card
    const id = setTimeout(() => document.addEventListener("mousedown", onClickOutside), 0);
    return () => {
      clearTimeout(id);
      document.removeEventListener("mousedown", onClickOutside);
    };
  }, [onClose]);

  // Position: right of block; flip left if less than 228px from right edge
  const CARD_WIDTH = 220;
  const GAP = 8;
  const spaceRight = window.innerWidth - anchorRect.right;
  const left =
    spaceRight >= CARD_WIDTH + GAP
      ? anchorRect.right + GAP
      : anchorRect.left - CARD_WIDTH - GAP;
  const top = Math.min(anchorRect.top, window.innerHeight - 160);

  return (
    <div
      ref={cardRef}
      role="dialog"
      aria-modal="true"
      aria-label={`Details for ${item.task_name}`}
      style={{
        position: "fixed",
        top,
        left,
        width: CARD_WIDTH,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: "14px 16px",
        zIndex: 1100,
        boxShadow: "0 4px 24px rgba(0,0,0,0.12)",
      }}
    >
      <p
        style={{
          fontSize: 13,
          fontFamily: "var(--font-literata)",
          color: "var(--text)",
          fontWeight: 500,
          marginBottom: 8,
          lineHeight: 1.4,
        }}
      >
        {item.task_name}
      </p>
      <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-literata)", marginBottom: 2 }}>
        {fmtTime(item.start_time)} – {fmtTime(item.end_time)}
      </p>
      <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-literata)", marginBottom: 14 }}>
        {fmtDuration(item.duration_minutes)}
      </p>
      {/* Rhythm tasks are synthetic (proj_<rhythm_id>) — no Todoist task to link to. */}
      {!item.task_id.startsWith("proj_") && (
        <a
          href={`https://app.todoist.com/app/task/${item.task_id}`}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${item.task_name} in Todoist`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: 12,
            color: "var(--accent)",
            fontFamily: "var(--font-literata)",
            textDecoration: "none",
          }}
        >
          Open in Todoist ↗
        </a>
      )}
    </div>
  );
}
