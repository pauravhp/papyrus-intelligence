# LEARNINGS.md

Hard-won API gotchas and architectural decisions. Read before touching any API client code.

---

## Todoist API

**Base URL:** `https://api.todoist.com/api/v1/` — REST v2 and Sync v9 both return 410 Gone.

**Writes use POST, not PATCH.** `PATCH /api/v1/tasks/{id}` → 405. Use `POST /api/v1/tasks/{id}` with a partial body.

**Task list responses are paginated.** v1 returns `{"results": [...], "next_cursor": ...}` — always use `_get_all_pages()`. Filter strings (`!date | today | overdue`, `@label`, `p1`) are unchanged from v2.

**Priority is inverted.** API: 4=P1, 3=P2, 2=P3, 1=P4. A new task with no priority set has `priority: 1` (P4/lowest). Use `_PRIORITY_LABEL = {4:"P1", 3:"P2", 2:"P3", 1:"P4"}` for display.

**Labels have no `@` prefix in API responses.** `@30min` in the UI → `"30min"` in the API. All in-code comparisons must omit the `@`. `context.json` uses `@label` for human readability only.

**Duration is read from labels, not the native field.** `DURATION_LABEL_MAP` in `todoist_client.py` maps `"30min"` → 30, etc. The matched label is stripped before passing to the LLM.

**Clearing due dates — field matters:**

- To fully remove due: `{"due_string": "no date"}` — removes date + datetime.
- To clear time only: `{"due_datetime": null}` — may leave a date-only entry, which `_parse_task` still reads as a `due_datetime`.
- `{"due": null}` is **silently ignored** — not a valid update field. Tasks retain their due after the call.

**"today & completed" filter returns active tasks too.** Unreliable for review — abandoned. Current approach: task_history as authoritative list, `GET /tasks/{id}` per task for status (404 = completed).

**`sync/v9/activity/get` is still live** despite sync v9/sync being deprecated. Reserved for Phase 7 habit tracking only — it returns stale historical events that cause false positives in real-time review.

---

## Architecture

**LLM orders, Python times.** The LLM never sees clock times — only `window_index`, `block_type`, and `duration_minutes`. All time math is in `pack_schedule()` (cursor-based). The LLM's only Step 2 jobs: order tasks (P1 before P2 before P3, no exceptions), match to window types, push only `never-schedule` flagged tasks. `pack_schedule` is the sole authority on overflow.

**`compute_free_windows()` returns raw continuous blocks** — no pre-chunking. `pack_schedule` owns all ultradian break insertion (`continuous_minutes >= 90` → 15min forced break).

**`compute_free_windows()` uses `max(morning_buffer, ceil5(now))` when `target_date == today`.** Added `now_override: datetime | None` parameter. If `start_override` is None and `target_date == date.today()` and `effective_now > effective_start`, the effective start is advanced to `ceil(now, 5min)` (same rounding algorithm as `--add-task`: `extra = (5 - minute % 5) % 5`, +5 if exactly on boundary with sub-minute precision). The `now_override` parameter is used in tests to inject a fixed "current time" without mocking. **Does not apply to tomorrow or past dates** — only `target_date == date.today()` triggers. `start_override` (used by `--add-task`) takes precedence and bypasses this check entirely.

**Mid-day `--plan-day` injects a hard rule into the LLM Step 2 prompt.** When `target_date == today` and `now > first_task_not_before`, `main.py` builds a `schedule_context` dict (copy of `context`) with an additional hard rule: "NOTE: It is currently HH:MM. The morning peak window has passed. Schedule from the afternoon secondary peak onwards." This is passed to `generate_schedule()` as `context=schedule_context` instead of `context=context`. The enrichment step (Step 1) is unaffected. Also emits: `[Scheduler] Mid-day plan: starting from HH:MM (X.Xh of morning already passed)`.

**Four task buckets in `--plan-day`:**

- `already_scheduled` — has `due_datetime` on target_date → blocks time, shown, skipped by LLM
- `pinned_other_day` — has `due_datetime` on another date → shown, skipped entirely
- `schedulable` — has `duration_minutes`, no `due_datetime` → passed to LLM
- `skipped` — no `duration_minutes` → listed with duration label hint

