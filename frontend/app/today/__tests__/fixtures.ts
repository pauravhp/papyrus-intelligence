import type { DayData, ScheduledItem, GCalEvent, PushedItem } from "../TodayPage";

export const FIXED_NOW = new Date("2026-04-28T14:08:00-07:00");

export function task(overrides: Partial<ScheduledItem> = {}): ScheduledItem {
  return {
    task_id: "8675309",
    task_name: "Sample task",
    start_time: "2026-04-28T15:00:00-07:00",
    end_time: "2026-04-28T15:30:00-07:00",
    duration_minutes: 30,
    category: "admin",
    kind: "task",
    ...overrides,
  };
}

export function rhythm(overrides: Partial<ScheduledItem> = {}): ScheduledItem {
  return task({
    task_id: "proj_e1234567-89ab-cdef-0123-456789abcdef",
    task_name: "Gym",
    start_time: "2026-04-28T07:00:00-07:00",
    end_time: "2026-04-28T07:45:00-07:00",
    duration_minutes: 45,
    category: null,
    kind: "rhythm",
    ...overrides,
  });
}

export function gcal(overrides: Partial<GCalEvent> = {}): GCalEvent {
  return {
    id: "gcal-evt-1",
    summary: "Standup",
    start_time: "2026-04-28T15:30:00-07:00",
    end_time: "2026-04-28T16:00:00-07:00",
    color_hex: null,
    ...overrides,
  };
}

export function pushed(overrides: Partial<PushedItem> = {}): PushedItem {
  return {
    task_id: "9999",
    reason: "Couldn't place — duration missing",
    ...overrides,
  };
}

export function dayData(overrides: Partial<DayData> = {}): DayData {
  return {
    schedule_date: "2026-04-28",
    scheduled: [],
    pushed: [],
    confirmed_at: null,
    gcal_events: [],
    all_day_events: [],
    ...overrides,
  };
}

/** A representative mid-afternoon day: 3 past blocks, 1 current, 3 future, 1 GCal, 2 rhythms, 1 pushed. */
export function busyAfternoonDay(): DayData {
  return dayData({
    confirmed_at: "2026-04-28T08:30:00-07:00",
    scheduled: [
      task({ task_id: "proj_morning", task_name: "Morning workout", start_time: "2026-04-28T08:00:00-07:00", end_time: "2026-04-28T08:45:00-07:00", duration_minutes: 45, category: null, kind: "rhythm" }),
      task({ task_id: "p2", task_name: "Spec review", start_time: "2026-04-28T09:00:00-07:00", end_time: "2026-04-28T10:30:00-07:00", duration_minutes: 90, category: "deep_work" }),
      task({ task_id: "p3", task_name: "Email triage", start_time: "2026-04-28T11:00:00-07:00", end_time: "2026-04-28T11:30:00-07:00", duration_minutes: 30, category: "admin" }),
      task({ task_id: "cur", task_name: "API refactor", start_time: "2026-04-28T13:30:00-07:00", end_time: "2026-04-28T15:00:00-07:00", duration_minutes: 90, category: "deep_work" }),
      task({ task_id: "n1", task_name: "PR review", start_time: "2026-04-28T15:30:00-07:00", end_time: "2026-04-28T16:00:00-07:00", duration_minutes: 30, category: "admin" }),
      task({ task_id: "n2", task_name: "Writing draft", start_time: "2026-04-28T17:00:00-07:00", end_time: "2026-04-28T18:00:00-07:00", duration_minutes: 60, category: "deep_work" }),
      task({ task_id: "proj_dinner", task_name: "Dinner", start_time: "2026-04-28T18:30:00-07:00", end_time: "2026-04-28T19:30:00-07:00", duration_minutes: 60, category: null, kind: "rhythm" }),
    ],
    gcal_events: [
      gcal({ summary: "Standup", start_time: "2026-04-28T15:00:00-07:00", end_time: "2026-04-28T15:30:00-07:00" }),
    ],
    pushed: [pushed({ task_id: "9999", reason: "Couldn't place — duration missing" })],
  });
}
