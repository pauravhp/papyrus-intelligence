"use client";

import { useMemo, useState } from "react";
import NumberField from "@/components/NumberField";
import type {
  DurationMinutes,
  RhythmProposal,
  TaskProposal,
  Weekday,
} from "@/lib/migrationApi";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BLESSED_DURATIONS: readonly DurationMinutes[] = [
  10, 15, 30, 45, 60, 75, 90, 120, 180,
] as const;

const DAYS: readonly Weekday[] = [
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
] as const;

const DAY_LABELS: Record<Weekday, string> = {
  mon: "M",
  tue: "T",
  wed: "W",
  thu: "T",
  fri: "F",
  sat: "S",
  sun: "S",
};

// ---------------------------------------------------------------------------
// Style constants (inline-style pattern matching ConfigCard.tsx)
// ---------------------------------------------------------------------------

const INPUT: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 8,
  padding: "5px 8px",
  fontSize: 13,
  outline: "none",
  width: "100%",
  fontFamily: "var(--font-literata)",
};

const SELECT: React.CSSProperties = {
  ...INPUT,
  width: "auto",
  cursor: "pointer",
  paddingRight: 24,
};

const BUTTON_PRIMARY: React.CSSProperties = {
  background: "var(--accent)",
  color: "#fff",
  border: "none",
  borderRadius: 8,
  padding: "9px 18px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-literata)",
};

const BUTTON_PRIMARY_DISABLED: React.CSSProperties = {
  ...BUTTON_PRIMARY,
  opacity: 0.45,
  cursor: "not-allowed",
};

const BUTTON_SECONDARY: React.CSSProperties = {
  background: "transparent",
  color: "var(--text-muted)",
  border: "1px solid var(--border-strong)",
  borderRadius: 8,
  padding: "9px 18px",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-literata)",
};

const BUTTON_GHOST: React.CSSProperties = {
  background: "transparent",
  color: "var(--text-muted)",
  border: "none",
  padding: "4px 8px",
  fontSize: 12,
  cursor: "pointer",
  borderRadius: 6,
  fontFamily: "var(--font-literata)",
  whiteSpace: "nowrap" as const,
};

const BUTTON_REMOVE: React.CSSProperties = {
  background: "transparent",
  color: "var(--danger)",
  border: "none",
  padding: "2px 6px",
  fontSize: 14,
  cursor: "pointer",
  borderRadius: 6,
  lineHeight: 1,
};

const DAY_CHIP: React.CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: 6,
  border: "1px solid var(--border-strong)",
  background: "var(--surface-raised)",
  color: "var(--text-muted)",
  fontSize: 11,
  fontWeight: 600,
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: "var(--font-literata)",
};

const DAY_CHIP_ON: React.CSSProperties = {
  ...DAY_CHIP,
  background: "var(--accent-tint)",
  border: "1px solid var(--accent)",
  color: "var(--accent)",
};

const SECTION_HEADING: React.CSSProperties = {
  color: "var(--text-muted)",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  marginBottom: 12,
  marginTop: 0,
};

const TABLE: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse" as const,
  tableLayout: "fixed" as const,
};

const TH: React.CSSProperties = {
  textAlign: "left" as const,
  padding: "6px 8px",
  fontSize: 11,
  fontWeight: 600,
  color: "var(--text-faint)",
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  borderBottom: "1px solid var(--border)",
};