**`--review` source of truth: task_history for WHICH, Todoist for STATUS.**
`get_todays_task_history()` is the authoritative list (only tasks `--plan-day` confirmed). Per-task `GET /tasks/{id}`: None→completed, different date→externally rescheduled, same date→incomplete. Reschedule proposals use task_history rows (not Todoist API) for double-booking prevention.

**`--review --date yesterday`: reschedule proposals land on today, not tomorrow.** All reschedule candidate dates use `target_date + timedelta(days=days_ahead)`, never `date.today() + timedelta(days=days_ahead)`. When `target_date` is yesterday, `target_date + 1 == today`, so proposals correctly display as "Today". Day label logic: `cand_date == today` → "Today", `cand_date == today + 1` → "Tomorrow", otherwise `"%a %b %d"` format.

**`task_history` upsert never touches completion fields.** `insert_task_history()` does not overwrite `actual_duration_mins` or `completed_at` — those belong to `--review`. The `reschedule_count` CASE only increments when `scheduled_at` actually changes.

**SQLite migrations: deduplicate before adding UNIQUE constraints.** Run `DELETE FROM task_history WHERE id NOT IN (SELECT MAX(id) FROM task_history GROUP BY task_id)` unconditionally before `CREATE UNIQUE INDEX` — safe no-op on clean databases, prevents IntegrityError on dirty ones.

---

## Scheduling Rules

**`context.json` is authoritative over CLAUDE.md prose.** Weekend cutoff is 13:00 (not noon). Flamingo buffer is 15min each side (not 30min). Always read from structured `context.json` fields at runtime.

**`@deep-work` enforcement is in code, not just the prompt.** `pack_schedule` computes peak window as `first_task_not_before` → `+5h`. Tasks with `needs-deep-work-block` in `scheduling_flags` are auto-pushed if the cursor is past peak end.

**Budget session duration clamps to the available window.** `session_dur = min(session_max, largest_window)` — not `max(session_min, ...)`. When `largest_window < session_min`, the old formula produced an unschedulable duration, pushing the task every day. Schedule whatever fits; only skip if no windows exist.

**GCal: query all calendars, not just "primary".** Call `calendarList().list()` first, then query each calendar. Events on secondary calendars (shared, work) are otherwise invisible to the scheduler.

**`[Budget]` Todoist tasks appear in the skipped list** (no duration label), while the budget system simultaneously injects a synthetic `TodoistTask` with the correct session duration. Both are correct — the skipped entry is harmless noise.

---

## Optional Date Arguments (argparse pattern)

```python
parser.add_argument("--plan-day", nargs="?", const="", default=None, metavar="DATE")
```

- `--plan-day` alone → `""` (const) → resolves to today
- `--plan-day tomorrow` → resolved by `dateparser.parse(..., settings={"PREFER_DATES_FROM": "future"})`
- not passed → `None` → detect via `is not None` (not truthiness — `""` is falsy)

Same pattern applies to `--review` and `--unplan`.

---

## Model

Current: `meta-llama/llama-4-scout-17b-16e-instruct` (both ENRICH_MODEL and SCHEDULE_MODEL in `src/llm.py` and `main.py`). Switched from `meta-llama/llama-4-scout-17b-16e-instruct` after hitting the 100k daily TPD limit. Scout uses significantly fewer tokens per call.

---

## --add-task (Emergency Replan)

**replan_from = ceil(now, 5min).** Round current time up to the next 5-minute boundary for a clean replan start. If now is 14:37 → replan_from is 14:40.

**already_done heuristic.** `scheduled_at < replan_from OR completed_at IS NOT NULL` → treat as in-flight/done. Block their full time slot in `compute_free_windows` via `scheduled_tasks`. Never reschedule or clear these.

**start_override bypasses morning rules.** Passing `start_override=replan_from` to `compute_free_windows()` skips wake/buffer/weekend logic entirely and uses that datetime directly as `effective_start`.

**Urgent task forced first.** After LLM returns `ordered_tasks`, the urgent task is moved to index 0 regardless of LLM ordering. LLM may not honour the hard rule reliably.

