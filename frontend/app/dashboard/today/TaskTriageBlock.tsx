// frontend/app/dashboard/today/TaskTriageBlock.tsx
"use client";

import { useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
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

// Height in px for a given duration. 72px/hour, same as calendar grid.
const PX_PER_HOUR = 72;
function blockHeight(minutes: number): number {
  return Math.max(22, (minutes / 60) * PX_PER_HOUR);
}

export default function TaskTriageBlock({
  item,
  state,
  onStateChange,
  fromTodoist = false,
}: TaskTriageBlockProps) {
  const height = blockHeight(item.duration_minutes);
  const showTimeLabel = height >= 36;
  const blockRef = useRef<HTMLDivElement>(null);
  const [cardOpen, setCardOpen] = useState(false);

  function handleBlockClick() {
    setCardOpen(true);
  }

  const blockOpacity = state === "done" ? 0.55 : state === "tomorrow" ? 0.25 : 1;
  const blockX = state === "tomorrow" ? 10 : 0;

  return (
    <>
    <motion.div
      ref={blockRef}
      role="button"
      aria-label={`View details for ${item.task_name}`}
      tabIndex={0}
      onClick={handleBlockClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleBlockClick(); }}
      animate={{ x: blockX, opacity: blockOpacity }}
      transition={{ type: "spring", stiffness: 120, damping: 18 }}
      style={{
        position: "relative",
        height,
        background: "var(--accent-light)",
        border: "1px solid var(--accent-border)",
        borderRadius: 6,
        marginBottom: 4,
        padding: "4px 8px",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        cursor: "pointer",
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
              background: "rgba(34, 197, 94, 0.25)",
              transformOrigin: "left center",
              borderRadius: 6,
              pointerEvents: "none",
            }}
          />
        )}
      </AnimatePresence>

      {/* Task name */}
      <span
        style={{
          fontSize: 11,
          fontWeight: 500,
          fontFamily: "var(--font-literata)",
          color: "var(--text)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          textDecoration: state === "done" ? "line-through" : "none",
          position: "relative",
          zIndex: 1,
        }}
      >
        {item.task_name}
        {fromTodoist && state === "done" && (
          <span style={{ color: "var(--text-faint)", fontSize: 10, marginLeft: 4 }}>
            · from Todoist
          </span>
        )}
      </span>

      {/* Time label — hidden if block too short */}
      {showTimeLabel && (
        <span
          style={{
            fontSize: 10,
            color: "var(--text-muted)",
            fontFamily: "var(--font-literata)",
            position: "relative",
            zIndex: 1,
          }}
        >
          {fmtTime(item.start_time)}
        </span>
      )}

      {/* State buttons */}
      <div
        style={{
          position: "absolute",
          right: 4,
          top: "50%",
          transform: "translateY(-50%)",
          display: "flex",
          gap: 2,
          zIndex: 2,
        }}
      >
        {(["done", "tomorrow", "keep"] as TriageState[]).map((s) => {
          const labels: Record<TriageState, string> = {
            done: "✓",
            tomorrow: "→",
            keep: "·",
          };
          const tooltips: Record<TriageState, string> = {
            done: "Already finished this",
            tomorrow: "Move to tomorrow",
            keep: "Keep for this afternoon",
          };
          const ariaLabels: Record<TriageState, string> = {
            done: `Mark ${item.task_name} as done`,
            tomorrow: `Move ${item.task_name} to tomorrow`,
            keep: `Keep ${item.task_name} for this afternoon`,
          };
          return (
            <button
              key={s}
              onClick={(e) => { e.stopPropagation(); onStateChange(item.task_id, s); }}
              title={tooltips[s]}
              aria-label={ariaLabels[s]}
              aria-pressed={state === s}
              style={{
                width: 22,
                height: 22,
                borderRadius: 4,
                border: state === s ? "1px solid var(--accent)" : "1px solid var(--border)",
                background: state === s ? "var(--accent)" : "var(--surface)",
                color: state === s ? "var(--surface)" : "var(--text-muted)",
                fontSize: 11,
                cursor: "pointer",
                fontFamily: "monospace",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {labels[s]}
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
