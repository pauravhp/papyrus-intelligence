"use client";

import { useReducer, useRef, useCallback, useEffect } from "react";
import { createClient } from "@/utils/supabase/client";
import { ApiError } from "@/utils/api";
import {
  convertMigration,
  commitMigration,
  runPlanForToday,
  confirmPapyrusSchedule,
} from "@/lib/migrationApi";
import type {
  ConvertResponse,
  CommitResponse,
  TaskProposal,
  RhythmProposal,
  PlanResponse,
} from "@/lib/migrationApi";
import MigrationPreview from "@/components/MigrationPreview";
import DemoTour from "@/components/DemoTour";
import PapyrusCalendarConfirm from "@/components/PapyrusCalendarConfirm";

// ---------------------------------------------------------------------------
// Variant type — keep all three for forward-compatibility
// v2 threshold gate will wire labels_only_card and skip_entirely
// ---------------------------------------------------------------------------

export type Variant = "paste" | "labels_only_card" | "skip_entirely";

// ---------------------------------------------------------------------------
// Reducer state machine
// ---------------------------------------------------------------------------

type Phase =
  | { tag: "idle" }
  | { tag: "parsing" }
  | { tag: "parse_error"; message: string }
  | {
      tag: "reveal";
      tasks: TaskProposal[];
      rhythms: RhythmProposal[];
      unmatched: string[];
    }
  | { tag: "committing"; tasks: TaskProposal[]; rhythms: RhythmProposal[] }
  | { tag: "post_commit"; result: CommitResponse }
  | { tag: "post_commit_reconnect" }
  | { tag: "post_commit_error"; tasks: TaskProposal[]; rhythms: RhythmProposal[] }
  | { tag: "auto_planning"; result: CommitResponse }
  | { tag: "auto_plan_failed"; result: CommitResponse; message: string }
  | { tag: "schedule_walkthrough"; result: CommitResponse; plan: PlanResponse }
  | { tag: "settings_nudge"; result: CommitResponse; plan: PlanResponse }
  | { tag: "gcal_confirm"; result: CommitResponse; plan: PlanResponse }
  | { tag: "gcal_confirming"; result: CommitResponse; plan: PlanResponse }
  | { tag: "gcal_done"; result: CommitResponse; plan: PlanResponse }
  | { tag: "exited" };

type State = {
  rawText: string;
  phase: Phase;
};

