"use client";

import type { NowNextState } from "./useNowNext";
import type { ScheduledItem, GCalEvent } from "./TodayPage";

function nameOf(ref: ScheduledItem | GCalEvent | null | undefined): string {
  if (!ref) return "";
  return "task_name" in ref ? ref.task_name : ref.summary;
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

interface Props {
  state: NowNextState;
}

export default function MobileNowNextHero({ state }: Props) {
  return (
    <div
      data-testid="now-hero"
      data-sticky="true"
      style={{
        background: "rgba(196,130,26,0.10)",
        borderLeft: "3px solid var(--accent)",
        padding: "10px 14px",
        borderRadius: 8,
        fontFamily: "var(--font-literata)",
        position: "sticky",
        top: 0,
        zIndex: 6,
      }}
    >
      {state.kind === "now" && (
        <>
          <p style={labelStyle}>Now · {fmtTime((state.current as { start_time: string }).start_time)}</p>
          <p style={titleStyle}>{nameOf(state.current)}</p>
          <p style={subStyle}>
            {state.minutes_left}m left
            {state.next && <> · Next: {nameOf(state.next)}</>}
          </p>
        </>
      )}
      {state.kind === "free" && (
        <>
          <p style={labelStyle}>Free until {fmtTime(state.until)}</p>
          {state.next && <p style={titleStyle}>Then: {nameOf(state.next)}</p>}
        </>
      )}
      {state.kind === "done" && (
        <>
          <p style={labelStyle}>All clear</p>
          <p style={titleStyle}>Nothing left today</p>
        </>
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontSize: 9,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  color: "var(--accent)",
  fontWeight: 700,
  margin: 0,
};
const titleStyle: React.CSSProperties = {
  fontSize: 14,
  color: "var(--text)",
  margin: "2px 0 1px",
  lineHeight: 1.3,
};
const subStyle: React.CSSProperties = {
  fontSize: 11,
  color: "rgba(44,26,14,0.55)",
  margin: 0,
};
