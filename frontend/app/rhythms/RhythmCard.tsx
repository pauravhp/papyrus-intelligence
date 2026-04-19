// frontend/app/dashboard/rhythms/RhythmCard.tsx
"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Pencil, Trash2, GripVertical } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

export interface Rhythm {
  id: number;
  rhythm_name: string;
  description: string | null;
  sessions_per_week: number;
  session_min_minutes: number;
  session_max_minutes: number;
  end_date: string | null;
  sort_order: number;
}

const DAYS = ["M", "T", "W", "T", "F", "S", "S"];

// Which day indices (0=Mon … 6=Sun) are "active" for each sessions_per_week value.
const DOT_INDICES: Record<number, number[]> = {
  1: [3],
  2: [1, 4],
  3: [0, 2, 4],
  4: [0, 1, 3, 4],
  5: [0, 1, 2, 3, 4],
  6: [0, 1, 2, 3, 4, 5],
  7: [0, 1, 2, 3, 4, 5, 6],
};

interface Props {
  rhythm: Rhythm;
  onEdit: (rhythm: Rhythm) => void;
  onDelete: (id: number) => void;
}

export default function RhythmCard({ rhythm, onEdit, onDelete }: Props) {
  const [hovered, setHovered] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: rhythm.id });

  const activeDots = DOT_INDICES[rhythm.sessions_per_week] ?? [];

  const formatEndDate = (d: string) => {
    // Parse as local date to avoid UTC offset shifting the day
    const [year, month, day] = d.split("-").map(Number);
    const date = new Date(year, month - 1, day);
    return date.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  };

  return (
    <motion.div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "20px 22px",
        position: "relative",
        opacity: isDragging ? 0.45 : 1,
        zIndex: isDragging ? 10 : undefined,
      }}
      animate={{
        boxShadow: isDragging
          ? "0 8px 28px rgba(44,26,14,0.16)"
          : hovered
          ? "0 2px 12px rgba(44,26,14,0.06)"
          : "none",
        borderColor: hovered ? "var(--border-strong)" : "var(--border)",
      }}
      onHoverStart={() => setHovered(true)}
      onHoverEnd={() => setHovered(false)}
    >
      {/* Hover actions: drag handle + edit + delete */}
      <AnimatePresence>
        {hovered && !confirmDelete && (
          <motion.div
            key="actions"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            style={{
              position: "absolute",
              top: 14,
              right: 14,
              display: "flex",
              gap: 4,
              alignItems: "center",
            }}
          >
            {/* Drag handle */}
            <div
              {...attributes}
              {...listeners}
              title="Drag to reorder"
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text-faint)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "grab",
              }}
            >
              <GripVertical size={13} />
            </div>

            {/* Edit */}
            <motion.button
              onClick={() => onEdit(rhythm)}
              title="Edit"
              whileHover={{ background: "var(--surface-raised)" }}
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text-muted)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
              }}
            >
              <Pencil size={12} />
            </motion.button>

            {/* Delete */}
            <motion.button
              onClick={() => setConfirmDelete(true)}
              title="Delete"
              whileHover={{ background: "var(--danger-tint)" }}
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                border: "1px solid var(--border)",
                background: "var(--bg)",
                color: "var(--text-muted)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
              }}
            >
              <Trash2 size={12} />
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Top row: name + duration pill */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: rhythm.description ? 4 : 14,
        }}
      >
        <span
          className="font-display"
          style={{ fontSize: 19, color: "var(--text)", letterSpacing: "-0.01em" }}
        >
          {rhythm.rhythm_name}
        </span>
        <span
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            background: "var(--surface-raised)",
            borderRadius: 5,
            padding: "2px 8px",
            fontStyle: "italic",
          }}
        >
          {rhythm.session_min_minutes}–{rhythm.session_max_minutes} min
        </span>
      </div>

      {/* Scheduling hint — only rendered when set */}
      {rhythm.description && (
        <p
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            fontStyle: "italic",
            lineHeight: 1.45,
            marginBottom: 14,
          }}
        >
          {rhythm.description}
        </p>
      )}

      {/* Body: cadence number + week grid */}
      <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
        {/* Big N× number */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            minWidth: 52,
          }}
        >
          <span
            className="font-display"
            style={{
              fontSize: 36,
              color: "var(--accent)",
              lineHeight: 1,
              letterSpacing: "-0.02em",
            }}
          >
            {rhythm.sessions_per_week}×
          </span>
          <span
            style={{
              fontSize: 9,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              color: "var(--text-faint)",
              marginTop: 3,
              whiteSpace: "nowrap",
            }}
          >
            per week
          </span>
        </div>

        {/* Week dot grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(7, 1fr)",
            gap: 4,
            flex: 1,
          }}
        >
          {DAYS.map((day, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 5,
              }}
            >
              <span
                style={{
                  fontSize: 9,
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  color: "var(--text-faint)",
                }}
              >
                {day}
              </span>
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: activeDots.includes(i)
                    ? "var(--accent)"
                    : "var(--border-strong)",
                  transition: "background 0.15s",
                }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* End date note */}
      {rhythm.end_date && (
        <p
          style={{
            marginTop: 12,
            fontSize: 11,
            color: "var(--text-faint)",
            fontStyle: "italic",
          }}
        >
          Ends {formatEndDate(rhythm.end_date)}
        </p>
      )}

      {/* Inline delete confirm */}
      <AnimatePresence>
        {confirmDelete && (
          <motion.div
            key="confirm"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.14 }}
            style={{
              marginTop: 14,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 10px",
              background: "var(--danger-tint)",
              borderRadius: 7,
              border: "1px solid rgba(139, 46, 46, 0.15)",
            }}
          >
            <span style={{ fontSize: 12, color: "var(--danger)" }}>
              Remove this rhythm?
            </span>
            <button
              onClick={() => onDelete(rhythm.id)}
              style={{
                fontSize: 12,
                color: "var(--danger)",
                background: "none",
                border: "none",
                cursor: "pointer",
                textDecoration: "underline",
                fontFamily: "var(--font-literata)",
              }}
            >
              Yes, remove
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                background: "none",
                border: "none",
                cursor: "pointer",
                fontFamily: "var(--font-literata)",
              }}
            >
              Cancel
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
