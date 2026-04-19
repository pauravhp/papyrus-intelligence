// frontend/app/dashboard/today/ReviewModal.tsx
"use client";

import { useEffect, useState } from "react";
import ReviewTaskRow, {
  ReviewTask,
  ReviewTaskState,
  IncompleteReason,
} from "./ReviewTaskRow";
import ReviewRhythmRow, { ReviewRhythm, ReviewRhythmState } from "./ReviewRhythmRow";
import ReviewSummary from "./ReviewSummary";

type Phase = "review" | "submitting" | "summary";

interface ReviewModalProps {
  token: string;
  onClose: () => void;
}

interface SummaryData {
  summaryLine: string;
  tasksCompleted: number;
  tasksTotal: number;
  timeOverUnder: number;
  rhythmsCompleted: number;
  rhythmsTotal: number;
}

export default function ReviewModal({ token, onClose }: ReviewModalProps) {
  const [phase, setPhase] = useState<Phase>("review");
  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [taskStates, setTaskStates] = useState<Record<string, ReviewTaskState>>({});
  const [rhythms, setRhythms] = useState<ReviewRhythm[]>([]);
  const [rhythmStates, setRhythmStates] = useState<Record<number, ReviewRhythmState>>({});
  const [summaryData, setSummaryData] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function preflight() {
      try {
        const res = await fetch("/api/review/preflight", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          setError("No schedule to review today.");
          setLoading(false);
          return;
        }
        const data = await res.json() as {
          tasks: ReviewTask[];
          rhythms: ReviewRhythm[];
        };

        setTasks(data.tasks);
        setTaskStates(
          Object.fromEntries(
            data.tasks.map((t) => [
              t.task_id,
              {
                completed: true,
                actual_duration_mins: t.estimated_duration_mins,
                incomplete_reason: null as IncompleteReason,
              },
            ])
          )
        );
        setRhythms(data.rhythms);
        setRhythmStates(
          Object.fromEntries(data.rhythms.map((r) => [r.id, { completed: null }]))
        );
        setLoading(false);
      } catch {
        setError("Something went wrong loading your review.");
        setLoading(false);
      }
    }
    preflight();
  }, [token]);

  function updateTaskState(taskId: string, update: Partial<ReviewTaskState>) {
    setTaskStates((prev) => ({
      ...prev,
      [taskId]: { ...prev[taskId], ...update },
    }));
  }

  function updateRhythmState(rhythmId: number, completed: boolean) {
    setRhythmStates((prev) => ({
      ...prev,
      [rhythmId]: { completed },
    }));
  }

  async function handleSubmit() {
    setPhase("submitting");
    try {
      const payload = {
        tasks: tasks.map((t) => ({
          task_id: t.task_id,
          task_name: t.task_name,
          completed: taskStates[t.task_id].completed,
          actual_duration_mins: taskStates[t.task_id].completed
            ? taskStates[t.task_id].actual_duration_mins
            : null,
          estimated_duration_mins: t.estimated_duration_mins,
          scheduled_at: t.scheduled_at,
          incomplete_reason: taskStates[t.task_id].incomplete_reason ?? null,
        })),
        rhythms: rhythms
          .filter((r) => rhythmStates[r.id].completed !== null)
          .map((r) => ({
            rhythm_id: r.id,
            completed: rhythmStates[r.id].completed as boolean,
          })),
      };

      const res = await fetch("/api/review/submit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error("Submit failed");
      const result = await res.json() as { saved: boolean; summary_line: string };

      const completedTasks = Object.values(taskStates).filter((s) => s.completed);
      const completedActualTotal = completedTasks.reduce(
        (sum, s) => sum + (s.actual_duration_mins ?? 0),
        0
      );
      const estimatedTotal = tasks.reduce((sum, t) => sum + t.estimated_duration_mins, 0);

      setSummaryData({
        summaryLine: result.summary_line,
        tasksCompleted: completedTasks.length,
        tasksTotal: tasks.length,
        timeOverUnder: completedActualTotal - estimatedTotal,
        rhythmsCompleted: rhythms.filter((r) => rhythmStates[r.id].completed === true).length,
        rhythmsTotal: rhythms.length,
      });
      setPhase("summary");
    } catch {
      setError("Couldn't save your review. Try again.");
      setPhase("review");
    }
  }

  const todayLabel = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="End of day review"
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "oklch(0.15 0.03 60 / 0.4)",
        zIndex: 50,
        padding: "0 16px",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          width: "100%",
          maxWidth: 480,
          overflow: "hidden",
          boxShadow: "0 4px 24px oklch(0.2 0.04 60 / 0.1)",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {phase === "summary" && summaryData ? (
          <ReviewSummary {...summaryData} onClose={onClose} />
        ) : (
          <>
            {/* Header */}
            <div
              style={{
                padding: "24px 24px 16px",
                borderBottom: "1px solid var(--border)",
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: "var(--text-muted, #a88d70)",
                  marginBottom: 4,
                  fontFamily: "var(--font-literata)",
                }}
              >
                {todayLabel}
              </div>
              <div
                style={{
                  fontFamily: "var(--font-gilda, var(--font-display))",
                  fontSize: 22,
                  fontWeight: 400,
                  color: "var(--text)",
                  lineHeight: 1.2,
                }}
              >
                How did today go?
              </div>
            </div>

            {/* Body */}
            <div style={{ overflowY: "auto", padding: "16px 24px", flex: 1 }}>
              {loading ? (
                <div style={{ color: "var(--text-muted)", fontSize: 14, fontFamily: "var(--font-literata)", padding: "16px 0" }}>
                  Loading your day…
                </div>
              ) : error ? (
                <div style={{ color: "var(--text-muted)", fontSize: 14, fontFamily: "var(--font-literata)", padding: "16px 0" }}>
                  {error}
                </div>
              ) : (
                <>
                  <div
                    style={{
                      fontSize: 10,
                      textTransform: "uppercase",
                      letterSpacing: "0.1em",
                      color: "var(--text-muted, #a88d70)",
                      marginBottom: 16,
                    }}
                  >
                    Tasks
                  </div>

                  {tasks.map((task) => (
                    <ReviewTaskRow
                      key={task.task_id}
                      task={task}
                      state={taskStates[task.task_id]}
                      onChange={updateTaskState}
                    />
                  ))}

                  {rhythms.length > 0 && (
                    <>
                      <div
                        style={{
                          height: 1,
                          background: "var(--border)",
                          margin: "24px 0 0",
                        }}
                      />
                      <div
                        style={{
                          fontSize: 10,
                          textTransform: "uppercase",
                          letterSpacing: "0.1em",
                          color: "var(--text-muted, #a88d70)",
                          margin: "16px 0",
                        }}
                      >
                        Rhythms
                      </div>
                      {rhythms.map((rhythm) => (
                        <ReviewRhythmRow
                          key={rhythm.id}
                          rhythm={rhythm}
                          state={rhythmStates[rhythm.id]}
                          onChange={updateRhythmState}
                        />
                      ))}
                    </>
                  )}
                </>
              )}
            </div>

            {/* Footer */}
            {!loading && !error && (
              <div
                style={{
                  padding: "16px 24px 24px",
                  borderTop: "1px solid var(--border)",
                  flexShrink: 0,
                }}
              >
                <button
                  onClick={handleSubmit}
                  disabled={phase === "submitting"}
                  style={{
                    width: "100%",
                    padding: 13,
                    background: "var(--text)",
                    color: "var(--surface)",
                    border: "none",
                    borderRadius: 8,
                    fontFamily: "var(--font-literata)",
                    fontSize: 14,
                    fontWeight: 500,
                    cursor: phase === "submitting" ? "default" : "pointer",
                    opacity: phase === "submitting" ? 0.6 : 1,
                    letterSpacing: "0.01em",
                    transition: "opacity 0.15s",
                  }}
                >
                  {phase === "submitting" ? "Saving…" : "Save & wrap up"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
