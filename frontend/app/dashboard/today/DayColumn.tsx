// frontend/app/dashboard/today/DayColumn.tsx
import Link from "next/link";
import { type DayData, type ScheduledItem, type GCalEvent } from "./TodayPage";
import TaskBlock from "./TaskBlock";
import NowIndicator from "./NowIndicator";
import GcalEventBlock from "./GcalEventBlock";

const GRID_START = 8;
const GRID_DEFAULT_END = 20;
const PX_PER_HOUR = 72;
const GUTTER_WIDTH = 44;

interface DayColumnProps {
  label: string;
  dayData: DayData | null;
  isToday: boolean;
}

function fmtDate(isoDate: string): string {
  return new Date(isoDate + "T12:00:00").toLocaleDateString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function formatHour(h: number): string {
  const actual = h % 24;
  if (actual === 0) return "12 am";
  if (actual === 12) return "12 pm";
  if (actual < 12) return `${actual} am`;
  return `${actual - 12} pm`;
}

function hasCrossMidnightTask(scheduled: ScheduledItem[]): boolean {
  return scheduled.some(
    (item) =>
      new Date(item.end_time).getDate() !== new Date(item.start_time).getDate()
  );
}

export default function DayColumn({ label, dayData, isToday }: DayColumnProps) {
  const scheduled = dayData?.scheduled ?? [];
  const pushed = dayData?.pushed ?? [];
  const isEmpty = scheduled.length === 0;
  const hasGcal =
    (dayData?.gcal_events?.length ?? 0) > 0 ||
    (dayData?.all_day_events?.length ?? 0) > 0;

  const crossMidnight = hasCrossMidnightTask(scheduled);
  // When it's today, extend the grid to include the current hour so the now indicator is always visible
  const nowHour = isToday ? new Date().getHours() : 0;
  const dynamicEnd = isToday ? Math.max(GRID_DEFAULT_END, nowHour + 1) : GRID_DEFAULT_END;
  const gridEnd = crossMidnight ? 25 : dynamicEnd;
  const gridHeight = (gridEnd - GRID_START) * PX_PER_HOUR;

  // Hour markers: one line + label per hour from GRID_START to gridEnd (inclusive start, exclusive end)
  const hourMarkers = Array.from(
    { length: gridEnd - GRID_START },
    (_, i) => GRID_START + i
  );

  const wrapperStyle: React.CSSProperties = isToday
    ? {
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        overflow: "hidden",
        boxShadow: "0 2px 16px rgba(192,122,47,0.09)",
      }
    : {};

  return (
    <div style={wrapperStyle}>
      {/* Column header */}
      <div
        style={{
          padding: "12px 14px 10px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <p
          className="font-display"
          style={{ fontSize: 16, color: "var(--text)" }}
        >
          {label}
        </p>
        {dayData && (
          <p
            style={{
              fontSize: 11,
              color: "var(--text-faint)",
              fontFamily: "var(--font-literata)",
              marginTop: 2,
            }}
          >
            {fmtDate(dayData.schedule_date)}
          </p>
        )}
      </div>

      {/* All-day event pills */}
      {(dayData?.all_day_events?.length ?? 0) > 0 && (
        <div
          style={{
            padding: "4px 14px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
          }}
        >
          {dayData!.all_day_events.map((name, i) => (
            <span
              key={i}
              style={{
                fontSize: 10,
                color: "var(--text-faint)",
                fontFamily: "var(--font-literata)",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 3,
                padding: "1px 5px",
              }}
            >
              {name}
            </span>
          ))}
        </div>
      )}

      {/* Empty state */}
      {(isEmpty && !hasGcal) && (
        <p
          style={{
            fontSize: 13,
            color: "var(--text-faint)",
            fontStyle: "italic",
            fontFamily: "var(--font-literata)",
            padding: "16px 14px",
          }}
        >
          {isToday ? (
            <>
              No schedule yet.{" "}
              <Link
                href="/dashboard"
                style={{ color: "var(--accent)", textDecoration: "none" }}
              >
                Plan your day →
              </Link>
            </>
          ) : (
            "No schedule planned."
          )}
        </p>
      )}

      {/* Calendar grid — shown when there are tasks, GCal events, or it's Today (for now line) */}
      {(!isEmpty || isToday || hasGcal) && (
        <div style={{ display: "flex" }}>
          {/* Time gutter */}
          <div
            style={{
              width: GUTTER_WIDTH,
              flexShrink: 0,
              borderRight: "1px solid var(--border)",
              position: "relative",
              height: gridHeight,
            }}
          >
            {hourMarkers.map((h) => (
              <div
                key={h}
                style={{
                  position: "absolute",
                  top: (h - GRID_START) * PX_PER_HOUR,
                  right: 6,
                  fontSize: 10,
                  color: "var(--text-faint)",
                  fontFamily: "var(--font-literata)",
                  transform: "translateY(-50%)",
                  whiteSpace: "nowrap",
                  fontVariantNumeric: "tabular-nums",
                  userSelect: "none",
                }}
              >
                {formatHour(h)}
              </div>
            ))}
          </div>

          {/* Events lane */}
          <div
            style={{
              flex: 1,
              position: "relative",
              height: gridHeight,
            }}
          >
            {/* Hour lines */}
            {hourMarkers.map((h) => (
              <div
                key={`hr-${h}`}
                style={{
                  position: "absolute",
                  top: (h - GRID_START) * PX_PER_HOUR,
                  left: 0,
                  right: 0,
                  height: 1,
                  background: "var(--border)",
                }}
              />
            ))}

            {/* Half-hour lines (dashed) */}
            {hourMarkers.map((h) => (
              <div
                key={`hh-${h}`}
                style={{
                  position: "absolute",
                  top: (h - GRID_START + 0.5) * PX_PER_HOUR,
                  left: 0,
                  right: 0,
                  height: 1,
                  opacity: 0.35,
                  background:
                    "repeating-linear-gradient(to right, var(--border) 0, var(--border) 4px, transparent 4px, transparent 8px)",
                }}
              />
            ))}

            {/* Midnight divider (cross-midnight tasks only) */}
            {crossMidnight && (
              <div
                style={{
                  position: "absolute",
                  top: (24 - GRID_START) * PX_PER_HOUR,
                  left: 0,
                  right: 0,
                  borderTop: "1px dashed var(--accent)",
                  display: "flex",
                  alignItems: "center",
                  zIndex: 5,
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    color: "var(--accent)",
                    fontFamily: "var(--font-literata)",
                    padding: "0 4px",
                    background: isToday ? "var(--surface)" : "var(--bg, #f5f0e8)",
                  }}
                >
                  midnight →
                </span>
              </div>
            )}

            {/* Task blocks */}
            {scheduled.map((item) => (
              <TaskBlock key={item.task_id} item={item} />
            ))}

            {/* GCal event blocks (read-only, behind confirmed task blocks) */}
            {(dayData?.gcal_events ?? []).map((event) => (
              <GcalEventBlock key={event.id} event={event} />
            ))}

            {/* Now indicator (today column only) */}
            {isToday && <NowIndicator />}
          </div>
        </div>
      )}

      {/* Pushed tasks */}
      {pushed.length > 0 && (
        <div style={{ padding: "12px 14px", borderTop: "1px solid var(--border)" }}>
          <p
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--text-faint)",
              marginBottom: 6,
              fontFamily: "var(--font-literata)",
            }}
          >
            Didn&apos;t make the cut
          </p>
          {pushed.map((p) => (
            <p
              key={p.task_id}
              style={{
                fontSize: 12,
                color: "var(--text-faint)",
                fontFamily: "var(--font-literata)",
                lineHeight: 1.5,
              }}
            >
              {p.reason}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
