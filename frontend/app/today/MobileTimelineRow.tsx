"use client";

import type { ScheduledItem, GCalEvent } from "./TodayPage";

interface CommonProps {
  onTap?: () => void;
}

interface TaskRowProps extends CommonProps {
  kind: "task" | "rhythm";
  item: ScheduledItem;
  isDone?: boolean;
}

interface GcalRowProps extends CommonProps {
  kind: "gcal";
  item: GCalEvent;
}

export type MobileTimelineRowProps = TaskRowProps | GcalRowProps;

const STRIPE_COLOR: Record<"deep_work" | "admin" | "untagged", string> = {
  deep_work: "#7a6250",
  admin: "#c4821a",
  untagged: "rgba(44,26,14,0.28)",
};
const RHYTHM_STRIPE = "#6a8d6f";

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function fmtDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

export default function MobileTimelineRow(props: MobileTimelineRowProps) {
  const isGcal = props.kind === "gcal";
  const startIso = isGcal ? props.item.start_time : props.item.start_time;
  const time = fmtTime(startIso);

  if (isGcal) {
    return (
      <div
        data-testid="row-root"
        data-kind="gcal"
        onClick={props.onTap}
        style={{
          display: "flex",
          alignItems: "stretch",
          gap: 10,
          minHeight: 52,
          padding: "0 10px",
          margin: "0 -10px",
          borderRadius: 6,
          background: "rgba(160,144,128,0.12)",
          fontFamily: "var(--font-literata)",
        }}
      >
        <span data-testid="row-time" style={timeStyle}>{time}</span>
        <span style={{ flex: 1, padding: "8px 0", color: "rgba(44,26,14,0.55)", fontStyle: "italic", fontSize: 13, lineHeight: 1.3, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {props.item.summary}
        </span>
        <span style={badgeStyle("gcal")}>GCAL</span>
      </div>
    );
  }

  const item = props.item;
  const isDone = props.isDone ?? false;
  const stripeColor =
    props.kind === "rhythm"
      ? RHYTHM_STRIPE
      : STRIPE_COLOR[item.category ?? "untagged"];
  const dataCategory = item.category ?? "untagged";

  return (
    <div
      data-testid="row-root"
      data-kind={props.kind}
      onClick={props.onTap}
      role={props.onTap ? "button" : undefined}
      tabIndex={props.onTap ? 0 : undefined}
      onKeyDown={(e) => {
        if (props.onTap && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          props.onTap();
        }
      }}
      style={{
        display: "flex",
        alignItems: "stretch",
        gap: 10,
        minHeight: 52,
        cursor: props.onTap ? "pointer" : "default",
        fontFamily: "var(--font-literata)",
      }}
    >
      <span data-testid="row-time" style={timeStyle}>{time}</span>
      <span
        data-testid="row-stripe"
        data-category={dataCategory}
        data-kind={props.kind}
        style={{ width: 4, borderRadius: 2, background: stripeColor, flexShrink: 0 }}
      />
      <span style={{ flex: 1, padding: "8px 0", color: "var(--text)", fontSize: 13, lineHeight: 1.3, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", wordBreak: "break-word", ...(isDone && { textDecoration: "line-through", opacity: 0.6 }) }}>
        {isDone && "✓ "}{item.task_name}
      </span>
      {props.kind === "rhythm" && <span style={badgeStyle("rhythm")}>RHYTHM</span>}
      <span style={durationStyle}>{fmtDuration(item.duration_minutes)}</span>
    </div>
  );
}

const timeStyle: React.CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  color: "rgba(44,26,14,0.55)",
  minWidth: 56,
  paddingTop: 9,
  fontSize: 11,
  textAlign: "right",
};

const durationStyle: React.CSSProperties = {
  color: "rgba(44,26,14,0.45)",
  fontSize: 10,
  paddingTop: 11,
  minWidth: 36,
  textAlign: "right",
};

function badgeStyle(kind: "rhythm" | "gcal"): React.CSSProperties {
  if (kind === "rhythm") {
    return {
      alignSelf: "center",
      background: "rgba(106,141,111,0.18)",
      color: "#2d6a4f",
      padding: "2px 6px",
      borderRadius: 3,
      fontSize: 9,
      letterSpacing: "0.06em",
      textTransform: "uppercase",
      fontFamily: "ui-sans-serif, system-ui, sans-serif",
    };
  }
  return {
    alignSelf: "center",
    background: "rgba(44,26,14,0.12)",
    color: "rgba(44,26,14,0.55)",
    padding: "2px 6px",
    borderRadius: 3,
    fontSize: 9,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
  };
}
