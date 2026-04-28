// frontend/app/dashboard/today/DayColumn.tsx
import { motion } from "framer-motion";
import { type DayData, type ScheduledItem, type GCalEvent } from "./TodayPage";
import TaskBlock from "./TaskBlock";
import NowIndicator from "./NowIndicator";
import GcalEventBlock from "./GcalEventBlock";

const GRID_START = 8;
const GRID_DEFAULT_END = 24;
const PX_PER_HOUR = 72;
const GUTTER_WIDTH = 44;
// Hard ceiling on how far past GRID_START the grid is allowed to extend.
// Backstop for the "runaway timestamp" case (e.g. backend bug or LLM
// hallucination places a task 18 hours into tomorrow): without this, the
// today column auto-grew to a single 28+ hour scrolling mess. Anything past
// this gets clipped + a "Schedule extends beyond view" notice surfaces.
const GRID_MAX_HOURS_FROM_START = 28;

interface DayColumnProps {
  label: string;
  dayData: DayData | null;
  isToday: boolean;
  planningStatus?: "idle" | "working" | "proposal";
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

/**
 * Hours past the column's local midnight. A task starting/ending on the next
 * day returns a value > 24 (e.g. 02:30 next day → 26.5).
 */
function hoursPastColumnMidnight(iso: string, columnDateIso: string): number {
  const t = new Date(iso);
  const colMid = new Date(columnDateIso + "T00:00:00");
  return (t.getTime() - colMid.getTime()) / 3_600_000;
}

export default function DayColumn({ label, dayData, isToday, planningStatus }: DayColumnProps) {
  const showSkeleton = isToday && planningStatus === "working";
  const scheduled = dayData?.scheduled ?? [];
  const pushed = dayData?.pushed ?? [];
  const isEmpty = scheduled.length === 0;
  const hasGcal =
    (dayData?.gcal_events?.length ?? 0) > 0 ||
    (dayData?.all_day_events?.length ?? 0) > 0;

  // columnDate must be YYYY-MM-DD (LOCAL date). Use today's local date as fallback
  // — toISOString() returns UTC date which can be off-by-one in evening hours.
  const columnDate = dayData?.schedule_date ?? (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  })();

  // Extend the grid to cover whatever task ends latest, including post-midnight
  // tasks. Old code capped at hour 25 even when a task ran to 02:30 next day.
  // Defensive: drop NaN values that would otherwise propagate into gridHeight.
  const taskEndHours = scheduled
    .map((item) => hoursPastColumnMidnight(item.end_time, columnDate))
    .filter((h) => Number.isFinite(h));
  const latestTaskEndHour = taskEndHours.length > 0 ? Math.max(...taskEndHours) : 0;
  const nowHour = isToday ? new Date().getHours() : 0;
  const baseEnd = isToday ? Math.max(GRID_DEFAULT_END, nowHour + 1) : GRID_DEFAULT_END;
  const desiredEnd = Math.max(baseEnd, Math.ceil(latestTaskEndHour));
  // Defensive ceiling: never let the column grow past GRID_START + N hours.
  // A backend that returned tasks with timestamps deep into the next day would
  // otherwise produce an 18-hour scrolling mess in today's column.
  const hardCeiling = GRID_START + GRID_MAX_HOURS_FROM_START;
  const gridEnd = Math.min(desiredEnd, hardCeiling);
  const overflowsCap = latestTaskEndHour > hardCeiling;
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
              <span style={{ color: "var(--accent)" }}>
                Use the Plan button above to get started →
              </span>
            </>
          ) : (
            "No schedule planned."
          )}
        </p>
      )}

      {/* Calendar grid — shown when there are tasks, GCal events, skeleton active, or it's Today (for now line) */}
      {(!isEmpty || isToday || hasGcal || showSkeleton) && (
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

            {/* Midnight divider (only when grid extends past midnight) */}
            {gridEnd > 24 && (
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

            {/* Task blocks — or skeleton while planning */}
            {showSkeleton ? (
              [
                { top: 0 * 72, h: 72, type: "deep" },
                { top: 1.5 * 72, h: 28, type: "admin" },
                { top: 2.25 * 72, h: 44, type: "deep" },
                { top: 4 * 72, h: 44, type: "admin" },
              ].map((s, i) => (
                <motion.div
                  key={i}
                  animate={{ opacity: [0.3, 0.6, 0.3] }}
                  transition={{ duration: 1.8, repeat: Infinity, delay: i * 0.2 }}
                  style={{
                    position: "absolute",
                    top: s.top,
                    left: 4,
                    right: 4,
                    height: s.h,
                    borderRadius: 6,
                    borderLeft: `3px solid ${s.type === "deep" ? "rgba(122,98,80,0.4)" : "rgba(196,130,26,0.35)"}`,
                    background: s.type === "deep" ? "rgba(122,98,80,0.12)" : "rgba(196,130,26,0.08)",
                  }}
                />
              ))
            ) : (
              scheduled.map((item) => (
                <TaskBlock
                  key={`${item.task_id}__${item.start_time}`}
                  item={item}
                  columnDate={columnDate}
                  isProposed={planningStatus === "proposal"}
                />
              ))
            )}

            {/* GCal event blocks (read-only, behind confirmed task blocks) */}
            {(dayData?.gcal_events ?? []).map((event) => (
              <GcalEventBlock key={event.id} event={event} />
            ))}

            {/* Now indicator (today column only) */}
            {isToday && <NowIndicator />}
          </div>
        </div>
      )}

      {/* Overflow notice — schedule extends past the defensive cap. Surfaces
          backend / LLM bugs that placed timestamps far past the day boundary
          rather than silently clipping them out of view. */}
      {overflowsCap && (
        <div
          style={{
            padding: "8px 14px",
            borderTop: "1px solid var(--border)",
            background: "var(--accent-tint)",
            fontSize: 11,
            color: "var(--accent)",
            fontFamily: "var(--font-literata)",
            fontStyle: "italic",
            lineHeight: 1.4,
          }}
        >
          Schedule extends beyond view — open Tomorrow&apos;s view to see the rest.
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
