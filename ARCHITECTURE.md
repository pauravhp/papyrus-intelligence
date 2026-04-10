# ARCHITECTURE.md

Token-efficient file map for new sessions. Read this before touching any code.

---

## Entry Point

**`main.py`** — Pure CLI router (~200 lines). Argparse setup, `_load_config()`, `_resolve_target_date()`, and lazy dispatch to `src/commands/`. No command logic.

---

## `src/`

**`models.py`** — Four dataclasses: `CalendarEvent`, `TodoistTask`, `FreeWindow`, `ScheduledBlock`. No logic — pure data containers shared across all modules.

**`scheduler.py`** — Two core functions: `compute_free_windows()` subtracts calendar events + daily fixed blocks + buffers to produce `FreeWindow` objects; `pack_schedule()` slots enriched tasks into windows using a cursor, enforces ultradian breaks, handles deep-work late-night overflow, and post-processes `back_to_back` flags. All hard scheduling rules live here, not in the LLM.

**`llm.py`** — Two-step Groq chain. `enrich_tasks()` (Step 1) calls `meta-llama/llama-4-scout-17b-16e-instruct` to assess cognitive load and scheduling flags per task. `generate_schedule()` (Step 2) orders tasks and assigns them to window types. Both wrap calls in retry-on-JSON-failure logic. LLM never sees raw clock times.

**`todoist_client.py`** — `TodoistClient` class wrapping REST API v1. Handles paginated task fetching, duration/priority label parsing, task updates, comment writes, and due-date clearing. `write_schedule_to_todoist()` is the top-level write-back called after user confirmation.

**`calendar_client.py`** — `get_events()` queries all calendars (not just primary) via `calendarList().list()` and returns `CalendarEvent` objects for a given date range. Handles OAuth token refresh.

**`db.py`** — Schema and migrations only. `get_connection()` returns a sqlite3 connection. `setup_database()` creates tables and runs all `ALTER TABLE` migrations (wrapped in `try/except sqlite3.OperationalError`). Tables: `task_history`, `schedule_log`, `project_budgets`. No SQL query functions — those live in `src/queries/`.

**`sync_engine.py`** — Shared non-command module. `run_sync(context, target_date, silent)` is the full `--sync` pipeline (5-step Todoist drift detection). Imported by `src/commands/sync.py` (thin wrapper), `src/commands/plan.py`, and `src/commands/review.py` for auto-sync. Lives outside `src/commands/` to avoid cross-command imports.

**`schedule_pipeline.py`** — Shared LLM pipeline helper. `build_enriched_task_details(tasks, enriched_map, priority_label_map)` merges enrichment output with raw task fields into the combined dict list fed to `generate_schedule()`. Used by both `commands/plan.py` and `commands/add_task.py`.

---

## `src/commands/`

**`plan.py`** — `cmd_plan_day(context, target_date)`. Full `--plan-day` pipeline: fetch tasks + events → enrich → compute windows → generate schedule → diff → confirm → write-back. Also houses private helpers `_late_night_threshold_dt`, `_has_pre_meeting`, `_display_schedule`.

**`review.py`** — `cmd_review(context, target_date)`. End-of-day review: auto-sync, per-task status checks, partial completion prompts, reschedule proposals, project budget hour capture, quality score write.

**`add_task.py`** — `cmd_add_task(context, search_text, target_date)`. Emergency replan: find urgent task → build replan window from `ceil(now, 5min)` → recompute free windows → LLM chain → display diff → confirm → write-back. `_handle_no_room` handles the case where the urgent task itself doesn't fit.

**`sync.py`** — Thin wrapper around `run_sync` from `src.sync_engine`. Exposes `cmd_sync(context, target_date, silent)`.

**`onboard.py`** — `cmd_onboard(context)`. Three-stage flow, auto-routed on each re-run by `_onboard_draft.status`. Stage 1 (`pending_stage_2_qa`): scans 14 days of GCal, pattern detection, LLM proposes draft config from `context.template.json` base, writes `context.json.draft`. Stage 2 (`pending_stage_3_audit`): `_run_stage_2()` presents questions interactively, applies answers via `_set_nested()` (dot-notation path). Stage 3 (promote): `_run_stage_3()` fetches today's GCal events, calls `compute_free_windows()` with the draft config, displays free windows + buffered events for visual confirmation, then on "y" strips `_onboard_draft`, backs up `context.json` → `context.json.bak`, writes clean draft as `context.json`, and removes the draft file. Never writes to GCal or Todoist.

**`check.py`** — `cmd_check(context)`. Validates the full data pipeline (GCal + Todoist + scheduler) without calling the LLM. Safe to run any time.

