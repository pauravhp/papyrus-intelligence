import { describe, it, expect } from "vitest";
import { computeNowNext } from "../useNowNext";
import { busyAfternoonDay, FIXED_NOW, gcal, task } from "./fixtures";

describe("computeNowNext", () => {
  it("returns kind:'now' when now is mid-block", () => {
    const day = busyAfternoonDay();
    const result = computeNowNext({ scheduled: day.scheduled, gcal_events: day.gcal_events, now: FIXED_NOW });
    expect(result.kind).toBe("now");
    if (result.kind !== "now") return;
    expect(result.current.task_name).toBe("API refactor");
    expect(result.minutes_left).toBe(52);
    expect(result.next?.task_name).toBe("PR review");
  });

  it("returns kind:'free' when now is between blocks", () => {
    const between = new Date("2026-04-28T11:45:00-07:00");
    const day = busyAfternoonDay();
    const result = computeNowNext({ scheduled: day.scheduled, gcal_events: day.gcal_events, now: between });
    expect(result.kind).toBe("free");
    if (result.kind !== "free") return;
    expect(result.next && "task_name" in result.next ? result.next.task_name : null).toBe("API refactor");
  });

  it("returns kind:'done' when after last block of the day", () => {
    const lateNight = new Date("2026-04-28T23:30:00-07:00");
    const day = busyAfternoonDay();
    const result = computeNowNext({ scheduled: day.scheduled, gcal_events: day.gcal_events, now: lateNight });
    expect(result.kind).toBe("done");
  });

  it("considers GCal events as anchors for current/next", () => {
    const inGcal = new Date("2026-04-28T15:10:00-07:00"); // mid-Standup, post-API-refactor
    const result = computeNowNext({
      scheduled: [task({ task_id: "after-standup", task_name: "Late deep", start_time: "2026-04-28T16:00:00-07:00", end_time: "2026-04-28T17:00:00-07:00" })],
      gcal_events: [gcal({ summary: "Standup", start_time: "2026-04-28T15:00:00-07:00", end_time: "2026-04-28T15:30:00-07:00" })],
      now: inGcal,
    });
    expect(result.kind).toBe("now");
    if (result.kind !== "now") return;
    expect("summary" in result.current ? result.current.summary : null).toBe("Standup");
  });

  it("returns the right minutes_left rounded down", () => {
    const justAfterStart = new Date("2026-04-28T13:31:30-07:00");
    const day = busyAfternoonDay();
    const result = computeNowNext({ scheduled: day.scheduled, gcal_events: day.gcal_events, now: justAfterStart });
    expect(result.kind).toBe("now");
    if (result.kind !== "now") return;
    expect(result.minutes_left).toBe(88); // 90 - 1.5min, floored
  });
});
