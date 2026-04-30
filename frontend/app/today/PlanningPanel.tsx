"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { usePostHog } from "posthog-js/react";
import { createClient } from "@/utils/supabase/client";
import { type ScheduledItem } from "./TodayPage";

export type PanelStatus = "working" | "proposal" | "confirmed";

interface PlanningPanelProps {
  token: string;
  contextNote?: string;
  targetDate?: "today" | "tomorrow";
  onScheduleProposed: (
    schedule: ScheduledItem[],
    autoShiftToTomorrowSuggested: boolean,
    pushed: Array<{ task_id: string; task_name?: string; reason: string }>,
  ) => void;
  onConfirm: () => void;
  onClose: () => void;
}

interface Block {
  start_iso: string;
  end_iso: string;
  source?: string;
}

interface Proposal {
  scheduled: ScheduledItem[];
  pushed: Array<{ task_id: string; task_name?: string; reason: string }>;
  reasoning_summary: string;
  free_windows_used: Array<{ start: string; end: string; duration_minutes: number }>;
  blocks?: Block[];
  cutoff_override?: string | null;
  auto_shift_to_tomorrow_suggested?: boolean;
}

const PROGRESS_STEPS = [
  "Reading your calendar",
  "Fetching tasks from Todoist",
  "Building your schedule",
  "Drafting reasoning",
];

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

// Best-effort parse of FastAPI's structured error envelope. Returns the
// detail.code string when the server raised HTTPException(400, {code, message}),
// e.g. "todoist_reconnect_required" or "google_reconnect_required". Returns
// null when the body is missing, malformed, or doesn't carry a code.
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

// Best-effort extraction of a human-readable detail string. FastAPI's default
// HTTPException emits {detail: "<string>"}; uvicorn's 500 page is HTML.
async function parseErrorMessage(res: Response): Promise<string | null> {
  try {
    const json = await res.clone().json();
    if (typeof json?.detail === "string") return json.detail;
  } catch { /* HTML body */ }
  return null;
}

