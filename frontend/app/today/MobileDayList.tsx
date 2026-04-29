"use client";

import { useState } from "react";
import type { DayData, ScheduledItem, GCalEvent } from "./TodayPage";
import MobileTimelineRow from "./MobileTimelineRow";
import MobileNowNextHero from "./MobileNowNextHero";
import { computeNowNext } from "./useNowNext";

const EMPTY_COMPLETED_SET: Set<string> = new Set();

interface Props {
  dayData: DayData | null;
  isToday: boolean;
  now: Date;
  planningStatus: "idle" | "working" | "proposal";
  todoistCompletedIds?: Set<string>;
}

interface TimelineEntry {
  startMs: number;
  endMs: number;
  kind: "task" | "rhythm" | "gcal";
  ref: ScheduledItem | GCalEvent;
}

function buildEntries(dayData: DayData | null): TimelineEntry[] {
  if (!dayData) return [];
  const entries: TimelineEntry[] = [];
  for (const s of dayData.scheduled) {
    entries.push({
      startMs: new Date(s.start_time).getTime(),
      endMs: new Date(s.end_time).getTime(),
      kind: s.kind,
      ref: s,
    });
  }
  for (const g of dayData.gcal_events) {
    entries.push({
      startMs: new Date(g.start_time).getTime(),
      endMs: new Date(g.end_time).getTime(),
      kind: "gcal",
      ref: g,
    });
  }
  entries.sort((a, b) => a.startMs - b.startMs);
  return entries;
}

export default function MobileDayList({ dayData, isToday, now, planningStatus, todoistCompletedIds = EMPTY_COMPLETED_SET }: Props) {
  const [earlierExpanded, setEarlierExpanded] = useState(false);

  const entries = buildEntries(dayData);
  const nowMs = now.getTime();
  const past = entries.filter((e) => e.endMs <= nowMs);
  const upcoming = entries.filter((e) => e.endMs > nowMs);

  const heroState = isToday && dayData
    ? computeNowNext({ scheduled: dayData.scheduled, gcal_events: dayData.gcal_events, now })
    : null;

  const pushed = dayData?.pushed ?? [];
  const hasContent = entries.length > 0 || (pushed.length > 0);

  if (!hasContent) {
    return (
      <p style={{ fontSize: 13, color: "var(--text-faint)", fontStyle: "italic", fontFamily: "var(--font-literata)", padding: "16px 14px" }}>
        {isToday ? "No schedule yet — tap Plan today below." : "No schedule planned."}
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {planningStatus === "proposal" && (
        <p style={{
          alignSelf: "flex-start",
          background: "rgba(34,197,94,0.18)",
          color: "#2d6a4f",
          padding: "2px 8px",
          borderRadius: 99,
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          margin: "0 0 4px",
        }}>
          Proposed
        </p>
      )}
      {heroState && <MobileNowNextHero state={heroState} />}

      {past.length > 0 && (
        <button
          data-testid="earlier-disclosure"
          type="button"
          onClick={() => setEarlierExpanded((v) => !v)}
          style={{
            background: "transparent",
            border: "none",
            borderBottom: "1px dashed rgba(44,26,14,0.18)",
            padding: "8px 0 6px",
            textAlign: "left",
            fontFamily: "var(--font-literata)",
            fontSize: 11,
            color: "rgba(44,26,14,0.55)",
            cursor: "pointer",
            minHeight: 36,
          }}
        >
          {earlierExpanded ? "▾" : "▸"} Earlier today ({past.length}) — {past.slice(0, 3).map((p) => "task_name" in p.ref ? p.ref.task_name : p.ref.summary).join(", ")}
        </button>
      )}

      {earlierExpanded && past.map((e) => (
        <MobileTimelineRow key={`past-${e.startMs}`} {...rowProps(e, todoistCompletedIds)} />
      ))}

      {upcoming.length > 0 && (
        <p style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.12em", color: "rgba(44,26,14,0.4)", fontFamily: "var(--font-literata)", margin: "8px 0 2px" }}>
          Up next
        </p>
      )}
      {upcoming.map((e) => (
        <MobileTimelineRow key={`up-${e.startMs}`} {...rowProps(e, todoistCompletedIds)} />
      ))}

      {pushed.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          <p style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-faint)", marginBottom: 6, fontFamily: "var(--font-literata)" }}>
            Didn't make the cut
          </p>
          {pushed.map((p) => (
            <p key={p.task_id} style={{ fontSize: 12, color: "var(--text-faint)", fontFamily: "var(--font-literata)", lineHeight: 1.5, fontStyle: "italic" }}>
              {p.reason}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function rowProps(e: TimelineEntry, todoistCompletedIds: Set<string>): React.ComponentProps<typeof MobileTimelineRow> {
  if (e.kind === "gcal") {
    return { kind: "gcal", item: e.ref as GCalEvent };
  }
  const item = e.ref as ScheduledItem;
  return { kind: e.kind, item, isDone: todoistCompletedIds.has(item.task_id) };
}
