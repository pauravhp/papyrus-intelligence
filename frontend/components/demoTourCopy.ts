// frontend/components/demoTourCopy.ts
//
// Static text-bubble copy for the migration assistant demo.
// Bubble content per step; placeholders (e.g. {tasksN}) are filled at render time.

export type TourStep =
  | "reveal"
  | "post_commit"
  | "auto_plan"
  | "schedule_walkthrough"
  | "settings_nudge"
  | "gcal_confirm"
  | "done"
  | "tiny_batch_warning"
  | "schedule_walkthrough_failed";

export const TOUR_COPY: Record<TourStep, { title: string; body: string }> = {
  reveal: {
    title: "Take a look",
    body: "I found {tasksN} task(s) and {rhythmsN} recurring routine(s). Here's how I'd organise each one — edit anything that looks off before saving.",
  },
  post_commit: {
    title: "Saved",
    body: "Tasks are now in your Todoist. Routines are in Papyrus. Let me show you what scheduling looks like.",
  },
  auto_plan: {
    title: "Planning…",
    body: "Generating today's schedule from what you just imported.",
  },
  schedule_walkthrough: {
    title: "Here's your day",
    body: "{summary}",
  },
  settings_nudge: {
    title: "Quick settings check",
    body: "I used some defaults — meal times, end-of-day cutoff. Want to fine-tune before we put this on your calendar?",
  },
  gcal_confirm: {
    title: "Last step — calendar",
    body: "Ready to put this on your calendar? I'll create a separate Papyrus calendar in Google Calendar so it stays out of the way.",
  },
  done: {
    title: "You're set",
    body: "Come back tomorrow morning, hit Plan today, and we'll do this for real.",
  },
  tiny_batch_warning: {
    title: "Just a small batch",
    body: "Papyrus shines once you've added more tasks. You'll see what I mean as you use it more.",
  },
  schedule_walkthrough_failed: {
    title: "Couldn't generate a plan",
    body: "Your tasks are saved. Try Plan today manually from the dashboard.",
  },
};

export const SKIP_LABEL = "I'll explore on my own";
