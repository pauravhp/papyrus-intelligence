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
        background: "rgba(99,102,241,0.06)",
        border: "1px solid rgba(99,102,241,0.2)",
        borderRadius: 14,
        padding: "18px 20px",
        marginTop: 8,
        width: "100%",
      }}
    >
      {/* Header */}
      <p
        style={{
          color: "#818cf8",
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 14,
        }}
      >
        Proposed schedule
      </p>

      {/* Scheduled items */}
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
                  ? "1px solid rgba(255,255,255,0.04)"
                  : "none",
            }}
          >
            {/* Time start */}
            <span
              style={{
                color: "#818cf8",
                fontSize: 12,
                fontWeight: 500,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmt(item.start_time)}
            </span>
            {/* Task name */}
            <span style={{ color: "#e2e8f0", fontSize: 14 }}>
              {item.task_name}
            </span>
            {/* Duration */}
            <span
              style={{
                color: "#475569",
                fontSize: 12,
                whiteSpace: "nowrap",
              }}
            >
              {item.duration_minutes}m
            </span>
          </div>
        ))}
      </div>

      {/* Pushed items */}
      {schedule.pushed.length > 0 && (
        <div
          style={{
            marginTop: 14,
            padding: "10px 12px",
            background: "rgba(245,158,11,0.08)",
            border: "1px solid rgba(245,158,11,0.15)",
            borderRadius: 8,
          }}
        >
          <p
            style={{
              color: "#d97706",
              fontSize: 11,
              fontWeight: 600,
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
              style={{ color: "#94a3b8", fontSize: 13, lineHeight: 1.5 }}
            >
              {p.task_id} — {p.reason}
            </p>
          ))}
        </div>
      )}

      {/* Reasoning */}
      {schedule.reasoning_summary && (
        <p
          style={{
            color: "#475569",
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
