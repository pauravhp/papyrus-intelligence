"use client";

import { useReducer, useRef, useCallback, useEffect } from "react";
import { createClient } from "@/utils/supabase/client";
import { ApiError } from "@/utils/api";
import {
  convertMigration,
  commitMigration,
} from "@/lib/migrationApi";
import type {
  ConvertResponse,
  CommitResponse,
  TaskProposal,
  RhythmProposal,
} from "@/lib/migrationApi";
import MigrationPreview from "@/components/MigrationPreview";
import DemoTour from "@/components/DemoTour";

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
// Component
// ---------------------------------------------------------------------------

type Props = {
  variant: Variant;
  onComplete: () => void;
  onContinueToDemoSteps: (result: CommitResponse) => void;
};

export default function ImportStage({ variant, onComplete, onContinueToDemoSteps }: Props) {
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
        if (result.calendar_scope_upgrade_required) {
          // Surface as a note but still advance — Task 13 handles scope upgrade
          dispatch({ type: "COMMIT_SUCCESS", result });
        } else {
          dispatch({ type: "COMMIT_SUCCESS", result });
        }
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

  // Post-commit: success
  if (phase.tag === "post_commit") {
    const { result } = phase;
    return (
      <div style={CARD}>
        {result.calendar_scope_upgrade_required && (
          <p style={{ ...NOTE, marginBottom: 16 }}>
            We&apos;ll ask permission to create your Papyrus calendar at the next step.
          </p>
        )}
        <p style={HEADING}>
          Imported {result.tasks_created} task{result.tasks_created !== 1 ? "s" : ""}
          {result.rhythms_created > 0
            ? ` and ${result.rhythms_created} rhythm${result.rhythms_created !== 1 ? "s" : ""}`
            : ""}
        </p>
        {result.errors.length > 0 && (
          <p style={NOTE}>
            {result.errors.length} item
            {result.errors.length !== 1 ? "s" : ""} couldn&apos;t be saved.
          </p>
        )}
        <button style={BTN_PRIMARY} onClick={() => onContinueToDemoSteps(result)}>
          Continue
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
