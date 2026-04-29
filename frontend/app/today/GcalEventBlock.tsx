import { type GCalEvent } from "./TodayPage";
import { gcalColorToPapyrus } from "./utils/gcalColor";

const PX_PER_HOUR = 72;

interface Props {
  event: GCalEvent;
  gridStart: number;
  columnDate: string;  // YYYY-MM-DD — date the column represents (LOCAL)
}

/**
 * Hours past the column's local midnight. Mirrors the helper in DayColumn
 * and TaskBlock — uses the column's date as the reference, not the event's
 * own getHours(). Without this, a Tue 22:30 event leaks into Wed's column
 * because getHours() returns 22 regardless of whose day it is.
 */
function hoursPastColumnMidnight(iso: string, columnDateIso: string): number {
  const t = new Date(iso);
  const colMid = new Date(columnDateIso + "T00:00:00");
  return (t.getTime() - colMid.getTime()) / 3_600_000;
}

export default function GcalEventBlock({ event, gridStart, columnDate }: Props) {
  const start = new Date(event.start_time);
  const end = new Date(event.end_time);
  const startHour = hoursPastColumnMidnight(event.start_time, columnDate);
  const durationMin = (end.getTime() - start.getTime()) / 60000;

  const top = (startHour - gridStart) * PX_PER_HOUR;
  const height = Math.max(18, (durationMin / 60) * PX_PER_HOUR);

  const colors = gcalColorToPapyrus(event.color_hex ?? "");

  return (
    <div
      style={{
        position: "absolute",
        top,
        left: 2,
        right: 4,
        height,
        background: colors.fill,
        borderLeft: `3px solid ${colors.border}`,
        borderTop: "none",
        borderRight: "none",
        borderBottom: "none",
        borderRadius: 4,
        padding: "2px 6px",
        overflow: "hidden",
        zIndex: 1,
        boxSizing: "border-box",
      }}
    >
      <p
        style={{
          fontSize: 11,
          color: colors.border,
          fontFamily: "var(--font-literata)",
          lineHeight: 1.3,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          margin: 0,
        }}
      >
        {event.summary}
      </p>
    </div>
  );
}
