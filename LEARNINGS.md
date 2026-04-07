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

**Four task buckets in `--plan-day`:**

- `already_scheduled` — has `due_datetime` on target_date → blocks time, shown, skipped by LLM
- `pinned_other_day` — has `due_datetime` on another date → shown, skipped entirely
- `schedulable` — has `duration_minutes`, no `due_datetime` → passed to LLM
- `skipped` — no `duration_minutes` → listed with duration label hint

**`--review` source of truth: task_history for WHICH, Todoist for STATUS.**
`get_todays_task_history()` is the authoritative list (only tasks `--plan-day` confirmed). Per-task `GET /tasks/{id}`: None→completed, different date→externally rescheduled, same date→incomplete. Reschedule proposals use task_history rows (not Todoist API) for double-booking prevention.

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