export default function PlanningPanel({
  token,
  contextNote,
  targetDate = "today",
  onScheduleProposed,
  onConfirm,
  onClose,
}: PlanningPanelProps) {
  const [status, setStatus] = useState<PanelStatus>("working");
  const [progressStep, setProgressStep] = useState(0);
  const [reasoning, setReasoning] = useState<string>("");
  const [refinementInput, setRefinementInput] = useState("");
  const [refineLoading, setRefineLoading] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  // Soft "still working" hint shown after ~25s of working state. Distinct
  // from planError — the request hasn't failed, it's just slow. Reset on
  // every retry so the timer restarts.
  const [slowHint, setSlowHint] = useState(false);
  const [needsTodoistReconnect, setNeedsTodoistReconnect] = useState(false);
  const [needsGcalReconnect, setNeedsGcalReconnect] = useState(false);
  // True between Confirm-click and confirmed state. Drives the button's
  // disabled + "Confirming…" label so users can't double-fire the write.
  const [isConfirming, setIsConfirming] = useState(false);
  const streamRef = useRef<HTMLDivElement>(null);
  const refinementRef = useRef<HTMLTextAreaElement>(null);
  const hasFired = useRef(false);
  const isConfirmingRef = useRef(false);
  const posthog = usePostHog();

  // Advance progress steps on a timer while working
  useEffect(() => {
    if (status !== "working") return;
    if (progressStep >= PROGRESS_STEPS.length - 1) return;
    const t = setTimeout(() => setProgressStep((s) => s + 1), 1200);
    return () => clearTimeout(t);
  }, [status, progressStep]);

  // After ~25 seconds of working state, hint that it's slow. Most plan calls
  // resolve in 5-12s; past 25s we want the user to know we're not stuck.
  // Reset is handled in runPlan/runRefine where we re-enter the working state.
  useEffect(() => {
    if (status !== "working") return;
    const t = setTimeout(() => setSlowHint(true), 25000);
    return () => clearTimeout(t);
  }, [status]);

  // Fire the planning request exactly once on mount
  useEffect(() => {
    if (hasFired.current) return;
    hasFired.current = true;
    runPlan();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runPlan() {
    setPlanError(null);
    setProgressStep(0);
    setSlowHint(false);
    setStatus("working");
    try {
      const res = await fetch(`${API_BASE}/api/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ target_date: targetDate, context_note: contextNote ?? null }),
      });
      if (!res.ok) {
        const code = await parseErrorCode(res);
        if (code === "todoist_reconnect_required") {
          setNeedsTodoistReconnect(true);
          setStatus("proposal");
          return;
        }
        if (code === "gcal_reconnect_required") {
          setNeedsGcalReconnect(true);
          setStatus("proposal");
          return;
        }
        const msg = await parseErrorMessage(res);
        throw new Error(msg ?? `Server error (${res.status})`);
      }
      const data: Proposal = await res.json();
      setProposal(data);
      setReasoning(data.reasoning_summary);
      setProgressStep(PROGRESS_STEPS.length - 1);
      onScheduleProposed(data.scheduled ?? [], data.auto_shift_to_tomorrow_suggested === true, data.pushed ?? []);
      posthog?.capture("schedule_proposed", {
        task_count: (data.scheduled ?? []).length,
      });
      setStatus("proposal");
    } catch (err) {
      setPlanError((err as Error).message);
      setStatus("proposal");
    }
  }

  async function runRefine(message: string) {
    if (!proposal) return;
    try {
      const res = await fetch(`${API_BASE}/api/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          target_date: targetDate,
          previous_proposal: {
            scheduled: proposal.scheduled,
            pushed: proposal.pushed,
            blocks: proposal.blocks ?? [],
            cutoff_override: proposal.cutoff_override ?? null,
          },
          refinement_message: message,
          original_context_note: contextNote ?? null,
        }),
      });
      if (!res.ok) {
        const code = await parseErrorCode(res);
        if (code === "todoist_reconnect_required") {
          setNeedsTodoistReconnect(true);
          setStatus("proposal");
          return;
        }
        if (code === "gcal_reconnect_required") {
          setNeedsGcalReconnect(true);
          setStatus("proposal");
          return;
        }
        throw new Error(`API error: ${res.status}`);
      }
      const data: Proposal = await res.json();
      setProposal(data);
      setReasoning(data.reasoning_summary);
      onScheduleProposed(data.scheduled ?? [], data.auto_shift_to_tomorrow_suggested === true, data.pushed ?? []);
      setStatus("proposal");
    } catch (err) {
      setPlanError(`Refine failed: ${(err as Error).message}`);
      setStatus("proposal");
    }
  }

  async function handleConfirm() {
    if (isConfirmingRef.current || !proposal) return;
    isConfirmingRef.current = true;
    setIsConfirming(true);
    try {
      const res = await fetch(`${API_BASE}/api/plan/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          target_date: targetDate,
          schedule: { scheduled: proposal.scheduled, pushed: proposal.pushed },
        }),
      });
      if (!res.ok) {
        const code = await parseErrorCode(res);
        if (code === "todoist_reconnect_required") {
          setNeedsTodoistReconnect(true);
          setStatus("proposal");
          isConfirmingRef.current = false;
          setIsConfirming(false);
          return;
        }
        if (code === "gcal_reconnect_required") {
          setNeedsGcalReconnect(true);
          setStatus("proposal");
          isConfirmingRef.current = false;
          setIsConfirming(false);
          return;
        }
        throw new Error(`API error: ${res.status}`);
      }
      setStatus("confirmed");
      setTimeout(() => onConfirm(), 1200);
      // Note: leaving isConfirming=true through the success-state transition
      // so the button never reverts to active before the panel unmounts.
    } catch (err) {
      console.error("Confirm failed:", err);
      isConfirmingRef.current = false;
      setIsConfirming(false);
      setReasoning("Confirm failed — please try again.");
    }
  }

  async function handleTodoistReconnect() {
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    const sessionToken = data.session?.access_token ?? token;
    window.location.href = `${API_BASE}/auth/todoist?token=${sessionToken}&redirect_after=${encodeURIComponent("/today")}`;
  }

  async function handleGcalReconnect() {
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    const sessionToken = data.session?.access_token ?? token;
    window.location.href = `${API_BASE}/auth/google?token=${sessionToken}&redirect_after=${encodeURIComponent("/today")}`;
  }

  async function handleRefinement() {
    const message = refinementInput.trim();
    if (!message || refineLoading) return;
    setRefinementInput("");
    setRefineLoading(true);
    setSlowHint(false);
    setStatus("working");
    setProgressStep(2); // Jump to "Building your schedule"
    // Event name retained as "chat_message_sent" for continuity with existing
    // PostHog dashboards — semantically this captures "user submitted a
    // refinement," which is the only message-sending surface that exists
    // post-chat-agent removal.
    posthog?.capture("chat_message_sent");
    await runRefine(message);
    setRefineLoading(false);
  }

  // ── RENDER: Working state ────────────────────────────────────────
  if (status === "working") {
    return (
      <div className="planning-panel-shell" style={panelShell}>
        <PanelHeader onClose={onClose} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "32px 24px", gap: 20 }}>
          <div style={{ width: 44, height: 44, borderRadius: 12, background: "var(--accent-tint)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)" }}>
            <CalendarIcon />
          </div>
          <p style={{ fontSize: 14, color: "var(--text-muted)", fontStyle: "italic", fontFamily: "var(--font-literata)" }}>
            Planning your day…
          </p>
          <div style={{ display: "flex", gap: 6 }}>
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                animate={{ opacity: [0.25, 1, 0.25], y: [0, -3, 0] }}
                transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.18 }}
                style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", display: "inline-block" }}
              />
            ))}
          </div>
          {slowHint && (
            <p style={{ fontSize: 11, color: "var(--text-faint)", fontStyle: "italic", textAlign: "center", maxWidth: 240, fontFamily: "var(--font-literata)", lineHeight: 1.5 }}>
              Taking longer than usual — still working.
            </p>
          )}
          <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 10 }}>
            {PROGRESS_STEPS.map((step, i) => (
              <div key={step} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <motion.span
                  animate={i <= progressStep ? { background: "var(--accent)" } : { background: "rgba(44,26,14,0.15)" }}
                  transition={{ duration: 0.3 }}
                  style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, display: "inline-block" }}
                />
                <span style={{
                  fontSize: 12,
                  fontFamily: "var(--font-literata)",
                  color: i < progressStep ? "var(--text-muted)"
                        : i === progressStep ? "var(--text)"
                        : "var(--text-faint)",
                }}>
                  {step}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── RENDER: Proposal state ───────────────────────────────────────
  if (status === "proposal") {
    return (
      <div className="planning-panel-shell" style={panelShell}>
        <PanelHeader onClose={onClose} />

        {/* Reasoning stream */}
        <div
          ref={streamRef}
          style={{ flex: 1, overflowY: "auto", padding: "18px 18px 12px", display: "flex", flexDirection: "column", gap: 14, scrollbarWidth: "none" }}
        >
          {/* User context note (if provided) */}
          {contextNote && (
            <div
              style={{
                alignSelf: "flex-end",
                maxWidth: "90%",
                padding: "8px 13px",
                borderRadius: "12px 12px 3px 12px",
                background: "var(--accent-tint)",
                border: "1px solid rgba(196,130,26,0.18)",
                fontSize: 13,
                color: "var(--text)",
                lineHeight: 1.5,
                fontFamily: "var(--font-literata)",
              }}
            >
              {contextNote}
            </div>
          )}

          {/* Todoist reconnect surface — mirrors CalendarSection.tsx */}
          {needsTodoistReconnect && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5, marginBottom: 12, fontFamily: "var(--font-literata)" }}>
                Your Todoist connection has expired.<br />
                <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
                  Reconnect to continue planning — your settings will stay intact.
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

          {/* Google Calendar reconnect surface — same shape as the Todoist banner */}
          {needsGcalReconnect && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5, marginBottom: 12, fontFamily: "var(--font-literata)" }}>
                Your Google Calendar connection needs reconnecting.<br />
                <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
                  We&apos;ve added a permission for the Papyrus calendar — your settings stay intact.
                </span>
              </p>
              <button
                onClick={handleGcalReconnect}
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
                Reconnect Google Calendar
              </button>
            </div>
          )}

          {/* Agent reasoning — prose, not bubbles */}
          {!needsTodoistReconnect && !needsGcalReconnect && (planError ? (
            <div
              style={{
                background: "var(--surface-raised)",
                border: "1px solid #d4a55a",
                borderRadius: 10,
                padding: 14,
                display: "flex",
                gap: 12,
                alignItems: "flex-start",
              }}
            >
              <div style={{ background: "rgba(212,165,90,0.15)", padding: 8, borderRadius: 8, flexShrink: 0, color: "#d4a55a", display: "flex" }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>
                  <line x1="12" y1="9" x2="12" y2="13"/>
                  <line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
              </div>
              <div style={{ flex: 1 }}>
                <p style={{ fontSize: 13, color: "var(--text)", fontWeight: 500, fontFamily: "var(--font-literata)" }}>
                  Planning didn’t finish
                </p>
                <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.55, fontFamily: "var(--font-literata)" }}>
                  {planError}
                </p>
                <button
                  onClick={runPlan}
                  style={{
                    marginTop: 10,
                    background: "var(--accent)",
                    color: "var(--bg)",
                    border: "none",
                    padding: "6px 12px",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 500,
                    fontFamily: "var(--font-literata)",
                    cursor: "pointer",
                  }}
                >
                  Try again
                </button>
              </div>
            </div>
          ) : (
            reasoning && (
              <div>
                <p style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--accent)", marginBottom: 8, fontFamily: "var(--font-literata)" }}>
                  Papyrus
                </p>
                <p style={{ fontSize: 13, lineHeight: 1.8, color: "var(--text-muted)", fontStyle: "italic", fontFamily: "var(--font-literata)", whiteSpace: "pre-wrap" }}>
                  {reasoning}
                </p>
              </div>
            )
          ))}
        </div>

        {/* Footer */}
        <div style={{ padding: "12px 16px 18px", borderTop: "1px solid var(--border)", flexShrink: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {!planError && !needsTodoistReconnect && !needsGcalReconnect && (
            <button
              onClick={handleConfirm}
              disabled={isConfirming}
              aria-busy={isConfirming}
              style={{
                width: "100%",
                padding: "10px 0",
                background: isConfirming ? "var(--accent-tint)" : "var(--accent)",
                color: isConfirming ? "var(--accent)" : "var(--bg)",
                border: "none",
                borderRadius: 9,
                fontFamily: "var(--font-literata)",
                fontSize: 13,
                cursor: isConfirming ? "default" : "pointer",
                letterSpacing: "0.01em",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                opacity: isConfirming ? 0.85 : 1,
                transition: "background 0.15s, opacity 0.15s",
              }}
            >
              {isConfirming && (
                <motion.span
                  aria-hidden="true"
                  animate={{ rotate: 360 }}
                  transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    border: "1.5px solid currentColor",
                    borderTopColor: "transparent",
                    display: "inline-block",
                  }}
                />
              )}
              {isConfirming ? "Confirming…" : "Confirm schedule"}
            </button>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "flex-end",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: 11,
                padding: "7px 8px 7px 13px",
              }}
            >
              <textarea
                ref={refinementRef}
                value={refinementInput}
                onChange={(e) => {
                  setRefinementInput(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 80)}px`;
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleRefinement();
                  }
                }}
                placeholder="Move gym to 7am, remove a task…"
                disabled={refineLoading}
                rows={1}
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  fontFamily: "var(--font-literata)",
                  fontSize: 13,
                  color: "var(--text)",
                  resize: "none",
                  overflow: "hidden",
                  height: 20,
                }}
              />
              <button
                onClick={handleRefinement}
                disabled={refineLoading || !refinementInput.trim()}
                style={{
                  width: 26, height: 26,
                  borderRadius: 7,
                  background: refineLoading || !refinementInput.trim() ? "var(--accent-tint)" : "var(--accent)",
                  border: "none",
                  color: refineLoading || !refinementInput.trim() ? "var(--accent)" : "var(--bg)",
                  cursor: refineLoading || !refinementInput.trim() ? "not-allowed" : "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0,
                }}
                aria-label="Send refinement"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="12" y1="19" x2="12" y2="5"/>
                  <polyline points="5 12 12 5 19 12"/>
                </svg>
              </button>
            </div>
            <p style={{ fontSize: 10, color: "var(--text-faint)", fontStyle: "italic", paddingLeft: 3, fontFamily: "var(--font-literata)" }}>
              Refine the schedule above or ask a question
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── RENDER: Confirmed state ──────────────────────────────────────
  return (
    <div className="planning-panel-shell" style={panelShell}>
      <PanelHeader onClose={onClose} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, padding: "32px 24px" }}>
        <motion.div
          initial={{ scale: 0.7, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 200, damping: 16 }}
          style={{ width: 44, height: 44, borderRadius: 12, background: "var(--accent-tint)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)" }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </motion.div>
        <motion.p
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          style={{ fontSize: 15, color: "var(--text)", fontFamily: "var(--font-literata)", fontStyle: "italic" }}
        >
          Scheduled
        </motion.p>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
          style={{ fontSize: 12, color: "var(--text-faint)", fontFamily: "var(--font-literata)" }}
        >
          Events written to Google Calendar
        </motion.p>
      </div>
    </div>
  );
}

// ── Shared shell style ───────────────────────────────────────────
// width applied via .planning-panel-shell class (340px desktop, fluid on mobile)
const panelShell: React.CSSProperties = {
  height: "100%",
  flexShrink: 0,
  background: "var(--surface)",
  borderLeft: "1px solid var(--border)",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
};

// ── Shared header ────────────────────────────────────────────────
function PanelHeader({ onClose }: { onClose: () => void }) {
  return (
    <div style={{ padding: "18px 18px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-faint)", fontFamily: "var(--font-literata)" }}>
        Planning
      </span>
      <button
        onClick={onClose}
        style={{ width: 26, height: 26, borderRadius: 7, border: "none", background: "transparent", color: "var(--text-faint)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}
        aria-label="Close planning panel"
      >
        ✕
      </button>
    </div>
  );
}

function CalendarIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2"/>
      <line x1="16" y1="2" x2="16" y2="6"/>
      <line x1="8" y1="2" x2="8" y2="6"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
  );
}

// Export for use in Tasks 10 and 11 additions
export { panelShell, PanelHeader };
