// frontend/app/dashboard/today/TaskTriageBlock.tsx
"use client";

import { useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, ArrowRight, Circle } from "lucide-react";
import { type ScheduledItem } from "./TodayPage";
import TaskCard from "./TaskCard";

export type TriageState = "keep" | "done" | "tomorrow";

interface TaskTriageBlockProps {
  item: ScheduledItem;
  state: TriageState;
  onStateChange: (id: string, state: TriageState) => void;
  fromTodoist?: boolean;  // pre-toggled by Todoist pre-flight
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function fmtDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

const STATE_ICON = {
  done:     <Check size={14} strokeWidth={2.4} />,
  tomorrow: <ArrowRight size={14} strokeWidth={2.4} />,
  keep:     <Circle size={12} strokeWidth={2.4} />,
} as const;

const STATE_TOOLTIP: Record<TriageState, string> = {
  done: "Already finished this",
  tomorrow: "Move to tomorrow",
  keep: "Keep for this afternoon",
};

export default function TaskTriageBlock({
  item,
  state,
  onStateChange,
  fromTodoist = false,
}: TaskTriageBlockProps) {
  const blockRef = useRef<HTMLDivElement>(null);
  const [cardOpen, setCardOpen] = useState(false);

  const blockOpacity = state === "done" ? 0.6 : state === "tomorrow" ? 0.35 : 1;
  const blockX = state === "tomorrow" ? 8 : 0;

  return (
    <>
    <motion.div
      ref={blockRef}
      role="button"
      aria-label={`View details for ${item.task_name}`}
      tabIndex={0}
      onClick={() => setCardOpen(true)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setCardOpen(true); }}
      animate={{ x: blockX, opacity: blockOpacity }}
      transition={{ type: "spring", stiffness: 120, damping: 18 }}
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "11px 12px",
        minHeight: 60,
        background: "var(--accent-light)",
        border: "1px solid var(--accent-border)",
        borderRadius: 8,
        marginBottom: 8,
        cursor: "pointer",
        overflow: "hidden",
      }}
    >
      {/* Green sweep overlay for "done" state */}
      <AnimatePresence>
        {state === "done" && (
          <motion.div
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            exit={{ scaleX: 0 }}
            transition={{ type: "spring", stiffness: 120, damping: 18 }}
            style={{
              position: "absolute",
              inset: 0,
              background: "rgba(34, 197, 94, 0.22)",
              transformOrigin: "left center",
              borderRadius: 8,
              pointerEvents: "none",
            }}
          />
        )}
      </AnimatePresence>

      {/* Left: task name + meta */}
      <div style={{ flex: 1, minWidth: 0, position: "relative", zIndex: 1 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "var(--text)",
            fontFamily: "var(--font-literata)",
            lineHeight: 1.35,
            textDecoration: state === "done" ? "line-through" : "none",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            wordBreak: "break-word",
          }}
        >
          {item.task_name}
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            fontFamily: "var(--font-literata)",
            marginTop: 3,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span>{fmtTime(item.start_time)}</span>
          <span style={{ color: "var(--text-faint)" }}>·</span>
          <span>{fmtDuration(item.duration_minutes)}</span>
          {fromTodoist && state === "done" && (
            <>
              <span style={{ color: "var(--text-faint)" }}>·</span>
              <span style={{ color: "var(--text-faint)", fontStyle: "italic" }}>from Todoist</span>
            </>
          )}
        </div>
      </div>

      {/* Right: state buttons */}
      <div
        style={{
          display: "flex",
          gap: 4,
          flexShrink: 0,
          position: "relative",
          zIndex: 2,
        }}
      >
        {(["done", "tomorrow", "keep"] as TriageState[]).map((s) => {
          const selected = state === s;
          const ariaLabels: Record<TriageState, string> = {
            done: `Mark ${item.task_name} as done`,
            tomorrow: `Move ${item.task_name} to tomorrow`,
            keep: `Keep ${item.task_name} for this afternoon`,
          };
          return (
            <button
              key={s}
              onClick={(e) => { e.stopPropagation(); onStateChange(item.task_id, s); }}
              title={STATE_TOOLTIP[s]}
              aria-label={ariaLabels[s]}
              aria-pressed={selected}
              style={{
                width: 34,
                height: 30,
                borderRadius: 6,
                border: `1px solid ${selected ? "var(--accent)" : "var(--border)"}`,
                background: selected ? "var(--accent)" : "var(--surface)",
                color: selected ? "var(--surface)" : "var(--text-muted)",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "all 0.12s",
              }}
            >
              {STATE_ICON[s]}
            </button>
          );
        })}
      </div>
    </motion.div>
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
