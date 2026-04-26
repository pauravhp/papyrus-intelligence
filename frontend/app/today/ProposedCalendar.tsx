// frontend/app/dashboard/today/ProposedCalendar.tsx
"use client";

import { useRef, useState } from "react";
import TaskCard from "./TaskCard";
import { type ScheduledItem } from "./TodayPage";

const PX_PER_HOUR = 72;
function blockHeight(minutes: number): number {
  return Math.max(22, (minutes / 60) * PX_PER_HOUR);
}
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

const MAX_WORDS = 40;
function countWords(s: string): number {
  return s.trim() === "" ? 0 : s.trim().split(/\s+/).length;
}

interface ProposedCalendarProps {
  scheduled: ScheduledItem[];
  reasoningSummary: string;
  onRefinement: (message: string) => void;
  isRefining: boolean;
}

export default function ProposedCalendar({
  scheduled,
  reasoningSummary,
  onRefinement,
  isRefining,
}: ProposedCalendarProps) {
  const [refinement, setRefinement] = useState("");
  const wordCount = countWords(refinement);
  const overLimit = wordCount > MAX_WORDS;
  const [activeCard, setActiveCard] = useState<{ item: ScheduledItem; rect: DOMRect } | null>(null);
  const blockRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !overLimit && refinement.trim() && !isRefining) {
      onRefinement(refinement.trim());
      setRefinement("");
    }
  }

  return (
    <div>
      {/* Proposed blocks */}
      <div style={{ marginBottom: 12 }}>
        {scheduled.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--text-faint)", fontStyle: "italic", fontFamily: "var(--font-literata)" }}>
            No tasks to schedule this afternoon.
          </p>
        ) : (
          scheduled.map((item) => {
            const minHeight = Math.max(44, blockHeight(item.duration_minutes));
            return (
              <div
                key={`${item.task_id}__${item.start_time}`}
                ref={(el) => { if (el) blockRefs.current.set(item.task_id, el); }}
                role="button"
                tabIndex={0}
                aria-label={`View details for ${item.task_name}`}
                onClick={() => {
                  const el = blockRefs.current.get(item.task_id);
                  if (el) setActiveCard({ item, rect: el.getBoundingClientRect() });
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    const el = blockRefs.current.get(item.task_id);
                    if (el) setActiveCard({ item, rect: el.getBoundingClientRect() });
                  }
                }}
                style={{
                  minHeight,
                  background: "rgba(34, 197, 94, 0.12)",
                  border: "1px solid rgba(34, 197, 94, 0.4)",
                  borderRadius: 6,
                  marginBottom: 4,
                  padding: "6px 8px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                  cursor: "pointer",
                  minWidth: 0,
                }}
              >
                <span style={{
                  fontSize: 11,
                  fontWeight: 500,
                  color: "var(--text)",
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                  wordBreak: "break-word",
                  lineHeight: 1.35,
                  fontFamily: "var(--font-literata)",
                }}>
                  {item.task_name}
                </span>
                <span style={{
                  fontSize: 10,
                  color: "var(--text-muted)",
                  fontFamily: "var(--font-literata)",
                  marginTop: 2,
                }}>
                  {fmtTime(item.start_time)} · {item.duration_minutes}m
                </span>
              </div>
            );
          })
        )}
      </div>

      {/* Reasoning summary */}
      {reasoningSummary && (
        <p style={{
          fontSize: 12,
          color: "var(--text-muted)",
          fontStyle: "italic",
          fontFamily: "var(--font-literata)",
          marginBottom: 16,
          lineHeight: 1.5,
        }}>
          {reasoningSummary}
        </p>
      )}

      {/* Refinement input */}
      <div style={{ position: "relative" }}>
        <input
          type="text"
          value={refinement}
          onChange={(e) => setRefinement(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Adjust the plan… (press Enter)"
          disabled={isRefining}
          aria-label="Refine the proposed schedule"
          style={{
            width: "100%",
            padding: "8px 12px",
            borderRadius: 8,
            border: `1px solid ${overLimit ? "var(--accent-danger, #ef4444)" : "var(--border)"}`,
            background: "var(--surface)",
            color: "var(--text)",
            fontSize: 13,
            fontFamily: "var(--font-literata)",
            boxSizing: "border-box",
            outline: "none",
          }}
        />
        {refinement && (
          <span style={{
            position: "absolute",
            right: 10,
            top: "50%",
            transform: "translateY(-50%)",
            fontSize: 10,
            color: overLimit ? "var(--accent-danger, #ef4444)" : "var(--text-faint)",
            fontFamily: "var(--font-literata)",
            pointerEvents: "none",
          }}>
            {wordCount}/{MAX_WORDS}
          </span>
        )}
      </div>

      {/* TaskCard on block click */}
      {activeCard && (
        <TaskCard
          item={activeCard.item}
          anchorRect={activeCard.rect}
          onClose={() => setActiveCard(null)}
        />
      )}
    </div>
  );
}