const TD: React.CSSProperties = {
  padding: "7px 8px",
  verticalAlign: "top" as const,
  borderBottom: "1px solid var(--border)",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(mins: number): string {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

function nearestBlessed(mins: number): DurationMinutes {
  const sorted = [...BLESSED_DURATIONS].sort(
    (a, b) => Math.abs(a - mins) - Math.abs(b - mins),
  );
  return sorted[0];
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Props = {
  initialTasks: TaskProposal[];
  initialRhythms: RhythmProposal[];
  unmatched: string[];
  onSubmit: (tasks: TaskProposal[], rhythms: RhythmProposal[]) => void;
  onSkip: () => void;
  submitting?: boolean;
};

// ---------------------------------------------------------------------------
// Sub-row: tasks
// ---------------------------------------------------------------------------

function TaskRow({
  task,
  onUpdate,
  onRemove,
  onPromote,
}: {
  task: TaskProposal;
  onUpdate: (patch: Partial<TaskProposal>) => void;
  onRemove: () => void;
  onPromote: () => void;
}) {
  return (
    <tr>
      <td style={{ ...TD, width: 32 }}>
        <button
          style={BUTTON_REMOVE}
          onClick={onRemove}
          aria-label="Remove task"
          title="Remove"
        >
          ✕
        </button>
      </td>
      <td style={TD}>
        <input
          type="text"
          value={task.content}
          onChange={(e) => onUpdate({ content: e.target.value })}
          style={INPUT}
          aria-label="Task name"
        />
      </td>
      <td style={{ ...TD, width: 90 }}>
        <select
          value={task.duration_minutes}
          onChange={(e) =>
            onUpdate({ duration_minutes: Number(e.target.value) as DurationMinutes })
          }
          style={SELECT}
          aria-label="Duration"
        >
          {BLESSED_DURATIONS.map((d) => (
            <option key={d} value={d}>
              {formatDuration(d)}
            </option>
          ))}
        </select>
      </td>
      <td style={{ ...TD, width: 130 }}>
        <input
          type="date"
          value={task.deadline ?? ""}
          onChange={(e) =>
            onUpdate({ deadline: e.target.value === "" ? null : e.target.value })
          }
          style={{ ...INPUT, fontSize: 12 }}
          aria-label="Deadline"
        />
      </td>
      <td style={TD}>
        <span
          style={{
            fontSize: 12,
            fontStyle: "italic",
            color: "var(--text-muted)",
          }}
        >
          {task.reasoning}
        </span>
      </td>
      <td style={{ ...TD, width: 90 }}>
        <button
          style={BUTTON_GHOST}
          onClick={onPromote}
          title="Promote to routine"
          aria-label="Move to routines"
        >
          → Routine
        </button>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Sub-row: rhythms
// ---------------------------------------------------------------------------

function RhythmRow({
  rhythm,
  onUpdate,
  onRemove,
  onDemote,
}: {
  rhythm: RhythmProposal;
  onUpdate: (patch: Partial<RhythmProposal>) => void;
  onRemove: () => void;
  onDemote: () => void;
}) {
  const toggleDay = (day: Weekday) => {
    const current = rhythm.days_of_week;
    const next = current.includes(day)
      ? current.filter((d) => d !== day)
      : [...current, day];
    onUpdate({ days_of_week: next });
  };

  return (
    <tr>
      <td style={{ ...TD, width: 32 }}>
        <button
          style={BUTTON_REMOVE}
          onClick={onRemove}
          aria-label="Remove routine"
          title="Remove"
        >
          ✕
        </button>
      </td>
      <td style={TD}>
        <input
          type="text"
          value={rhythm.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
          style={INPUT}
          aria-label="Routine name"
        />
      </td>
      <td style={{ ...TD, width: 220 }}>
        <div style={{ display: "flex", gap: 3, flexWrap: "wrap" as const }}>
          {DAYS.map((day) => {
            const on = rhythm.days_of_week.includes(day);
            return (
              <button
                key={day}
                style={on ? DAY_CHIP_ON : DAY_CHIP}
                onClick={() => toggleDay(day)}
                aria-pressed={on}
                aria-label={day}
                title={day}
              >
                {DAY_LABELS[day]}
              </button>
            );
          })}
        </div>
      </td>
      <td style={{ ...TD, width: 72 }}>
        <NumberField
          value={rhythm.sessions_per_week}
          onChange={(n) => onUpdate({ sessions_per_week: n })}
          min={1}
          max={21}
          fallback={3}
          style={{ ...INPUT, width: 52 }}
          ariaLabel="Sessions per week"
        />
      </td>
      <td style={{ ...TD, width: 90 }}>
        <select
          value={rhythm.session_min_minutes}
          onChange={(e) =>
            onUpdate({
              session_min_minutes: Number(e.target.value) as DurationMinutes,
            })
          }
          style={SELECT}
          aria-label="Min duration"
        >
          {BLESSED_DURATIONS.map((d) => (
            <option key={d} value={d}>
              {formatDuration(d)}
            </option>
          ))}
        </select>
      </td>
      <td style={{ ...TD, width: 90 }}>
        <select
          value={rhythm.session_max_minutes}
          onChange={(e) =>
            onUpdate({
              session_max_minutes: Number(e.target.value) as DurationMinutes,
            })
          }
          style={SELECT}
          aria-label="Max duration"
        >
          {BLESSED_DURATIONS.map((d) => (
            <option key={d} value={d}>
              {formatDuration(d)}
            </option>
          ))}
        </select>
      </td>
      <td style={TD}>
        <span
          style={{
            fontSize: 12,
            fontStyle: "italic",
            color: "var(--text-muted)",
          }}
        >
          {rhythm.reasoning}
        </span>
      </td>
      <td style={{ ...TD, width: 80 }}>
        <button
          style={BUTTON_GHOST}
          onClick={onDemote}
          title="Demote to task"
          aria-label="Move to tasks"
        >
          → Task
        </button>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function MigrationPreview({
  initialTasks,
  initialRhythms,
  unmatched,
  onSubmit,
  onSkip,
  submitting = false,
}: Props) {
  const [tasks, setTasks] = useState<TaskProposal[]>(initialTasks);
  const [rhythms, setRhythms] = useState<RhythmProposal[]>(initialRhythms);
  const [unmatchedOpen, setUnmatchedOpen] = useState(false);

  // -------------------------------------------------------------------------
  // Task handlers
  // -------------------------------------------------------------------------

  const updateTask = (index: number, patch: Partial<TaskProposal>) => {
    setTasks((prev) =>
      prev.map((t, i) => (i === index ? { ...t, ...patch } : t)),
    );
  };

  const removeTask = (index: number) => {
    setTasks((prev) => prev.filter((_, i) => i !== index));
  };

  const promoteTaskToRhythm = (index: number) => {
    const task = tasks[index];
    const newRhythm: RhythmProposal = {
      name: task.content,
      scheduling_hint: "",
      sessions_per_week: 3,
      days_of_week: ["mon", "tue", "wed", "thu", "fri"],
      session_min_minutes: task.duration_minutes,
      session_max_minutes: task.duration_minutes,
      reasoning: task.reasoning,
    };
    setTasks((prev) => prev.filter((_, i) => i !== index));
    setRhythms((prev) => [...prev, newRhythm]);
  };

  // -------------------------------------------------------------------------
  // Rhythm handlers
  // -------------------------------------------------------------------------

  const updateRhythm = (index: number, patch: Partial<RhythmProposal>) => {
    setRhythms((prev) =>
      prev.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    );
  };

  const removeRhythm = (index: number) => {
    setRhythms((prev) => prev.filter((_, i) => i !== index));
  };

  const demoteRhythmToTask = (index: number) => {
    const rhythm = rhythms[index];
    const newTask: TaskProposal = {
      content: rhythm.name,
      priority: 3,
      duration_minutes: rhythm.session_min_minutes,
      category_label: null,
      deadline: null,
      reasoning: rhythm.reasoning,
    };
    setRhythms((prev) => prev.filter((_, i) => i !== index));
    setTasks((prev) => [...prev, newTask]);
  };

  // -------------------------------------------------------------------------
  // Unmatched handlers
  // -------------------------------------------------------------------------

  const addUnmatchedAsTask = (line: string) => {
    const newTask: TaskProposal = {
      content: line,
      priority: 3,
      duration_minutes: 30,
      category_label: null,
      deadline: null,
      reasoning: "manual entry",
    };
    setTasks((prev) => [...prev, newTask]);
  };

  // -------------------------------------------------------------------------
  // Derived state / validation
  // -------------------------------------------------------------------------

  const isDisabled = useMemo(() => {
    if (submitting) return true;
    if (tasks.length + rhythms.length === 0) return true;
    if (tasks.some((t) => t.content.trim() === "")) return true;
    if (rhythms.some((r) => r.name.trim() === "")) return true;
    return false;
  }, [tasks, rhythms, submitting]);

  const confirmLabel = submitting
    ? "Creating…"
    : `Looks good — create ${tasks.length} ${tasks.length === 1 ? "task" : "tasks"} · ${rhythms.length} ${rhythms.length === 1 ? "routine" : "routines"}`;

  const headerLabel = `I found ${initialTasks.length} ${initialTasks.length === 1 ? "task" : "tasks"} and ${initialRhythms.length} ${initialRhythms.length === 1 ? "routine" : "routines"}`;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "24px 28px",
        display: "flex",
        flexDirection: "column",
        gap: 24,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          justifyContent: "space-between",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: 18,
            fontWeight: 600,
            color: "var(--text)",
            fontFamily: "var(--font-literata)",
          }}
        >
          {headerLabel}
        </h2>
        <a
          href="#"
          onClick={(e) => e.preventDefault()}
          style={{
            fontSize: 12,
            color: "var(--accent)",
            textDecoration: "none",
            whiteSpace: "nowrap",
          }}
        >
          Why these labels?
        </a>
      </div>

      {/* Tasks section */}
      <div>
        <p style={SECTION_HEADING}>Tasks ({tasks.length})</p>
        {tasks.length === 0 ? (
          <p
            style={{
              color: "var(--text-faint)",
              fontSize: 13,
              fontStyle: "italic",
              margin: 0,
            }}
          >
            No tasks yet. Add one from the unmatched section below, or move a
            routine here.
          </p>
        ) : (
          <div style={{ overflowX: "auto" as const }}>
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={{ ...TH, width: 32 }} />
                  <th style={TH}>Name</th>
                  <th style={{ ...TH, width: 90 }}>Duration</th>
                  <th style={{ ...TH, width: 130 }}>Deadline</th>
                  <th style={TH}>Why</th>
                  <th style={{ ...TH, width: 90 }} />
                </tr>
              </thead>
              <tbody>
                {tasks.map((task, i) => (
                  <TaskRow
                    key={i}
                    task={task}
                    onUpdate={(patch) => updateTask(i, patch)}
                    onRemove={() => removeTask(i)}
                    onPromote={() => promoteTaskToRhythm(i)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Rhythms section */}
      <div>
        <p style={SECTION_HEADING}>Routines ({rhythms.length})</p>
        {rhythms.length === 0 ? (
          <p
            style={{
              color: "var(--text-faint)",
              fontSize: 13,
              fontStyle: "italic",
              margin: 0,
            }}
          >
            No routines yet. Move a task here if it repeats regularly.
          </p>
        ) : (
          <div style={{ overflowX: "auto" as const }}>
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={{ ...TH, width: 32 }} />
                  <th style={TH}>Name</th>
                  <th style={{ ...TH, width: 220 }}>Days</th>
                  <th style={{ ...TH, width: 72 }}>Wk</th>
                  <th style={{ ...TH, width: 90 }}>Min</th>
                  <th style={{ ...TH, width: 90 }}>Max</th>
                  <th style={TH}>Why</th>
                  <th style={{ ...TH, width: 80 }} />
                </tr>
              </thead>
              <tbody>
                {rhythms.map((rhythm, i) => (
                  <RhythmRow
                    key={i}
                    rhythm={rhythm}
                    onUpdate={(patch) => updateRhythm(i, patch)}
                    onRemove={() => removeRhythm(i)}
                    onDemote={() => demoteRhythmToTask(i)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Unmatched section */}
      {unmatched.length > 0 && (
        <div>
          <button
            style={{
              ...BUTTON_GHOST,
              padding: "4px 0",
              color: "var(--text-muted)",
              fontSize: 12,
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
            onClick={() => setUnmatchedOpen((v) => !v)}
            aria-expanded={unmatchedOpen}
          >
            <span
              style={{
                display: "inline-block",
                transform: unmatchedOpen ? "rotate(90deg)" : "rotate(0deg)",
                transition: "transform 0.15s ease",
                fontSize: 10,
              }}
            >
              ▶
            </span>
            {unmatched.length} unmatched{" "}
            {unmatched.length === 1 ? "item" : "items"}
          </button>

          {unmatchedOpen && (
            <div
              style={{
                marginTop: 8,
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              {unmatched.map((line, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "6px 10px",
                    background: "var(--surface-raised)",
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                  }}
                >
                  <span
                    style={{
                      flex: 1,
                      fontSize: 13,
                      color: "var(--text-muted)",
                      fontStyle: "italic",
                    }}
                  >
                    {line}
                  </span>
                  <button
                    style={{
                      ...BUTTON_GHOST,
                      color: "var(--accent)",
                      fontSize: 12,
                      padding: "3px 8px",
                      border: "1px solid var(--accent)",
                      borderRadius: 6,
                    }}
                    onClick={() => addUnmatchedAsTask(line)}
                    aria-label={`Add "${line}" as task`}
                  >
                    Add as task
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          gap: 10,
          paddingTop: 4,
          borderTop: "1px solid var(--border)",
        }}
      >
        <button style={BUTTON_SECONDARY} onClick={onSkip} disabled={submitting}>
          I&apos;ll explore on my own
        </button>
        <button
          style={isDisabled ? BUTTON_PRIMARY_DISABLED : BUTTON_PRIMARY}
          onClick={() => !isDisabled && onSubmit(tasks, rhythms)}
          disabled={isDisabled}
          aria-disabled={isDisabled}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}
