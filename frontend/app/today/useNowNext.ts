import { useEffect, useState } from "react";
import type { ScheduledItem, GCalEvent } from "./TodayPage";

export type NowNextState =
  | { kind: "now"; current: ScheduledItem | GCalEvent; minutes_left: number; next: ScheduledItem | GCalEvent | null }
  | { kind: "free"; until: string; next: ScheduledItem | GCalEvent | null }
  | { kind: "done" };

export interface UseNowNextInput {
  scheduled: ScheduledItem[];
  gcal_events: GCalEvent[];
  now: Date;
}

interface Anchor {
  start: number;
  end: number;
  ref: ScheduledItem | GCalEvent;
}

function toAnchors(input: UseNowNextInput): Anchor[] {
  const a: Anchor[] = [];
  for (const s of input.scheduled) {
    a.push({ start: new Date(s.start_time).getTime(), end: new Date(s.end_time).getTime(), ref: s });
  }
  for (const g of input.gcal_events) {
    a.push({ start: new Date(g.start_time).getTime(), end: new Date(g.end_time).getTime(), ref: g });
  }
  a.sort((x, y) => x.start - y.start);
  return a;
}

export function computeNowNext(input: UseNowNextInput): NowNextState {
  const anchors = toAnchors(input);
  const now = input.now.getTime();
  const current = anchors.find((a) => a.start <= now && now < a.end);
  if (current) {
    const after = anchors.find((a) => a.start > current.end);
    return {
      kind: "now",
      current: current.ref,
      minutes_left: Math.floor((current.end - now) / 60_000),
      next: after?.ref ?? null,
    };
  }
  const future = anchors.find((a) => a.start > now);
  if (future) {
    const startIso =
      "start_time" in future.ref ? future.ref.start_time : (future.ref as GCalEvent).start_time;
    return { kind: "free", until: startIso, next: future.ref };
  }
  return { kind: "done" };
}

/** Re-renders every 60s. Inject `now` for testing. */
export function useNowNext(scheduled: ScheduledItem[], gcal_events: GCalEvent[]): NowNextState {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  return computeNowNext({ scheduled, gcal_events, now });
}