**Diff computation.** Compare `new_by_id[task_id].start_time` vs `original_by_id[task_id].scheduled_at` parsed as datetime. Delta > 1min = MOVED. In `auto_pushed` and was in `to_replan` = PUSHED TO TOMORROW.

**schedule_log keeps all replan rows.** `replan_trigger = "--add-task"` column distinguishes replan rows from `--plan-day` rows. Never delete old rows on replan — it's an audit trail.

**"No room for urgent task itself".** If `new_task.id in pushed_ids` after pack_schedule, don't write anything. Offer: [1] Schedule first thing tomorrow [2] Cancel. Find tomorrow's first window with `duration >= task.duration_minutes`.

**Todoist write-back for tasks pushed to tomorrow.** `clear_task_due(task_id)` + `add_comment("Pushed from X by emergency insert: Y")` + `delete_task_history_row(task_id, date_str)`.

---

## Phase-3 Schema Additions (2026-04-08)

**ALTER TABLE ADD COLUMN migration pattern.** SQLite has no `ADD COLUMN IF NOT EXISTS`. The pattern used: wrap each `ALTER TABLE task_history ADD COLUMN {name} {type}` in `try/except sqlite3.OperationalError: pass`. This is safe because SQLite raises `OperationalError: duplicate column name` (not a generic error) when the column already exists. Using the base `Exception` class (as in the earlier `replan_trigger` migration) also works but catches too broadly — prefer `sqlite3.OperationalError` for precision.

**CASE expression in INSERT VALUES.** SQLite supports CASE expressions directly in the VALUES clause of an INSERT: `INSERT INTO t (col) VALUES (CASE WHEN ... THEN ... ELSE NULL END)`. This is how `estimated_vs_actual_ratio` is computed atomically on insert without a separate UPDATE round-trip.

**`excluded` references in ON CONFLICT DO UPDATE.** `excluded.column_name` refers to the value that *would have been inserted* (i.e., the new value), while `table_name.column_name` refers to the current value on disk. This lets you compare old vs new `scheduled_at` to detect reschedules and compute ratios against the pre-existing `estimated_duration_mins`.

**session_number_today: SELECT before INSERT within same connection.** Computing `COUNT(*) + 1` from task_history in the same connection before the INSERT is safe in SQLite — the SELECT and INSERT share the same implicit transaction within one `sqlite3.Connection`. The count is stable until commit.

**session_number_today not updated on upsert.** Intentionally omitted from `ON CONFLICT DO UPDATE SET`. When a task is replanned (same task_id, new scheduled_at), the session position it held on the original day is preserved. This keeps the column's meaning clean for training data.

**back_to_back computed as post-processing in pack_schedule().** Computed after all blocks are placed by sorting blocks chronologically and comparing adjacent end/start times. This correctly handles out-of-band DW late-night placements (which are placed earlier in the loop but appear later on the clock) without needing to track a separate cursor per task category.

**time_of_day_bucket boundary: morning_peak is [10:30, 14:30).** 10:30 + 4h = 14:30. Trough is [14:30, 16:30). Afternoon peak is [16:30, 18:00). Any time before 10:30 is classified as `late_night` (early-morning edge case). Times before the boundary in tests were incorrectly assumed to be trough — always derive from the 4h/2h spec, not intuition about "early afternoon".

**update_quality_score uses a subquery for ORDER BY.** SQLite does not support `ORDER BY` or `LIMIT` directly in an `UPDATE` statement. Workaround: `UPDATE ... WHERE id = (SELECT id FROM ... ORDER BY id DESC LIMIT 1)`. This correctly targets the most recent confirmed schedule_log row for a given date.

---

## --sync Architecture (2026-04-09)

**`insert_task_history` does not persist `completed_at`.** The INSERT statement in `insert_task_history` omits `completed_at` — it's only set by `upsert_task_completed` or direct SQL. Tests that need a pre-completed row must call `UPDATE task_history SET completed_at = ? WHERE task_id = ?` after inserting. Using `upsert_task_completed` also works.

