import { type GCalEvent } from "./TodayPage";
import { gcalColorToPapyrus } from "./utils/gcalColor";

const GRID_START = 8;
const PX_PER_HOUR = 72;

interface Props {
  event: GCalEvent;
}

export default function GcalEventBlock({ event }: Props) {
  const start = new Date(event.start_time);
  const end = new Date(event.end_time);
  const startHour = start.getHours() + start.getMinutes() / 60;
  const durationMin = (end.getTime() - start.getTime()) / 60000;

  const top = (startHour - GRID_START) * PX_PER_HOUR;
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
