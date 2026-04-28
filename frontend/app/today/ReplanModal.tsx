// frontend/app/dashboard/today/ReplanModal.tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { type ScheduledItem } from "./TodayPage";
import TaskTriageBlock, { type TriageState } from "./TaskTriageBlock";
import ProposedCalendar from "./ProposedCalendar";
import { createClient } from "@/utils/supabase/client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

const MAX_WORDS = 40;
function countWords(s: string): number {
  return s.trim() === "" ? 0 : s.trim().split(/\s+/).length;
}

// Mirrors PlanningPanel.tsx — surfaces FastAPI's structured 400 detail.code
// (e.g. "todoist_reconnect_required") so the modal can render the dedicated
// reconnect surface instead of a generic error toast.
async function parseErrorCode(res: Response): Promise<string | null> {
  try {
    const json = await res.clone().json();
    if (json?.detail && typeof json.detail === "object" && typeof json.detail.code === "string") {
      return json.detail.code;
    }
  } catch {
    /* non-JSON body */
  }
  return null;
}

interface ReplanModalProps {
  afternoonTasks: ScheduledItem[];
  token: string;
  onClose: () => void;
  onConfirm: () => void;
}

type Phase = "triage" | "loading" | "proposed";

interface ProposedBlock {
  start_iso: string;
  end_iso: string;
  source?: string;
}

interface ProposedResult {
  scheduled: ScheduledItem[];
  pushed: Array<{ task_id: string; reason: string }>;
  reasoning_summary: string;
  blocks?: ProposedBlock[];
  cutoff_override?: string | null;
}

function PushedSummary({ pushed }: { pushed: Array<{ task_id: string; reason: string }> }) {
  if (pushed.length === 0) return null;

  const buckets = { duration: 0, calendar: 0, other: 0 };
  for (const p of pushed) {
    if (/duration/i.test(p.reason)) buckets.duration++;
    else if (/calendar/i.test(p.reason)) buckets.calendar++;
    else buckets.other++;
  }

  const lines: string[] = [];
  if (buckets.duration) lines.push(`${buckets.duration} need a duration estimate in Todoist`);
  if (buckets.calendar) lines.push(`${buckets.calendar} already on your calendar`);
  if (buckets.other) lines.push(`${buckets.other} didn't fit today`);

  return (
    <div
      style={{
        marginTop: 16,
        padding: "10px 12px",
        borderTop: "1px solid var(--border)",
      }}
    >
      <p
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-faint)",
          marginBottom: 4,
          fontFamily: "var(--font-literata)",
        }}
      >
        Couldn&apos;t place ({pushed.length})
      </p>
      {lines.map((line) => (
        <p
          key={line}
          style={{
            fontSize: 12,
            color: "var(--text-faint)",
            fontFamily: "var(--font-literata)",
            lineHeight: 1.5,
            margin: 0,
          }}
        >
          {line}
        </p>
      ))}
    </div>
  );
}