**Step 4 (user-injected scan) runs even when there are no agent-scheduled rows.** Early return on empty `get_task_history_for_sync` would silently skip detection of user-scheduled tasks on otherwise unplanned days. Structure: skip Steps 2-3 (batch fetch + classify) if rows is empty, but always run Step 4. Only print "No scheduled tasks found" if both rows and n_injected are zero.

**Case B preserves the row, only flips `was_agent_scheduled=0`.** `scheduled_at` is NOT updated — the row keeps the original agent-planned time as a historical record. The row is then excluded from `get_task_history_for_sync` (which filters `COALESCE(was_agent_scheduled, 1) = 1`) and from `compute_quality_score` (same filter). It still appears in `get_task_ids_for_date` (no filter) so Step 4 won't re-inject it.

**Todoist 404 means completed OR deleted — indistinguishable.** `get_task_by_id` returns `None` for both. We set `completed_at` in either case, leave `actual_duration_mins` NULL. A `--review` completion always sets `actual_duration_mins`; a sync completion leaves it NULL. This is the only distinguishing signal between "completed via review" and "completed externally".

**`_fetch_one` catches `requests.exceptions.HTTPError` for 429 detection.** `get_task_by_id` calls `resp.raise_for_status()` for non-200/404/401 responses, which raises `HTTPError`. The retry wrapper checks `exc.response.status_code == 429`. Other HTTP errors fall through to `return row, "error"` (logged, task skipped for this sync run).

**`ThreadPoolExecutor` with `max_workers=4` is safe with `requests`.** The `requests` library is thread-safe; sessions/headers are read-only during the parallel fetch. Each worker gets a fresh `requests.get` call with the shared `client` instance. The `TodoistClient._get_inbox_project_id` call inside `get_task_by_id` is memoized after first call, making concurrent access safe in practice (worst case: two simultaneous first calls, both succeed and both cache the same value).

**`append_sync_diff` preserves existing `diff_json` content.** The existing `diff_json` column may contain a plan diff from `--plan-day`. The function parses the existing JSON (defaulting to `{}` on error), appends to a `"sync_changes"` list, and writes back. Original keys are preserved.

**`_display_schedule` must convert `due_datetime` to local tz before formatting.** Todoist API returns datetimes in UTC (e.g. `"2026-04-09T17:30:00Z"`). `strftime('%H:%M')` on a UTC datetime shows UTC time, not local time. A task at 10:30 AM PDT (UTC-7) was showing as "17:30" in the Already Scheduled section. Fix: pass `tz: ZoneInfo` to `_display_schedule` and call `dt.astimezone(tz)` before formatting. The `📌 Already scheduled` pre-display in `_cmd_plan_day` already did this correctly — only the final display function was missing the conversion.

**Todoist "today" filter matches `due.date`, not `due.datetime`.** A task with `due.date = "today"` but `due.datetime = tomorrow midnight UTC` (= midnight local) appears in the "today" filter. `get_todays_scheduled_tasks` doesn't filter by datetime date, so it would return such tasks. Sync Step 4 must explicitly verify `due_datetime.astimezone(tz).date() == target_date` before injecting. Without this, tasks like "Wipe down desk" (due April 12 midnight) get injected as user-injected for today.

**`ON CONFLICT DO NOTHING` is silent — always check `cursor.rowcount`.** `sync_inject_task` used `ON CONFLICT(task_id) DO NOTHING` but printed the "+" injection message unconditionally. On every re-run of `--sync` or `--plan-day`, already-injected tasks would re-print as newly injected. Fixed by returning `cursor.rowcount > 0` from `sync_inject_task` and only printing/counting when `was_inserted=True`.