type Action =
  | { type: "SET_RAW_TEXT"; text: string }
  | { type: "PARSE_START" }
  | { type: "PARSE_SUCCESS"; data: ConvertResponse }
  | { type: "PARSE_ERROR"; message: string }
  | { type: "RESET_TO_IDLE" }
  | { type: "COMMIT_START"; tasks: TaskProposal[]; rhythms: RhythmProposal[] }
  | { type: "COMMIT_SUCCESS"; result: CommitResponse }
  | { type: "COMMIT_RECONNECT_REQUIRED" }
  | { type: "COMMIT_ERROR"; tasks: TaskProposal[]; rhythms: RhythmProposal[] }
  | { type: "RETRY_FROM_REVEAL"; tasks: TaskProposal[]; rhythms: RhythmProposal[] }
  | { type: "AUTO_PLAN_START"; result: CommitResponse }
  | { type: "AUTO_PLAN_OK"; result: CommitResponse; plan: PlanResponse }
  | { type: "AUTO_PLAN_FAIL"; result: CommitResponse; message: string }
  | { type: "NUDGE_SKIP" }
  | { type: "TO_GCAL_CONFIRM" }
  | { type: "GCAL_CONFIRM_START" }
  | { type: "GCAL_CONFIRM_OK" }
  | { type: "RE_OAUTH" }
  | { type: "EXIT" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "SET_RAW_TEXT":
      return { ...state, rawText: action.text };

    case "PARSE_START":
      return { ...state, phase: { tag: "parsing" } };

    case "PARSE_SUCCESS":
      return {
        ...state,
        phase: {
          tag: "reveal",
          tasks: action.data.tasks,
          rhythms: action.data.rhythms,
          unmatched: action.data.unmatched,
        },
      };

    case "PARSE_ERROR":
      return { ...state, phase: { tag: "parse_error", message: action.message } };

    case "RESET_TO_IDLE":
      return { ...state, phase: { tag: "idle" } };

    case "COMMIT_START":
      return {
        ...state,
        phase: { tag: "committing", tasks: action.tasks, rhythms: action.rhythms },
      };

    case "COMMIT_SUCCESS":
      return { ...state, phase: { tag: "post_commit", result: action.result } };

    case "COMMIT_RECONNECT_REQUIRED":
      return { ...state, phase: { tag: "post_commit_reconnect" } };

    case "COMMIT_ERROR":
      return {
        ...state,
        phase: { tag: "post_commit_error", tasks: action.tasks, rhythms: action.rhythms },
      };

    case "RETRY_FROM_REVEAL":
      return {
        ...state,
        phase: {
          tag: "reveal",
          tasks: action.tasks,
          rhythms: action.rhythms,
          unmatched: [],
        },
      };

    case "AUTO_PLAN_START":
      return { ...state, phase: { tag: "auto_planning", result: action.result } };

    case "AUTO_PLAN_OK":
      return { ...state, phase: { tag: "schedule_walkthrough", result: action.result, plan: action.plan } };

    case "AUTO_PLAN_FAIL":
      return { ...state, phase: { tag: "auto_plan_failed", result: action.result, message: action.message } };

    case "TO_GCAL_CONFIRM": {
      const p = state.phase;
      if (p.tag === "schedule_walkthrough" || p.tag === "settings_nudge") {
        return { ...state, phase: { tag: "gcal_confirm", result: p.result, plan: p.plan } };
      }
      return state;
    }

    case "NUDGE_SKIP": {
      const p = state.phase;
      if (p.tag === "settings_nudge") {
        return { ...state, phase: { tag: "gcal_confirm", result: p.result, plan: p.plan } };
      }
      return state;
    }

    case "GCAL_CONFIRM_START": {
      const p = state.phase;
      if (p.tag === "gcal_confirm") {
        return { ...state, phase: { tag: "gcal_confirming", result: p.result, plan: p.plan } };
      }
      return state;
    }

    case "GCAL_CONFIRM_OK": {
      const p = state.phase;
      if (p.tag === "gcal_confirming") {
        return { ...state, phase: { tag: "gcal_done", result: p.result, plan: p.plan } };
      }
      return state;
    }

    case "RE_OAUTH":
      return state; // side-effect handled in handler, state unchanged

    case "EXIT":
      return { ...state, phase: { tag: "exited" } };

    default:
      return state;
  }
}

const initialState: State = {
  rawText: "",
  phase: { tag: "idle" },
};

// ---------------------------------------------------------------------------
// Inline style constants — parchment theme with CSS variables
// ---------------------------------------------------------------------------

const CARD: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  padding: "24px",
  maxWidth: 680,
  margin: "0 auto",
};

const HEADING: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 700,
  color: "var(--text)",
  marginBottom: 6,
  fontFamily: "var(--font-literata)",
};

const SUBHEADING: React.CSSProperties = {
  fontSize: 13,
  color: "var(--text-muted)",
  marginBottom: 20,
  lineHeight: 1.5,
  fontFamily: "var(--font-literata)",
};

const TEXTAREA: React.CSSProperties = {
  width: "100%",
  minHeight: 180,
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "12px",
  fontSize: 13,
  color: "var(--text)",
  resize: "vertical" as const,
  outline: "none",
  fontFamily: "var(--font-literata)",
  lineHeight: 1.6,
  boxSizing: "border-box" as const,
};

const BTN_PRIMARY: React.CSSProperties = {
  background: "var(--accent)",
  color: "#fff",
  border: "none",
  borderRadius: 8,
  padding: "9px 20px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "var(--font-literata)",
};

const BTN_PRIMARY_DISABLED: React.CSSProperties = {
  ...BTN_PRIMARY,
  opacity: 0.45,
  cursor: "not-allowed",
};

