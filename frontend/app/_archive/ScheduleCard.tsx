// frontend/app/dashboard/ScheduleCard.tsx
"use client";

interface ScheduledItem {
  task_id: string;
  task_name: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
}

interface PushedItem {
  task_id: string;
  task_name?: string;
  reason: string;
}

interface Schedule {
  scheduled: ScheduledItem[];
  pushed: PushedItem[];
  reasoning_summary: string;
}

export default function ScheduleCard({ schedule }: { schedule: Schedule }) {
  const fmt = (iso: string) =>
    new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "18px 20px",
        marginTop: 8,
        width: "100%",
      }}
    >
      <p
        style={{
          color: "var(--accent)",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 14,
        }}
      >
        Proposed schedule
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {schedule.scheduled.map((item, i) => (
          <div
            key={item.task_id}
            style={{
              display: "grid",
              gridTemplateColumns: "44px 1fr auto",
              alignItems: "center",
              gap: "0 12px",
              padding: "9px 0",
              borderBottom:
                i < schedule.scheduled.length - 1
                  ? "1px solid var(--border)"
                  : "none",
            }}
          >
            <span
              style={{
                color: "var(--accent)",
                fontSize: 12,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmt(item.start_time)}
            </span>
            <span style={{ color: "var(--text)", fontSize: 14 }}>
              {item.task_name}
            </span>
            <span
              style={{
                color: "var(--text-faint)",
                fontSize: 12,
                whiteSpace: "nowrap",
              }}
            >
              {item.duration_minutes}m
            </span>
          </div>
        ))}
      </div>

      {schedule.pushed.length > 0 && (
        <div
          style={{
            marginTop: 14,
            padding: "10px 12px",
            background: "var(--danger-tint)",
            border: "1px solid var(--danger)",
            borderRadius: 8,
          }}
        >
          <p
            style={{
              color: "var(--danger)",
              fontSize: 11,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              marginBottom: 6,
            }}
          >
            Moved to another day
          </p>
          {schedule.pushed.map((p) => (
            <p
              key={p.task_id}
              style={{ color: "var(--text-muted)", fontSize: 13, lineHeight: 1.5 }}
            >
              {p.task_name || p.task_id} — {p.reason}
            </p>
          ))}
        </div>
      )}

      {schedule.reasoning_summary && (
        <p
          style={{
            color: "var(--text-muted)",
            fontSize: 12,
            marginTop: 12,
            lineHeight: 1.6,
            fontStyle: "italic",
          }}
        >
          {schedule.reasoning_summary}
        </p>
      )}
    </div>
  );
}