**`--add-task` collision: budget tasks silently dropped when budget record missing.** If `budgets_map.get(bt.id)` returns None (project_budgets record not found for a `to_replan` task's ID), the old code silently `continue`d. The task stayed in `original_by_id` but never entered `all_schedulable`, so pack_schedule didn't know about it. Write-back section B saw `nb = None → continue` (no Todoist update). The task kept its old Todoist slot while another task was written to the same time. Fix: fall back to `replan_tasks.append(bt)` so the task goes through pack_schedule and write-back updates it. Also added a safety-net write-back section: any task in `original_by_id` that is neither in `new_by_id` nor `pushed_from_today` gets `clear_task_due` called unconditionally.

**`--sync` may miss deletions for user-injected tasks.** `get_task_history_for_sync` filtered `COALESCE(was_agent_scheduled, 1) = 1`, excluding all user-injected rows. A task manually scheduled by the user in Todoist, then deleted, would never be detected by sync. Fix: added a separate Step 4 sweep using `get_user_injected_for_deletion_check` which queries `was_agent_scheduled=0, completed_at IS NULL` rows and applies Case C only (no drift detection — user-injected tasks move freely). The sweep runs BEFORE the injection scan (Step 5) so newly-injected tasks aren't immediately flagged as deleted.

**`_fetch_one` in sync silently ate 410 (Gone) responses as "error".** `get_task_by_id` handles 404 internally (returns None). But if Todoist ever returns 410 for a deleted task, `resp.raise_for_status()` raises `HTTPError`, which `_fetch_one` caught and returned `"error"` — silently skipping the deletion. Fix: in the `HTTPError` handler, `status in (404, 410)` now returns `(row, None)` instead of `(row, "error")`.

**`--plan-day` budget session `else` branch used `session_min` as duration, not window size.** When no DW window met `session_min` (e.g., session_min=90, largest morning=60min), `session_dur = session_min = 90`. Pack_schedule then saw `duration(90) > remaining(60)` → `in_morning_no_fit = True` → routed to late night. If no late night window existed, pushed every day. The same bug was fixed in `add_task.py` previously (see LEARNINGS entry re: budget session clamp). Fix applied to `plan.py`: `else: session_dur = min(session_max, largest_window) if largest_window > 0 else session_min`.

**LLM priority ordering is unreliable — enforce it in code.** The LLM prompt instructs "P1 before P2 before P3, no exceptions" but the model occasionally violates this (P3 tasks filled the last 120min window, pushing a P1 budget task). Fixed by adding a stable sort on `ordered_tasks` after LLM Step 2, using `task_map[task_id].priority` as the key (descending, so 4=P1 sorts first). Stable sort preserves LLM sequence within each priority tier.

---

## Codebase Refactor (2026-04-09)

**`src/queries/` package split: reads and writes into separate files per domain.** `src/db.py` originally contained all SQL functions. Refactored to: `src/db.py` (schema/migrations/get_connection only), `src/queries/__init__.py` (re-exports all public functions), `src/queries/task_history_reads.py`, `src/queries/task_history_writes.py`, `src/queries/schedule_log.py`, `src/queries/sync_queries.py`. User explicitly rejected a single `queries.py` file and a single `task_history.py` — both too large. Rule: split reads and writes, one file per domain.

**`_compute_time_bucket` is private and must be imported directly from its submodule.** The function is not re-exported through `src/queries/__init__.py` (private implementation detail). Tests that verify it directly must use `from src.queries.task_history_writes import _compute_time_bucket`, not `from src.queries import _compute_time_bucket`. This is intentional — it signals the function is internal and should not be part of the public query API.

**Mock patch target must match where the name is bound, not where it's defined.** `src/sync_engine.py` imports `from src.todoist_client import TodoistClient` at module level. After module load, `sync_engine.TodoistClient` is a separate name binding. Patching `src.todoist_client.TodoistClient` after load does not affect this binding. All test patches must target `src.sync_engine.TodoistClient`. This is the standard Python mock rule: patch where the name is *used*, not where it's *defined*.

**`src/sync_engine.py` as a shared non-command module.** Both `plan.py` and `review.py` need auto-sync. The cross-command import rule ("no command file imports another command file") prevents `plan.py` importing from `sync.py`. Solution: `src/sync_engine.py` is a non-command shared module. `src/commands/sync.py` is a thin wrapper that calls `run_sync` from `src.sync_engine`. Both `plan.py` and `review.py` also import `run_sync` from `src.sync_engine` directly.

**`src/schedule_pipeline.py` for shared LLM chain steps.** `build_enriched_task_details` appeared identically in both `plan.py` and `add_task.py`. Extracted to `src/schedule_pipeline.py`. The `@waiting` label check for default `scheduling_flags` is preserved in the extracted function — both callers rely on this default. Zero logic change; pure extraction.

**`src/commands/plan.py` contains all local helpers needed by `--plan-day`.** Private helpers (`_late_night_threshold_dt`, `_has_pre_meeting`, `_display_schedule`) and constants (`ENRICH_MODEL`, `SCHEDULE_MODEL`, `_PRIORITY_LABEL`, `_PRIORITY_API`, `_WIDTH`) live in `plan.py`, not in shared modules. They are only used by this one command and promoting them to shared scope would be premature abstraction.

**Old test files must be deleted after refactor, not updated in place.** After `src/db.py` was slimmed down, the original `tests/test_schema_and_review.py` and `tests/test_sync.py` still imported functions from `src.db` that had moved to `src/queries/`. Rather than updating both the old tests and the new ones, the old files were deleted. Keeping them would have caused pytest to collect both, producing duplicate test IDs and stale import failures.

---

## --onboard Stage 1 (2026-04-10)

**`get_events()` fetches one day at a time — 14 sequential API calls for the scan window.** This takes ~5-10 seconds. Each call returns only events for that single date. Batching is not supported by the existing API; use a loop with `end="\r"` progress indicator to avoid appearing frozen.

**`_groq_json_call` is importable from `src.llm` within the project.** The underscore prefix signals it's not part of the public API surface — but within the same codebase it is fine to import directly. The onboard command uses it to get the JSON retry + logging behaviour without duplicating the code.

**LLM correctly identifies colorId semantics from event names alone.** Even without explicit buffer/type hints, the model correctly mapped colorId 4 (short ~42min events with "Lab Meeting", "call" in names) → meeting_or_call and colorId 5 (long ~170min events) → focus_block_or_event.

**The `_onboard_draft` key in `context.json.draft` is the Stage 2 handoff.** Stage 2 reads `_onboard_draft.questions_for_stage_2` and `_onboard_draft.status`. The key MUST be preserved through any draft edits. Stage 2 checks `status == "pending_stage_2_qa"` to detect a valid Stage 1 draft.

**Draft collision detection: if Stage 1 draft exists with `pending_stage_2_qa` status, skip re-scan.** This prevents accidentally wiping an answered Q&A draft by re-running `--onboard`. To force a re-scan, user must delete `context.json.draft` first.

**Architecture decision (2026-04-10): multi-user ownership model → Supabase, not per-user files.** The project is heading toward a FastAPI + Supabase (Postgres + auth) + Next.js web product. Users bring their own Todoist and Groq API keys. The CLI stays intact for local dev. The `_onboard_draft` metadata block in context.json maps directly to the `config` JSON column in the future `users` Supabase table — no schema change needed at handoff.

---

## --onboard Stage 2 (2026-04-10)

**Stage 2 applies answers directly to the draft — no LLM call.** `_set_nested(draft, field_path, value)` traverses the draft dict using dot-notation (e.g. `sleep.default_wake_time`, `calendar_rules.flamingo.buffer_before_minutes`) and writes the value in-place. Stage 1's LLM already produced the best-guess inference; Stage 2 just lets the user confirm or correct it. Stage 3 is the right place for any final consistency audit.

**`_set_nested` silently skips unknown paths.** If the LLM produces a `field` like `current_sleep_config.no_tasks_after` that doesn't match the draft structure, `_set_nested` returns without writing anything. This is intentional — never inject unknown keys into the draft.

**Numeric coercion for `_minutes` / `_min` fields.** If the field path ends with `_minutes` or `_min` and the answer string parses as an integer, it is stored as `int` (not string). This keeps the draft type-consistent with context.json.

**Enter with no input keeps the Stage 1 inference.** `value = raw if raw else inference`. If the inference itself is `None`, `""`, or `"null"`, the prompt shows no brackets and no value is written on empty input.

**KeyboardInterrupt / EOFError exits without saving.** Caught at the `input()` call; prints a clear message and returns immediately. The draft file is never opened for writing unless all questions complete normally.

**`import copy` must be at module level, not inside `_run_stage_2`.** The function uses `copy.deepcopy` on the incoming draft dict to avoid mutating the caller's reference. The top-level `import copy` covers this — a second `import copy` inside the function is redundant and was removed.
