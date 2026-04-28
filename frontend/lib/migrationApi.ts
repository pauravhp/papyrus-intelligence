// frontend/lib/migrationApi.ts
//
// Typed wrappers for the migration-assistant import routes:
//   POST /api/import/convert
//   POST /api/import/commit
//
// Mirrors api/routes/import_tasks.py request/response models.
// Uses apiPost<T> from @/utils/api — callers supply the bearer token.

import { apiPost } from "@/utils/api";

// ---------------------------------------------------------------------------
// Shared primitive types
// ---------------------------------------------------------------------------

export type CategoryLabel = "@deep-work" | "@admin" | "@quick" | null;

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export type DurationMinutes = 10 | 15 | 30 | 45 | 60 | 75 | 90 | 120 | 180;

// ---------------------------------------------------------------------------
// /api/import/convert
// ---------------------------------------------------------------------------

export type TaskProposal = {
  content: string;
  priority: 1 | 2 | 3 | 4;
  duration_minutes: DurationMinutes;
  category_label: CategoryLabel;
  deadline: string | null; // ISO date
  reasoning: string;
};

export type RhythmProposal = {
  name: string;
  scheduling_hint: string;
  sessions_per_week: number; // 1-21
  session_min_minutes: DurationMinutes;
  session_max_minutes: DurationMinutes;
  days_of_week: Weekday[];
  reasoning: string;
};

export type ConvertResponse = {
  tasks: TaskProposal[];
  rhythms: RhythmProposal[];
  unmatched: string[];
};

// ---------------------------------------------------------------------------
// /api/import/commit
// ---------------------------------------------------------------------------

/** Named *Record* to avoid clashing with the built-in Error type. */
export type CommitErrorRecord = {
  kind: "task" | "rhythm" | "calendar";
  name: string;
  reason: string;
};

export type CommitResponse = {
  tasks_created: number;
  rhythms_created: number;
  errors: CommitErrorRecord[];
  todoist_reconnect_required: boolean;
  papyrus_calendar_id: string | null;
  calendar_scope_upgrade_required: boolean;
};

// ---------------------------------------------------------------------------
// Wrappers
// ---------------------------------------------------------------------------

/**
 * POST /api/import/convert
 *
 * Converts raw text (e.g. a pasted task list) into structured TaskProposal
 * and RhythmProposal objects via a single LLM call.
 *
 * Throws ApiError on non-2xx responses.
 * Relevant error codes: "input_too_short" | "input_too_long" | "parse_failed"
 */
export async function convertMigration(
  rawText: string,
  token: string,
): Promise<ConvertResponse> {
  return apiPost<ConvertResponse>("/api/import/convert", { raw_text: rawText }, token);
}

/**
 * POST /api/import/commit
 *
 * Commits approved proposals — creates Todoist tasks, Papyrus rhythms, and
 * (if needed) the Papyrus GCal calendar.
 *
 * Throws ApiError on non-2xx responses.
 * Relevant error codes: "todoist_reconnect_required"
 */
export async function commitMigration(
  tasks: TaskProposal[],
  rhythms: RhythmProposal[],
  token: string,
): Promise<CommitResponse> {
  return apiPost<CommitResponse>("/api/import/commit", { tasks, rhythms }, token);
}
