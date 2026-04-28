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
import MultiDayReviewSummary from "./MultiDayReviewSummary";

type Phase = "review" | "submitting" | "aggregate-loading" | "aggregate";

interface ReviewModalProps {
  token: string;
  dates: string[];          // queue, oldest → newest, length >= 1
  onClose: () => void;
}

interface AggregateData {
  narrative_line: string;
  per_day: Array<{
    schedule_date: string;
    weekday: string;
    tasks_completed: number;
    tasks_total: number;
    rhythms_completed: number;
    rhythms_total: number;
  }>;
}

function weekdayLabelFor(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
}

export default function ReviewModal({ token, dates, onClose }: ReviewModalProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>("review");
  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [taskStates, setTaskStates] = useState<Record<string, ReviewTaskState>>({});
  const [rhythms, setRhythms] = useState<ReviewRhythm[]>([]);
  const [rhythmStates, setRhythmStates] = useState<Record<number, ReviewRhythmState>>({});
  const [aggregate, setAggregate] = useState<AggregateData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeDate = dates[activeIndex];
  const isLastDay = activeIndex === dates.length - 1;

  useEffect(() => {
    let cancelled = false;
    async function preflight() {
      setLoading(true);
      setError(null);
      try {
        const url = `/api/review/preflight?date=${encodeURIComponent(activeDate)}`;
        const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
        if (!res.ok) {
          if (!cancelled) {
            setError("No schedule to review for this day.");
            setLoading(false);
          }
          return;
        }
        const data = await res.json() as { tasks: ReviewTask[]; rhythms: ReviewRhythm[] };
        if (cancelled) return;
        setTasks(data.tasks);
        setTaskStates(Object.fromEntries(
          data.tasks.map(t => [t.task_id, {
            completed: true,
            actual_duration_mins: t.estimated_duration_mins,
            incomplete_reason: null as IncompleteReason,
          }])
        ));
        setRhythms(data.rhythms);
        setRhythmStates(Object.fromEntries(data.rhythms.map(r => [r.id, { completed: null }])));
        setLoading(false);
      } catch {
        if (!cancelled) {
          setError("Something went wrong loading your review.");
          setLoading(false);
        }
      }
    }
    preflight();
    return () => { cancelled = true; };
  }, [token, activeDate]);

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

  async function submitCurrentDay(): Promise<boolean> {
    setPhase("submitting");
    try {
      const payload = {
        schedule_date: activeDate,
        tasks: tasks.map(t => ({
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
          .filter(r => rhythmStates[r.id].completed !== null)
          .map(r => ({ rhythm_id: r.id, completed: rhythmStates[r.id].completed as boolean })),
      };
      const res = await fetch("/api/review/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("Submit failed");
      return true;
    } catch {
      setError("Couldn't save your review. Try again.");
      setPhase("review");
      return false;
    }
  }

  async function fetchAggregate(): Promise<void> {
    setPhase("aggregate-loading");
    try {
      const res = await fetch("/api/review/aggregate", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ schedule_dates: dates }),
      });
      if (!res.ok) throw new Error("Aggregate failed");
      const data = await res.json() as AggregateData;
      setAggregate(data);
      setPhase("aggregate");
    } catch {
      setError("We saved your review but couldn't generate the wrap.");
      setPhase("review");
    }
  }

  async function handleSubmitContinue() {
    const ok = await submitCurrentDay();
    if (!ok) return;
    if (isLastDay) {
      await fetchAggregate();
    } else {
      setActiveIndex(activeIndex + 1);
      setPhase("review");
    }
  }

  async function handleSaveAndExit() {
    const ok = await submitCurrentDay();
    if (ok) onClose();
  }

  const todayLabel = weekdayLabelFor(activeDate);

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
        {phase === "aggregate" && aggregate ? (
          dates.length === 1 ? (
            <ReviewSummary
              summaryLine={aggregate.narrative_line}
              tasksCompleted={aggregate.per_day[0]?.tasks_completed ?? 0}
              tasksTotal={aggregate.per_day[0]?.tasks_total ?? 0}
              timeOverUnder={0}
              rhythmsCompleted={aggregate.per_day[0]?.rhythms_completed ?? 0}
              rhythmsTotal={aggregate.per_day[0]?.rhythms_total ?? 0}
              onClose={onClose}
            />
          ) : (
            <MultiDayReviewSummary aggregate={aggregate} onClose={onClose} />
          )
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
              {dates.length > 1 ? (
                <div style={{
                  fontSize: 10, textTransform: "uppercase", letterSpacing: "0.1em",
                  color: "var(--text-muted, #a88d70)", marginBottom: 4,
                  fontFamily: "var(--font-literata)",
                }}>
                  Day {activeIndex + 1} of {dates.length} · {weekdayLabelFor(activeDate)}
                </div>
              ) : (
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
              )}
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
              <div style={{ padding: "16px 24px 24px", borderTop: "1px solid var(--border)", flexShrink: 0, display: "flex", gap: 8 }}>
                <button
                  onClick={handleSaveAndExit}
                  disabled={phase === "submitting" || phase === "aggregate-loading"}
                  style={{
                    flex: 1, padding: 13, background: "transparent",
                    color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8,
                    fontFamily: "var(--font-literata)", fontSize: 14, fontWeight: 500,
                    cursor: "pointer", letterSpacing: "0.01em",
                  }}
                >
                  Save & exit
                </button>
                <button
                  onClick={handleSubmitContinue}
                  disabled={phase === "submitting" || phase === "aggregate-loading"}
                  style={{
                    flex: 2, padding: 13, background: "var(--text)",
                    color: "var(--surface)", border: "none", borderRadius: 8,
                    fontFamily: "var(--font-literata)", fontSize: 14, fontWeight: 500,
                    cursor: "pointer", letterSpacing: "0.01em",
                    opacity: (phase === "submitting" || phase === "aggregate-loading") ? 0.6 : 1,
                  }}
                >
                  {phase === "submitting" ? "Saving…" : phase === "aggregate-loading" ? "Wrapping up…" : isLastDay ? "Submit & finish" : "Submit & continue →"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
