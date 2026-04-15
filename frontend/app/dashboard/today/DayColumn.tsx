// frontend/app/dashboard/today/DayColumn.tsx
import Link from "next/link";
import { type DayData, type ScheduledItem } from "./TodayPage";
import TaskBlock from "./TaskBlock";
import NowIndicator from "./NowIndicator";

interface DayColumnProps {
  label: string;
  dayData: DayData | null;
  isToday: boolean;
}

function fmtDate(isoDate: string): string {
  return new Date(isoDate + "T12:00:00").toLocaleDateString([], {
    weekday: "short", day: "numeric", month: "short"
  });
}

// Detect tasks that start on the PREVIOUS day (cross-midnight continuations to show at top)
function getContinuationItems(scheduled: ScheduledItem[], dayDate: string): ScheduledItem[] {
  // Items where start_time is from the previous calendar day but end_time is on this day
  return scheduled.filter(item => {
    const startDate = new Date(item.start_time).toDateString();
    const endDate   = new Date(item.end_time).toDateString();
    const thisDay   = new Date(dayDate + "T12:00:00").toDateString();
    return startDate !== thisDay && endDate === thisDay;
  });
}

export default function DayColumn({ label, dayData, isToday }: DayColumnProps) {
  const isEmpty = !dayData || dayData.scheduled.length === 0;

  const wrapperStyle: React.CSSProperties = isToday
    ? {
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "20px 18px",
      }
    : { padding: "4px 0" };

  return (
    <div style={wrapperStyle}>
      {/* Day heading */}
      <p
        className="font-display"
        style={{ fontSize: 18, color: "var(--text)", marginBottom: 2 }}
      >
        {label}
      </p>
      {dayData && (
        <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-literata)", marginBottom: 16 }}>
          {fmtDate(dayData.schedule_date)}
        </p>
      )}

      {isEmpty ? (
        <p style={{
          fontSize: 13,
          color: "var(--text-faint)",
          fontStyle: "italic",
          fontFamily: "var(--font-literata)",
          marginTop: dayData ? 0 : 8,
        }}>
          {isToday ? (
            <>No schedule yet.{" "}
              <Link href="/dashboard" style={{ color: "var(--accent)", textDecoration: "none" }}>
                Plan your day →
              </Link>
            </>
          ) : "No schedule planned."}
        </p>
      ) : (
        <div style={{ position: "relative" }}>
          {/* Cross-midnight continuations at the top */}
          {dayData.schedule_date && getContinuationItems(dayData.scheduled, dayData.schedule_date).map(item => (
            <TaskBlock key={`cont-${item.task_id}`} item={item} isContinuation />
          ))}

          {/* Now indicator (today only) — inserted between tasks */}
          {isToday ? (
            <NowIndicator scheduled={dayData.scheduled} />
          ) : (
            dayData.scheduled.map(item => (
              <TaskBlock key={item.task_id} item={item} />
            ))
          )}

          {/* Pushed tasks */}
          {dayData.pushed.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <p style={{
                fontSize: 10,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--text-faint)",
                marginBottom: 6,
                fontFamily: "var(--font-literata)",
              }}>
                Didn&apos;t make the cut
              </p>
              {dayData.pushed.map((p) => (
                <p key={p.task_id} style={{
                  fontSize: 13,
                  color: "var(--text-faint)",
                  fontFamily: "var(--font-literata)",
                  lineHeight: 1.5,
                }}>
                  {p.reason}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