**`status.py`** — `cmd_status(context)`. Displays today's confirmed schedule and task history state.

**`unplan.py`** — `cmd_unplan(context, target_date, task_name)`. Clears a confirmed plan (or single task) from `schedule_log` and resets Todoist due dates/durations.

**`projects.py`** — CRUD commands for project budgets: `cmd_add_project`, `cmd_update_project`, `cmd_delete_project`, `cmd_reset_project`, `cmd_projects`. Manages `project_budgets` table and the corresponding synthetic `TodoistTask` entries.

---

## `src/prompts/`

**`enrich.py`** — Prompt template for Step 1 (task enrichment). `build_enrich_prompt(tasks, label_vocab, context, science_json)` returns the full system + user prompt string.

**`schedule.py`** — Prompt template for Step 2 (schedule generation). `build_schedule_prompt(enriched_tasks, free_windows, date_str, context, science_summary)` returns the full system + user prompt string.

**`onboard.py`** — Prompt template for `--onboard` Stage 1. `build_onboard_prompt(patterns, existing_context)` returns messages for the LLM to produce `proposed_config` + `questions_for_stage_2`. The `field` values in questions use dot-notation paths into the draft (e.g. `sleep.default_wake_time`).

---

## `src/queries/`

**`__init__.py`** — Re-exports all public query functions from the four submodules. Single import point: `from src.queries import insert_task_history, get_todays_task_history, ...`

**`task_history_reads.py`** — Read-only queries against `task_history`: `get_todays_task_history`, `get_task_history_for_sync`, `get_task_history_for_replan`, `get_task_ids_for_date`, `get_all_active_budgets` (also reads `project_budgets`).

**`task_history_writes.py`** — Write queries against `task_history`: `insert_task_history`, `upsert_task_completed`, `mark_task_partial`, `set_incomplete_reason`. Also houses private `_compute_time_bucket` (not re-exported — import directly from this submodule if needed in tests).

**`schedule_log.py`** — All queries against `schedule_log`: `insert_schedule_log`, `get_latest_schedule_log`, `confirm_schedule_log`, `append_sync_diff`, `compute_quality_score`, `update_quality_score`.

**`sync.py`** — Sync-specific write helpers: `sync_apply_case_a`, `sync_apply_case_b`, `sync_apply_case_c`, `sync_inject_task`. Called exclusively by `src/sync_engine.py`.

**`budgets.py`** — Read/write queries against `project_budgets`: `get_all_active_budgets`, `compute_deadline_pressure`, `upsert_project_budget`, `delete_project_budget`, `reset_project_budget_hours`.

---

## `tests/`

**`tests/core/test_scheduler.py`** — Unit tests for `compute_free_windows()` and `pack_schedule()`. Pure logic, no API calls, uses mock `CalendarEvent`/`TodoistTask` data. 26 tests.

**`tests/commands/test_schema_and_review.py`** — Tests for DB migrations, `_compute_time_bucket`, `session_number_today` increment, `estimated_vs_actual_ratio`, `compute_quality_score`, and `set_incomplete_reason`. 23 tests.

**`tests/commands/test_sync.py`** — Tests for the full `--sync` pipeline via `run_sync`. Patches `src.sync_engine.TodoistClient` (not `src.todoist_client.TodoistClient` — sync_engine binds the name at module load). 24 tests.

---

## Config & Data Files

**`context.json`** — Authoritative source for personal scheduling rules: sleep hours, weekend cutoffs, morning buffer, Flamingo/Banana colorId buffer sizes, daily fixed blocks, label vocabulary. Read at startup; passed to LLM and `compute_free_windows`. During `--onboard`, only `user.timezone` and `calendar_ids` are read from this file (scan credentials); the draft base comes from `context.template.json`.

**`context.template.json`** — Committed to git. Minimal schema with nulls for all user-specific fields (`user.name`, `user.timezone`, `calendar_ids`, sleep times, colorIds, `daily_blocks`, `projects`) and universal defaults for everything else (`label_vocabulary`, `rules`, `scheduling`, buffer minutes). Used as the deepcopy base in `_build_draft_context()` so every new user's onboarding draft starts clean.

**`productivity_science.json`** — Pre-compiled circadian/cognitive research. Loaded once at startup, injected into LLM prompts. Never re-fetched at runtime.

**`LEARNINGS.md`** — Hard-won API gotchas, architectural decisions, and bug post-mortems. Read before touching any API client code or DB migrations.

**`data/schedule.db`** — SQLite database (gitignored). Created/migrated automatically by `setup_database()`.

**`snapshots/latest.json`** — Last confirmed schedule. Diff'd against new proposals before any Todoist write-back (gitignored).
