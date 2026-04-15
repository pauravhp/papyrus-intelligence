// frontend/app/dashboard/today/ReviewTaskRow.tsx

export interface ReviewTask {
  task_id: string;
  task_name: string;
  estimated_duration_mins: number;
  scheduled_at: string;
  already_completed_in_todoist: boolean;
}

export type IncompleteReason =
  | "ran_out_of_time"
  | "deprioritized"
  | "blocked"
  | "scope_grew"
  | "low_energy"
  | "forgot"
  | null;

export interface ReviewTaskState {
  completed: boolean;
  actual_duration_mins: number;
  incomplete_reason: IncompleteReason;
}

interface ReviewTaskRowProps {
  task: ReviewTask;
  state: ReviewTaskState;
  onChange: (taskId: string, update: Partial<ReviewTaskState>) => void;
}

const REASONS: { value: IncompleteReason; label: string }[] = [
  { value: "ran_out_of_time", label: "Ran out of time" },
  { value: "deprioritized", label: "Deprioritized" },
  { value: "blocked", label: "Blocked" },
  { value: "scope_grew", label: "Scope grew" },
  { value: "low_energy", label: "Low energy" },
  { value: "forgot", label: "Forgot" },
];

const MIN_DURATION = 15;

export default function ReviewTaskRow({ task, state, onChange }: ReviewTaskRowProps) {
  const { completed, actual_duration_mins, incomplete_reason } = state;

  function toggleDone() {
    onChange(task.task_id, {
      completed: !completed,
      actual_duration_mins: !completed ? task.estimated_duration_mins : actual_duration_mins,
      incomplete_reason: !completed ? null : incomplete_reason,
    });
  }

  function adjustTime(delta: number) {
    const next = Math.max(MIN_DURATION, actual_duration_mins + delta);
    onChange(task.task_id, { actual_duration_mins: next });
  }

  const isOver = completed && actual_duration_mins > task.estimated_duration_mins;

  return (
    <div style={{ borderBottom: "1px solid var(--border)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 0",
          paddingBottom: completed ? "10px" : "6px",
        }}
      >
        {/* Done toggle */}
        <button
          onClick={toggleDone}
          aria-label={completed ? "Mark incomplete" : "Mark complete"}
          style={{
            width: 24,
            height: 24,
            borderRadius: "50%",
            border: `1.5px solid ${completed ? "var(--accent)" : "var(--border)"}`,
            background: completed ? "var(--accent-soft, #f0e0c0)" : "var(--surface-raised, #fff9f0)",
            cursor: "pointer",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
            color: "var(--accent)",
            transition: "all 0.15s",
          }}
        >
          {completed ? "✓" : ""}
        </button>

        {/* Task name */}
        <span
          style={{
            flex: 1,
            fontSize: 14,
            fontFamily: "var(--font-literata)",
            color: completed ? "var(--text-muted, #a88d70)" : "var(--text)",
            textDecoration: completed ? "line-through" : "none",
            textDecorationColor: "var(--text-muted, #a88d70)",
          }}
        >
          {task.task_name}
        </span>

        {/* Time control */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
          <button
            onClick={() => adjustTime(-15)}
            disabled={!completed}
            aria-label="Subtract 15 minutes"
            style={{
              width: 26, height: 26,
              borderRadius: 6,
              border: "1px solid var(--border)",
              background: "var(--surface-raised, #fff9f0)",
              color: "var(--text-secondary, #7a5c3e)",
              fontSize: 16,
              cursor: completed ? "pointer" : "default",
              opacity: completed ? 1 : 0.28,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}
          >
            −
          </button>
          <div style={{ textAlign: "center", minWidth: 52 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 500,
                fontFamily: "var(--font-literata)",
                color: completed
                  ? isOver ? "var(--accent)" : "var(--text)"
                  : "var(--text-muted, #a88d70)",
              }}
            >
              {completed ? `${actual_duration_mins} min` : "—"}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-muted, #a88d70)", marginTop: 1 }}>
              est. {task.estimated_duration_mins}
            </div>
          </div>
          <button
            onClick={() => adjustTime(15)}
            disabled={!completed}
            aria-label="Add 15 minutes"
            style={{
              width: 26, height: 26,
              borderRadius: 6,
              border: "1px solid var(--border)",
              background: "var(--surface-raised, #fff9f0)",
              color: "var(--text-secondary, #7a5c3e)",
              fontSize: 16,
              cursor: completed ? "pointer" : "default",
              opacity: completed ? 1 : 0.28,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}
          >
            +
          </button>
        </div>
      </div>

      {/* Reason dropdown — only when not completed */}
      <div
        style={{
          overflow: "hidden",
          maxHeight: completed ? 0 : 40,
          transition: "max-height 0.2s ease",
          paddingLeft: 36,
          paddingBottom: completed ? 0 : 10,
        }}
      >
        <select
          value={incomplete_reason ?? ""}
          onChange={(e) =>
            onChange(task.task_id, {
              incomplete_reason: (e.target.value as IncompleteReason) || null,
            })
          }
          style={{
            fontFamily: "var(--font-literata)",
            fontSize: 12,
            color: "var(--text-secondary, #7a5c3e)",
            background: "var(--surface-raised, #fff9f0)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "5px 10px",
            width: "100%",
            cursor: "pointer",
            appearance: "none",
          }}
        >
          <option value="">Why not? (optional)</option>
          {REASONS.map((r) => (
            <option key={r.value} value={r.value ?? ""}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
