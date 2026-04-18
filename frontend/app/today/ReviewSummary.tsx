// frontend/app/dashboard/today/ReviewSummary.tsx

interface ReviewSummaryProps {
  summaryLine: string;
  tasksCompleted: number;
  tasksTotal: number;
  timeOverUnder: number; // positive = over, negative = under, 0 = on track (in minutes)
  rhythmsCompleted: number;
  rhythmsTotal: number;
  onClose: () => void;
}

export default function ReviewSummary({
  summaryLine,
  tasksCompleted,
  tasksTotal,
  timeOverUnder,
  rhythmsCompleted,
  rhythmsTotal,
  onClose,
}: ReviewSummaryProps) {
  const timeLabel =
    timeOverUnder === 0
      ? "On track"
      : timeOverUnder > 0
      ? `+${timeOverUnder} min over`
      : `${Math.abs(timeOverUnder)} min under`;

  return (
    <>
      <div style={{ padding: "32px 24px 24px" }}>
        <div
          style={{
            fontFamily: "var(--font-gilda, var(--font-display))",
            fontSize: 28,
            fontWeight: 400,
            color: "var(--text)",
            marginBottom: 8,
          }}
        >
          That&rsquo;s a wrap.
        </div>
        <div
          style={{
            fontSize: 14,
            fontFamily: "var(--font-literata)",
            fontStyle: "italic",
            color: "var(--text-secondary, #7a5c3e)",
            marginBottom: 32,
            lineHeight: 1.6,
            maxWidth: "38ch",
          }}
        >
          {summaryLine}
        </div>

        {[
          { label: "Tasks completed", value: `${tasksCompleted} of ${tasksTotal}` },
          {
            label: timeOverUnder >= 0 ? "Time over estimate" : "Time under estimate",
            value: timeLabel,
            accent: timeOverUnder > 0,
          },
          { label: "Rhythms kept", value: `${rhythmsCompleted} of ${rhythmsTotal}` },
        ].map(({ label, value, accent }) => (
          <div
            key={label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              padding: "11px 0",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <span style={{ fontSize: 13, color: "var(--text-secondary, #7a5c3e)", fontFamily: "var(--font-literata)" }}>
              {label}
            </span>
            <span
              style={{
                fontSize: 15,
                fontWeight: 500,
                fontFamily: "var(--font-literata)",
                color: accent ? "var(--accent)" : "var(--text)",
              }}
            >
              {value}
            </span>
          </div>
        ))}
      </div>

      <div style={{ padding: "16px 24px 24px", borderTop: "1px solid var(--border)" }}>
        <button
          onClick={onClose}
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
            cursor: "pointer",
            letterSpacing: "0.01em",
          }}
        >
          Close
        </button>
      </div>
    </>
  );
}
