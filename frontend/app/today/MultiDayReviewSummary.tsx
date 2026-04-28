interface DayStatRow {
  schedule_date: string;
  weekday: string;
  tasks_completed: number;
  tasks_total: number;
  rhythms_completed: number;
  rhythms_total: number;
}

interface AggregateData {
  narrative_line: string;
  per_day: DayStatRow[];
}

interface MultiDayReviewSummaryProps {
  aggregate: AggregateData;
  onClose: () => void;
}

export default function MultiDayReviewSummary({ aggregate, onClose }: MultiDayReviewSummaryProps) {
  return (
    <>
      <div style={{ padding: "32px 24px 24px" }}>
        <div style={{
          fontFamily: "var(--font-gilda, var(--font-display))",
          fontSize: 28, fontWeight: 400, color: "var(--text)", marginBottom: 8,
        }}>
          That&rsquo;s a wrap.
        </div>
        <div style={{
          fontSize: 14, fontFamily: "var(--font-literata)",
          fontStyle: "italic", color: "var(--text-secondary, #7a5c3e)",
          marginBottom: 24, lineHeight: 1.6, maxWidth: "38ch",
        }}>
          {aggregate.narrative_line}
        </div>

        {aggregate.per_day.map(row => (
          <div key={row.schedule_date} style={{
            display: "flex", justifyContent: "space-between", alignItems: "baseline",
            padding: "11px 0", borderBottom: "1px solid var(--border)",
          }}>
            <span style={{ fontSize: 13, color: "var(--text-secondary, #7a5c3e)", fontFamily: "var(--font-literata)" }}>
              {row.weekday} · {row.schedule_date.slice(5)}
            </span>
            <span style={{ fontSize: 14, fontFamily: "var(--font-literata)", color: "var(--text)" }}>
              {row.tasks_completed}/{row.tasks_total} tasks · {row.rhythms_completed}/{row.rhythms_total} rhythms
            </span>
          </div>
        ))}
      </div>

      <div style={{ padding: "16px 24px 24px", borderTop: "1px solid var(--border)" }}>
        <button onClick={onClose} style={{
          width: "100%", padding: 13, background: "var(--text)",
          color: "var(--surface)", border: "none", borderRadius: 8,
          fontFamily: "var(--font-literata)", fontSize: 14, fontWeight: 500,
          cursor: "pointer", letterSpacing: "0.01em",
        }}>
          Close
        </button>
      </div>
    </>
  );
}
