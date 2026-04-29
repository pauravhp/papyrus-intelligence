"use client";

// ---------------------------------------------------------------------------
// PapyrusCalendarConfirm
//
// Step 8 of the migration assistant demo. Two variants:
//   scopeUpgradeRequired === true  → ask user to grant calendar.app.created scope
//   normal                         → confirm writing today's schedule to Papyrus cal
// ---------------------------------------------------------------------------

type Props = {
  calendarId: string | null;
  scopeUpgradeRequired: boolean;
  onConfirm: () => void;
  onSkip: () => void;
  onReOAuth: () => void;
  loading?: boolean;
};

// Inline style constants — parchment theme with CSS variables
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

const BODY: React.CSSProperties = {
  fontSize: 13,
  color: "var(--text-muted)",
  marginBottom: 20,
  lineHeight: 1.5,
  fontFamily: "var(--font-literata)",
};

const BTN_ROW: React.CSSProperties = {
  display: "flex",
  gap: 10,
  flexWrap: "wrap" as const,
  alignItems: "center",
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

const NOTE: React.CSSProperties = {
  fontSize: 12,
  color: "var(--text-faint)",
  fontFamily: "var(--font-literata)",
  lineHeight: 1.5,
  marginTop: 12,
};

export default function PapyrusCalendarConfirm({
  calendarId,
  scopeUpgradeRequired,
  onConfirm,
  onSkip,
  onReOAuth,
  loading = false,
}: Props) {
  // Scope-upgrade variant — user doesn't have calendar.app.created permission
  if (scopeUpgradeRequired) {
    return (
      <div style={CARD}>
        <p style={HEADING}>One quick permission</p>
        <p style={BODY}>
          To create your Papyrus calendar and write today&apos;s schedule to it,
          we need one extra Google permission. This is a one-time step.
        </p>
        <div style={BTN_ROW}>
          <button style={BTN_PRIMARY} onClick={onReOAuth}>
            Grant permission
          </button>
          <button style={BTN_SECONDARY} onClick={onSkip}>
            Skip — I&apos;ll set this up later
          </button>
        </div>
      </div>
    );
  }

  // Normal variant — confirm writing schedule to Papyrus calendar
  const isDisabled = loading || !calendarId;
  const confirmLabel = loading ? "Writing…" : "Confirm — write to my calendar";

  return (
    <div style={CARD}>
      <p style={HEADING}>Last step — your calendar</p>
      <p style={BODY}>
        I&apos;ll write today&apos;s schedule to your new <strong>Papyrus</strong> calendar
        in Google Calendar. You can always delete or edit the events from there.
      </p>
      <div style={BTN_ROW}>
        <button
          style={isDisabled ? BTN_PRIMARY_DISABLED : BTN_PRIMARY}
          disabled={isDisabled}
          onClick={onConfirm}
        >
          {confirmLabel}
        </button>
        <button style={BTN_SECONDARY} onClick={onSkip}>
          I&apos;ll explore on my own
        </button>
      </div>
      {!calendarId && !loading && (
        <p style={NOTE}>
          No Papyrus calendar was created during import — skipping calendar write is safe.
        </p>
      )}
    </div>
  );
}