export default function ReplanModal({
  afternoonTasks,
  token,
  onClose,
  onConfirm,
}: ReplanModalProps) {
  const [phase, setPhase] = useState<Phase>("triage");
  // task_id -> state; default to "keep"
  const [triageStates, setTriageStates] = useState<Record<string, TriageState>>(
    () => Object.fromEntries(afternoonTasks.map((t) => [t.task_id, "keep"]))
  );
  // Pre-flight: track which tasks were auto-set by Todoist
  const [todistDone, setTodoistDone] = useState<Set<string>>(new Set());
  const [contextNote, setContextNote] = useState("");
  const [proposed, setProposed] = useState<ProposedResult | null>(null);
  const [isRefining, setIsRefining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsTodoistReconnect, setNeedsTodoistReconnect] = useState(false);

  async function handleTodoistReconnect() {
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    const sessionToken = data.session?.access_token ?? token;
    window.location.href = `${API_BASE}/auth/todoist?token=${sessionToken}&redirect_after=${encodeURIComponent("/today")}`;
  }

  const dialogRef = useRef<HTMLDivElement>(null);
  const noteWordCount = countWords(contextNote);
  const noteOverLimit = noteWordCount > MAX_WORDS;
  // Replan is always enabled — even if all tasks are done/tomorrow, backlog fills the rest of the day

  // Fetch Todoist pre-flight on mount
  useEffect(() => {
    async function preflight() {
      try {
        const res = await fetch(`${API_BASE}/api/replan/preflight`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ task_ids: afternoonTasks.map((t) => t.task_id) }),
        });
        if (res.ok) {
          const { completed_ids } = await res.json() as { completed_ids: string[] };
          const doneSet = new Set(completed_ids);
          setTodoistDone(doneSet);
          setTriageStates((prev) => {
            const next = { ...prev };
            for (const tid of completed_ids) {
              next[tid] = "done";
            }
            return next;
          });
        }
      } catch {
        // Silently skip — user can toggle manually
      }
    }
    if (afternoonTasks.length > 0) preflight();
  }, [afternoonTasks, token]);

  // Focus trap + Escape key
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const handleTriageChange = useCallback((id: string, state: TriageState) => {
    setTriageStates((prev) => ({ ...prev, [id]: state }));
  }, []);

  async function submitReplan(refinementMessage?: string) {
    setPhase("loading");
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/replan`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          task_states: triageStates,
          context_note: contextNote,
          refinement_message: refinementMessage ?? null,
        }),
      });
      if (!res.ok) {
        if ((await parseErrorCode(res)) === "todoist_reconnect_required") {
          setNeedsTodoistReconnect(true);
          setPhase("triage");
          return;
        }
        const detail = (await res.json().catch(() => ({}))).detail ?? "Replan failed.";
        throw new Error(typeof detail === "string" ? detail : "Replan failed.");
      }
      const result = await res.json() as ProposedResult;
      setProposed(result);
      setPhase("proposed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setPhase("triage");
    }
  }

  async function handleRefinement(message: string) {
    setIsRefining(true);
    setPhase("loading");
    try {
      const res = await fetch(`${API_BASE}/api/replan`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          task_states: triageStates,
          context_note: contextNote,
          refinement_message: message,
          previous_proposal: proposed
            ? {
                scheduled: proposed.scheduled,
                pushed: proposed.pushed,
                blocks: proposed.blocks ?? [],
                cutoff_override: proposed.cutoff_override ?? null,
              }
            : null,
        }),
      });
      if (!res.ok) {
        if ((await parseErrorCode(res)) === "todoist_reconnect_required") {
          setNeedsTodoistReconnect(true);
          setPhase("proposed");
          return;
        }
        const detail = (await res.json().catch(() => ({}))).detail ?? "Refinement failed.";
        throw new Error(typeof detail === "string" ? detail : "Refinement failed.");
      }
      const result = await res.json() as ProposedResult;
      setProposed(result);
      setPhase("proposed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setPhase("proposed");
    } finally {
      setIsRefining(false);
    }
  }

  async function handleConfirm() {
    if (!proposed) return;
    setPhase("loading");
    try {
      const tomorrowIds = Object.entries(triageStates)
        .filter(([, s]) => s === "tomorrow")
        .map(([id]) => id);

      const res = await fetch(`${API_BASE}/api/replan/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ schedule: proposed, tomorrow_task_ids: tomorrowIds }),
      });
      if (!res.ok) {
        if ((await parseErrorCode(res)) === "todoist_reconnect_required") {
          setNeedsTodoistReconnect(true);
          setPhase("proposed");
          return;
        }
        const detail = (await res.json().catch(() => ({}))).detail ?? "Confirm failed.";
        throw new Error(typeof detail === "string" ? detail : "Confirm failed.");
      }
      onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setPhase("proposed");
    }
  }

  return (
    // Backdrop
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        backdropFilter: "blur(4px)",
        background: "rgba(0,0,0,0.3)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: "16px",
      }}
    >
      {/* Dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Replan your afternoon"
        tabIndex={-1}
        className="replan-dialog"
        style={{
          background: "var(--surface)",
          borderRadius: 16,
          width: "100%",
          maxWidth: 580,
          maxHeight: "85vh",
          overflowY: "auto",
          outline: "none",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <h2
            className="font-display"
            style={{ fontSize: 22, letterSpacing: "-0.02em", color: "var(--text)" }}
          >
            {phase === "proposed" ? "Proposed afternoon" : "Replan afternoon"}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close modal"
            style={{
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              fontSize: 18,
              cursor: "pointer",
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        {error && !needsTodoistReconnect && (
          <p style={{ color: "var(--accent-danger, #ef4444)", fontSize: 13, marginBottom: 16, fontFamily: "var(--font-literata)" }}>
            {error}
          </p>
        )}

        {needsTodoistReconnect && (
          <div style={{ marginBottom: 16 }}>
            <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5, marginBottom: 12, fontFamily: "var(--font-literata)" }}>
              Your Todoist connection has expired.<br />
              <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
                Reconnect to continue replanning — your triage choices stay intact.
              </span>
            </p>
            <button
              onClick={handleTodoistReconnect}
              style={{
                padding: "7px 14px",
                background: "transparent",
                color: "var(--accent)",
                border: "1px solid var(--accent)",
                borderRadius: 8,
                fontFamily: "var(--font-literata)",
                fontSize: 12,
                cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              Reconnect Todoist
            </button>
          </div>
        )}

        {/* Phase content */}
        <AnimatePresence mode="wait">
          {phase === "triage" && (
            <motion.div
              key="triage"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -14 }}
              transition={{ duration: 0.24 }}
            >
              {afternoonTasks.length === 0 ? (
                <p style={{ fontSize: 13, color: "var(--text-faint)", fontStyle: "italic", fontFamily: "var(--font-literata)", marginBottom: 16 }}>
                  No afternoon tasks found in today&apos;s schedule.
                </p>
              ) : (
                <div style={{ marginBottom: 16 }}>
                  {afternoonTasks.map((task) => (
                    <TaskTriageBlock
                      key={task.task_id}
                      item={task}
                      state={triageStates[task.task_id] ?? "keep"}
                      onStateChange={handleTriageChange}
                      fromTodoist={todistDone.has(task.task_id)}
                    />
                  ))}
                </div>
              )}

              {/* Context note */}
              <div style={{ marginBottom: 20 }}>
                <textarea
                  value={contextNote}
                  onChange={(e) => setContextNote(e.target.value)}
                  placeholder="Anything the app should know? e.g. 'running behind, skip the gym'"
                  rows={3}
                  aria-label="Context note for replanning"
                  style={{
                    width: "100%",
                    padding: "8px 12px",
                    borderRadius: 8,
                    border: `1px solid ${noteOverLimit ? "var(--accent-danger, #ef4444)" : "var(--border)"}`,
                    background: "var(--surface)",
                    color: "var(--text)",
                    fontSize: 13,
                    fontFamily: "var(--font-literata)",
                    resize: "vertical",
                    boxSizing: "border-box",
                    outline: "none",
                  }}
                />
                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
                  <span style={{
                    fontSize: 11,
                    color: noteOverLimit ? "var(--accent-danger, #ef4444)" : "var(--text-faint)",
                    fontFamily: "var(--font-literata)",
                  }}>
                    {noteWordCount}/{MAX_WORDS} words
                  </span>
                </div>
              </div>

              <button
                onClick={() => submitReplan()}
                disabled={noteOverLimit}
                aria-disabled={noteOverLimit}
                style={{
                  width: "100%",
                  padding: "10px 0",
                  background: !noteOverLimit ? "var(--accent)" : "var(--border)",
                  color: !noteOverLimit ? "var(--surface)" : "var(--text-faint)",
                  border: "none",
                  borderRadius: 8,
                  fontSize: 14,
                  fontFamily: "var(--font-literata)",
                  fontWeight: 500,
                  cursor: !noteOverLimit ? "pointer" : "not-allowed",
                }}
              >
                Replan →
              </button>
            </motion.div>
          )}

          {phase === "loading" && (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              aria-busy="true"
              style={{ padding: "32px 0", display: "flex", flexDirection: "column", gap: 10 }}
            >
              {[120, 80, 100, 60].map((w, i) => (
                <motion.div
                  key={i}
                  animate={{ opacity: [0.4, 0.7, 0.4] }}
                  transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.15 }}
                  style={{
                    height: 22,
                    width: `${w}%`,
                    maxWidth: "100%",
                    borderRadius: 6,
                    background: "var(--border)",
                  }}
                />
              ))}
            </motion.div>
          )}

          {phase === "proposed" && proposed && (
            <motion.div
              key="proposed"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -14 }}
              transition={{ duration: 0.24 }}
            >
              <ProposedCalendar
                scheduled={proposed.scheduled}
                reasoningSummary={proposed.reasoning_summary}
                onRefinement={handleRefinement}
                isRefining={isRefining}
              />

              <PushedSummary pushed={proposed.pushed} />

              <button
                onClick={handleConfirm}
                style={{
                  width: "100%",
                  padding: "10px 0",
                  background: "var(--accent)",
                  color: "var(--surface)",
                  border: "none",
                  borderRadius: 8,
                  fontSize: 14,
                  fontFamily: "var(--font-literata)",
                  fontWeight: 500,
                  cursor: "pointer",
                  marginTop: 20,
                }}
              >
                Confirm schedule
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
