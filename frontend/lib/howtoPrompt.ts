// frontend/lib/howtoPrompt.ts
export const HOWTO_PROMPT = `Papyrus is an AI scheduling coach that connects Todoist (tasks) and Google Calendar (events) to plan your day.

What Papyrus does:
Each morning, tell it anything in chat ("plan my day", "low energy today"). It reads your tasks and calendar, proposes a time-blocked schedule, and writes it to Google Calendar once you confirm.

Required Todoist setup:

1. Scheduling labels — tells Papyrus how to place each task:
   @deep-work — focused, uninterrupted work. Scheduled in peak energy windows only.
   @admin — low-cognitive tasks (emails, coordination). Flexible timing.
   @quick — under 15 minutes. Batched into transition gaps.
   @waiting — blocked on someone else. Never auto-scheduled.
   @in-progress — partially done. Treated as higher urgency.
   @recurring-review — weekly review. Not in daily plan unless requested.

2. Time estimate labels — REQUIRED. Tasks without one are skipped entirely:
   @15min / @30min / @60min / @90min / @2h / @3h
   The 3h cap exists because your brain works in ~90-minute ultradian focus cycles (BRAC).
   Beyond two cycles, cognitive output drops sharply regardless of motivation.
   Papyrus never schedules a single block longer than 90 minutes.

3. Priority flags:
   P1 — schedule today, no exceptions
   P2 — this week, fit where possible
   P3 — someday, only if time allows
   P4 — reference only, never scheduled

Context notes (optional but powerful):
Before planning, say things like:
- "plan light today, low energy"
- "I have a clear morning, prioritise deep work"
- "skip anything physical, I'm under the weather"
This changes which tasks get scheduled, when, and how tightly.

Two planning moments:
- Morning: type anything in chat to get a proposed day plan
- Afternoon (after noon): use the Replan button in Today view to triage what happened
  and get a revised afternoon schedule. One slip does not have to cascade into losing the whole day.

Ask me anything about setting up Todoist for Papyrus, writing better context notes,
or understanding why Papyrus scheduled something a certain way.`