const BTN_SECONDARY: React.CSSProperties = {
  background: "transparent",
  color: "var(--text-muted)",
  border: "1px solid var(--border-strong)",
  borderRadius: 8,
  padding: "9px 20px",
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "var(--font-literata)",
};

const SPINNER_WRAP: React.CSSProperties = {
  display: "flex",
  flexDirection: "column" as const,
  alignItems: "center",
  justifyContent: "center",
  padding: "48px 24px",
  gap: 14,
};

const SPINNER: React.CSSProperties = {
  width: 28,
  height: 28,
  border: "3px solid var(--border)",
  borderTopColor: "var(--accent)",
  borderRadius: "50%",
  animation: "spin 0.8s linear infinite",
};

const ERROR_BOX: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--danger, #e5534b)",
  borderRadius: 8,
  padding: "16px",
  marginBottom: 16,
};

const NOTE: React.CSSProperties = {
  fontSize: 12,
  color: "var(--text-faint)",
  fontFamily: "var(--font-literata)",
  lineHeight: 1.5,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Props = {
  variant: Variant;
  onComplete: () => void;
};

export default function ImportStage({ variant, onComplete }: Props) {
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;

  const [state, dispatch] = useReducer(reducer, initialState);

  // ---------------------------------------------------------------------------
  // Token helper — fetched fresh per call, never stored in state
  // ---------------------------------------------------------------------------

  async function getToken(): Promise<string> {
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? "";
  }

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleParse = useCallback(async () => {
    dispatch({ type: "PARSE_START" });
    try {
      const token = await getToken();
      const data = await convertMigration(state.rawText, token);
      dispatch({ type: "PARSE_SUCCESS", data });
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : "Something went wrong — please try again.";
      dispatch({ type: "PARSE_ERROR", message: msg });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.rawText]);

  const handleCommit = useCallback(
    async (tasks: TaskProposal[], rhythms: RhythmProposal[]) => {
      dispatch({ type: "COMMIT_START", tasks, rhythms });
      try {
        const token = await getToken();
        const result = await commitMigration(tasks, rhythms, token);
        dispatch({ type: "COMMIT_SUCCESS", result });
      } catch (err) {
        if (err instanceof ApiError && err.code === "todoist_reconnect_required") {
          dispatch({ type: "COMMIT_RECONNECT_REQUIRED" });
        } else {
          dispatch({ type: "COMMIT_ERROR", tasks, rhythms });
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const handleSkipOut = useCallback(() => {
    dispatch({ type: "EXIT" });
    onComplete();
  }, [onComplete]);

  // ---------------------------------------------------------------------------
  // Auto-plan: triggered when phase transitions to post_commit
  // ---------------------------------------------------------------------------

  const autoPlanFiredRef = useRef(false);

  useEffect(() => {
    const p = state.phase;
    if (p.tag !== "post_commit") return;
    if (autoPlanFiredRef.current) return;
    autoPlanFiredRef.current = true;
    const result = p.result;
    dispatch({ type: "AUTO_PLAN_START", result });
    (async () => {
      try {
        const token = await getToken();
        const plan = await runPlanForToday(token);
        dispatch({ type: "AUTO_PLAN_OK", result, plan });
      } catch {
        dispatch({ type: "AUTO_PLAN_FAIL", result, message: "Couldn't generate a plan." });
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase]);

  // ---------------------------------------------------------------------------
  // GCal confirm handler
  // ---------------------------------------------------------------------------

  const handleGcalConfirm = useCallback(async () => {
    dispatch({ type: "GCAL_CONFIRM_START" });
    // Read the current phase AFTER dispatch — but we dispatch first and then
    // read from the current state snapshot to get result/plan.
    // Since useReducer state is captured at call time, we use a closure trick:
    // The state variable here is the snapshot from the last render.
    const p = state.phase;
    if (p.tag !== "gcal_confirm") return;
    const { result, plan } = p;
    try {
      const token = await getToken();
      if (result.papyrus_calendar_id) {
        await confirmPapyrusSchedule(
          { scheduled: plan.scheduled, pushed: plan.pushed },
          result.papyrus_calendar_id,
          token,
        );
      }
      dispatch({ type: "GCAL_CONFIRM_OK" });
    } catch {
      // On failure, silently advance to done — the schedule is already in memory
      dispatch({ type: "GCAL_CONFIRM_OK" });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase]);

  // ---------------------------------------------------------------------------
  // ReOAuth handler — new-tab + try-again approach (v1 simplest)
  // ---------------------------------------------------------------------------

  const handleReOAuth = useCallback(() => {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
    // Open OAuth in a new tab so the user can grant calendar.app.created scope
    // without losing in-memory state. After granting, they close the tab and
    // click "Try again" which re-runs confirmPapyrusSchedule.
    window.open(`${API_BASE}/auth/google?prompt=consent`, "_blank");
  }, []);

  // ---------------------------------------------------------------------------
  // Variant: skip_entirely — defensive guard (should never reach here in v1)
  // ---------------------------------------------------------------------------

  // Must come before any conditional returns to satisfy Rules of Hooks
  useEffect(() => {
    if (variant === "skip_entirely") {
      onComplete();
    }
  }, [variant, onComplete]);

  if (variant === "skip_entirely") {
    return null;
  }

  // ---------------------------------------------------------------------------
  // Variant: labels_only_card — stub for v2
  // ---------------------------------------------------------------------------

  if (variant === "labels_only_card") {
    return (
      <div style={CARD}>
        <p style={HEADING}>Label your tasks</p>
        <p style={SUBHEADING}>
          You have Todoist tasks without categories. Quick-labelling coming in v2.
        </p>
        <button style={BTN_SECONDARY} onClick={onComplete}>
          Skip for now
        </button>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Variant: paste — full import flow
  // ---------------------------------------------------------------------------

  const { phase } = state;

  // Exited terminal state
  if (phase.tag === "exited") {
    return null;
  }

  // Post-commit: Todoist reconnect required
  if (phase.tag === "post_commit_reconnect") {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
    async function handleReconnect() {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? "";
      window.location.href = `${API_BASE}/auth/todoist?token=${encodeURIComponent(token)}&redirect_after=${encodeURIComponent("/onboard")}`;
    }

    return (
      <div style={CARD}>
        <p style={HEADING}>Todoist connection expired</p>
        <p style={SUBHEADING}>
          Your Todoist connection has expired. Reconnect to save your tasks — your
          previewed data will still be here after reconnecting.
        </p>
        <button
          style={{
            padding: "7px 14px",
            background: "transparent",
            color: "var(--accent)",
            border: "1px solid var(--accent)",
            borderRadius: 8,
            fontFamily: "var(--font-literata)",
            fontSize: 12,
            cursor: "pointer",
          }}
          onClick={handleReconnect}
        >
          Reconnect Todoist
        </button>
      </div>
    );
  }

  // Post-commit: generic commit error → retry back to reveal
  if (phase.tag === "post_commit_error") {
    const { tasks, rhythms } = phase;
    return (
      <div style={CARD}>
        <div style={ERROR_BOX}>
          <p
            style={{
              fontSize: 13,
              color: "var(--danger, #e5534b)",
              margin: 0,
              fontFamily: "var(--font-literata)",
            }}
          >
            Couldn&apos;t save — please try again.
          </p>
        </div>
        <button
          style={BTN_PRIMARY}
          onClick={() => dispatch({ type: "RETRY_FROM_REVEAL", tasks, rhythms })}
        >
          Try again
        </button>
      </div>
    );
  }

  // Post-commit: success — auto-plan fires immediately via useEffect, show spinner
  if (phase.tag === "post_commit") {
    const { result } = phase;
    return (
      <div style={CARD}>
        <DemoTour step="post_commit" anchor={null} onSkip={handleSkipOut} />
        <div style={SPINNER_WRAP}>
          <div style={SPINNER} />
          <p style={{ ...NOTE, marginTop: 0 }}>
            Imported {result.tasks_created} task{result.tasks_created !== 1 ? "s" : ""}
            {result.rhythms_created > 0
              ? ` and ${result.rhythms_created} rhythm${result.rhythms_created !== 1 ? "s" : ""}`
              : ""}
            . Generating today&apos;s schedule…
          </p>
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  // Auto-planning spinner
  if (phase.tag === "auto_planning") {
    return (
      <div style={CARD}>
        <DemoTour step="auto_plan" anchor={null} onSkip={handleSkipOut} />
        <div style={SPINNER_WRAP}>
          <div style={SPINNER} />
          <p style={{ ...NOTE, marginTop: 0 }}>Generating today&apos;s schedule from what you just imported…</p>
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  // Auto-plan failed
  if (phase.tag === "auto_plan_failed") {
    return (
      <div style={CARD}>
        <DemoTour step="schedule_walkthrough_failed" anchor={null} onSkip={handleSkipOut} />
        <div style={{ marginTop: 16 }}>
          <button style={BTN_PRIMARY} onClick={handleSkipOut}>
            Take me to dashboard
          </button>
        </div>
      </div>
    );
  }

  // Schedule walkthrough — read-only list + DemoTour bubble
  if (phase.tag === "schedule_walkthrough") {
    const { plan } = phase;
    return (
      <div style={CARD}>
        <DemoTour
          step="schedule_walkthrough"
          anchor={null}
          variables={{ summary: plan.reasoning_summary }}
          onSkip={handleSkipOut}
        />
        <p style={HEADING}>Today&apos;s schedule</p>
        {plan.scheduled.length === 0 ? (
          <p style={{ ...NOTE }}>No tasks could be scheduled for today.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: "0 0 20px", display: "flex", flexDirection: "column", gap: 8 }}>
            {plan.scheduled.map((item, i) => (
              <li
                key={i}
                style={{
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "10px 14px",
                  fontFamily: "var(--font-literata)",
                }}
              >
                <span style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>
                  {item.task_name}
                </span>
                <span style={{ color: "var(--text-muted)", fontSize: 12, marginLeft: 8 }}>
                  {fmtTime(item.start_time)}–{fmtTime(item.end_time)} ({item.duration_minutes}m)
                </span>
                {item.reasoning && (
                  <em style={{ display: "block", color: "var(--text-faint)", fontSize: 12, marginTop: 2, fontStyle: "italic" }}>
                    {item.reasoning}
                  </em>
                )}
              </li>
            ))}
          </ul>
        )}
        {plan.pushed.length > 0 && (
          <p style={{ ...NOTE, marginBottom: 16 }}>
            {plan.pushed.length} task{plan.pushed.length !== 1 ? "s" : ""} pushed to tomorrow.
          </p>
        )}
        <div style={{ display: "flex", gap: 10 }}>
          <button
            style={BTN_PRIMARY}
            onClick={() => dispatch({ type: "TO_GCAL_CONFIRM" })}
          >
            Continue
          </button>
          <button style={BTN_SECONDARY} onClick={handleSkipOut}>
            I&apos;ll explore on my own
          </button>
        </div>
      </div>
    );
  }

  // Settings nudge
  if (phase.tag === "settings_nudge") {
    return (
      <div style={CARD}>
        <DemoTour step="settings_nudge" anchor={null} onSkip={handleSkipOut} />
        <p style={HEADING}>Quick settings check</p>
        <p style={{ ...NOTE, marginBottom: 16 }}>
          I used some defaults — meal times, end-of-day cutoff. Want to fine-tune?
        </p>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            style={BTN_PRIMARY}
            onClick={() => dispatch({ type: "NUDGE_SKIP" })}
          >
            Skip — looks good
          </button>
          <button
            style={BTN_SECONDARY}
            onClick={() => window.open("/dashboard/settings", "_blank")}
          >
            Open settings
          </button>
        </div>
      </div>
    );
  }

  // GCal confirm
  if (phase.tag === "gcal_confirm") {
    const { result } = phase;
    return (
      <PapyrusCalendarConfirm
        calendarId={result.papyrus_calendar_id}
        scopeUpgradeRequired={result.calendar_scope_upgrade_required}
        onConfirm={handleGcalConfirm}
        onSkip={handleSkipOut}
        onReOAuth={handleReOAuth}
        loading={false}
      />
    );
  }

  // GCal confirming (loading)
  if (phase.tag === "gcal_confirming") {
    const { result } = phase;
    return (
      <PapyrusCalendarConfirm
        calendarId={result.papyrus_calendar_id}
        scopeUpgradeRequired={result.calendar_scope_upgrade_required}
        onConfirm={handleGcalConfirm}
        onSkip={handleSkipOut}
        onReOAuth={handleReOAuth}
        loading={true}
      />
    );
  }

  // GCal done — terminal
  if (phase.tag === "gcal_done") {
    return (
      <div style={CARD}>
        <DemoTour step="done" anchor={null} onSkip={handleSkipOut} />
        <p style={HEADING}>You&apos;re all set</p>
        <p style={{ ...NOTE, marginBottom: 16 }}>
          Tomorrow morning, come back and hit Plan today.
        </p>
        <button style={BTN_PRIMARY} onClick={onComplete}>
          Go to dashboard
        </button>
      </div>
    );
  }

  // Committing spinner
  if (phase.tag === "committing") {
    return (
      <div style={CARD}>
        <div style={SPINNER_WRAP}>
          <div style={SPINNER} />
          <p style={{ ...NOTE, marginTop: 0 }}>Saving to Todoist and Papyrus…</p>
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  // Reveal: MigrationPreview + DemoTour overlay
  if (phase.tag === "reveal") {
    const { tasks, rhythms, unmatched } = phase;
    const tasksN = tasks.length;
    const rhythmsN = rhythms.length;

    return (
      <div>
        <DemoTour
          step="reveal"
          anchor={null}
          variables={{ tasksN, rhythmsN }}
          onSkip={handleSkipOut}
        />
        <MigrationPreview
          initialTasks={tasks}
          initialRhythms={rhythms}
          unmatched={unmatched}
          onSubmit={(finalTasks, finalRhythms) =>
            handleCommit(finalTasks, finalRhythms)
          }
          onSkip={handleSkipOut}
        />
      </div>
    );
  }

  // Parse error — retry
  if (phase.tag === "parse_error") {
    return (
      <div style={CARD}>
        <div style={ERROR_BOX}>
          <p
            style={{
              fontSize: 13,
              color: "var(--danger, #e5534b)",
              margin: 0,
              fontFamily: "var(--font-literata)",
            }}
          >
            {phase.message}
          </p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button style={BTN_PRIMARY} onClick={handleParse}>
            Try again
          </button>
          <button
            style={BTN_SECONDARY}
            onClick={() => dispatch({ type: "RESET_TO_IDLE" })}
          >
            Edit text
          </button>
        </div>
      </div>
    );
  }

  // Parsing spinner
  if (phase.tag === "parsing") {
    return (
      <div style={CARD}>
        <div style={SPINNER_WRAP}>
          <div style={SPINNER} />
          <p style={{ ...NOTE, marginTop: 0 }}>Reading your tasks…</p>
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  // Idle: textarea paste view
  // phase.tag === "idle"
  const canParse = state.rawText.trim().length >= 20;

  return (
    <div style={CARD}>
      <p style={HEADING}>Import your tasks</p>
      <p style={SUBHEADING}>
        Paste a list of tasks, notes, or projects below. Papyrus will read them and
        suggest how to organise your work.
      </p>
      <textarea
        style={TEXTAREA}
        placeholder={
          "e.g.\n• Finish project proposal — due Friday, ~2 hours\n• Weekly grocery run\n• Call dentist to reschedule"
        }
        value={state.rawText}
        onChange={(e) => dispatch({ type: "SET_RAW_TEXT", text: e.target.value })}
      />
      <div style={{ display: "flex", gap: 10, marginTop: 14, alignItems: "center" }}>
        <button
          style={canParse ? BTN_PRIMARY : BTN_PRIMARY_DISABLED}
          disabled={!canParse}
          onClick={handleParse}
        >
          Import
        </button>
        <button style={BTN_SECONDARY} onClick={onComplete}>
          Skip
        </button>
      </div>
      {!canParse && state.rawText.length > 0 && (
        <p style={{ ...NOTE, marginTop: 8 }}>
          Add a bit more detail — at least 20 characters.
        </p>
      )}
    </div>
  );
}
