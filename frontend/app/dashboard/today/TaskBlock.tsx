// frontend/app/dashboard/today/TaskBlock.tsx
import { type ScheduledItem } from "./TodayPage";

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function fmtDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

function spansNextDay(item: ScheduledItem): boolean {
  const startDate = new Date(item.start_time).toDateString();
  const endDate   = new Date(item.end_time).toDateString();
  return startDate !== endDate;
}

interface TaskBlockProps {
  item: ScheduledItem;
  isContinuation?: boolean;  // true when shown on the NEXT day as a cross-midnight continuation
}

export default function TaskBlock({ item, isContinuation = false }: TaskBlockProps) {
  const crossMidnight = spansNextDay(item);
  const displayStart = isContinuation
    ? new Date(item.start_time).toDateString() === new Date(item.end_time).toDateString()
      ? fmtTime(item.start_time)
      : "12:00 am"
    : fmtTime(item.start_time);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "52px 1fr auto",
        alignItems: "baseline",
        gap: "0 10px",
        padding: "10px 0",
        borderBottom: "1px solid var(--border)",
        opacity: isContinuation ? 0.65 : 1,
      }}
    >
      <time
        dateTime={item.start_time}
        style={{
          color: "var(--accent)",
          fontSize: 12,
          fontVariantNumeric: "tabular-nums",
          fontFamily: "var(--font-literata)",
        }}
      >
        {displayStart}
      </time>

      <div>
        <span style={{ color: "var(--text)", fontSize: 14, fontFamily: "var(--font-literata)" }}>
          {item.task_name}
        </span>
        {crossMidnight && !isContinuation && (
          <span style={{ color: "var(--text-faint)", fontSize: 11, marginLeft: 6 }}>
            → next day
          </span>
        )}
        {isContinuation && (
          <span style={{ color: "var(--text-faint)", fontSize: 11, display: "block", fontStyle: "italic" }}>
            ↑ continued
          </span>
        )}
      </div>

      <span
        style={{
          color: "var(--text-faint)",
          fontSize: 12,
          whiteSpace: "nowrap",
          fontFamily: "var(--font-literata)",
        }}
      >
        {fmtDuration(item.duration_minutes)}
      </span>
    </div>
  );
}
