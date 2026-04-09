# ARCHITECTURE.md

Token-efficient file map for new sessions. Read this before touching any code.

---

## Entry Point

**`main.py`** — CLI dispatcher and all command implementations. Contains `_cmd_plan_day` (full scheduling pipeline), `_cmd_review` (end-of-day review, quality score, reschedule proposals), `_cmd_add_task` (emergency replan), `_cmd_unplan`, `_cmd_check`, and the project budget CRUD commands (`_cmd_add_project`, `_cmd_update_project`, `_cmd_delete_project`, `_cmd_reset_project`, `_cmd_projects`). Also houses `_has_pre_meeting` and `_late_night_threshold_dt` helpers.

---

## `src/`

**`models.py`** — Four dataclasses: `CalendarEvent`, `TodoistTask`, `FreeWindow`, `ScheduledBlock`. No logic — pure data containers shared across all modules.

**`scheduler.py`** — Two core functions: `compute_free_windows()` subtracts calendar events + daily fixed blocks + buffers from the day to produce a list of `FreeWindow` objects; `pack_schedule()` slots enriched tasks into those windows using a cursor, enforces ultradian breaks, handles deep-work overflow to late night, and post-processes `back_to_back` flags. All hard scheduling rules live here, not in the LLM.

**`llm.py`** — Two-step Groq chain. `enrich_tasks()` (Step 1) calls `meta-llama/llama-4-scout-17b-16e-instruct` to assess cognitive load and scheduling flags per task. `generate_schedule()` (Step 2) calls the same model to order tasks and assign them to window types. Both wrap calls in retry-on-JSON-failure logic. LLM never sees raw clock times.

**`todoist_client.py`** — `TodoistClient` class wrapping REST API v1. Handles paginated task fetching (`_get_all_pages`), duration/priority label parsing, task updates, comment writes, and due-date clearing. `write_schedule_to_todoist()` is the top-level write-back function called after user confirmation.

**`calendar_client.py`** — `get_events()` queries all calendars (not just primary) via `calendarList().list()` and returns `CalendarEvent` objects for a given date range. Handles OAuth token refresh.

**`db.py`** — SQLite layer (`data/schedule.db`). `setup_database()` runs all migrations (ALTER TABLE wrapped in `try/except sqlite3.OperationalError`). Key tables: `task_history` (per-task scheduling metadata + completion data for habit learning), `schedule_log` (audit trail per run + `quality_score`), `project_budgets` (tracked time-budget projects). Main functions: `insert_task_history`, `upsert_task_completed`, `mark_task_partial`, `set_incomplete_reason`, `compute_quality_score`, `update_quality_score`, `get_todays_task_history`, `get_task_history_for_replan`.

---

## `tests/`

**`tests/test_scheduler.py`** — Unit tests for `compute_free_windows()` and `pack_schedule()`. Pure logic, no API calls, uses mock `CalendarEvent`/`TodoistTask` data.

**`tests/test_schema_and_review.py`** — Tests for DB migrations, `_compute_time_bucket`, `session_number_today` increment logic, `estimated_vs_actual_ratio` computation, `compute_quality_score` (including the regression for the pre-reschedule-write ordering fix), and `set_incomplete_reason`.

---

## Config & Data Files

**`context.json`** — Authoritative source for personal scheduling rules: sleep hours, weekend cutoffs, morning buffer, Flamingo/Banana colorId buffer sizes, daily fixed blocks, label vocabulary. Read at startup; passed to LLM and `compute_free_windows`.

**`productivity_science.json`** — Pre-compiled circadian/cognitive research. Loaded once at startup, injected into LLM prompts. Never re-fetched at runtime.

**`LEARNINGS.md`** — Hard-won API gotchas, architectural decisions, and bug post-mortems. Read this before touching any API client code or DB migrations.

**`data/schedule.db`** — SQLite database (gitignored). Created/migrated automatically by `setup_database()`.

**`snapshots/latest.json`** — Last confirmed schedule. Diff'd against new proposals before any Todoist write-back (gitignored).
