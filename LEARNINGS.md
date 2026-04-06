# LEARNINGS.md

Unexpected findings, API gotchas, and hard-won knowledge from each build phase.
Read this before touching any API client code.

---

## Phase 0 — Foundation (2026-04-05)

### Todoist API deprecation: REST v2 / Sync v9 → `/api/v1/`

**What happened:** The Todoist REST v2 base URL (`https://api.todoist.com/rest/v2/`)
and Sync v9 (`https://api.todoist.com/sync/v9/`) both return HTTP 410 Gone with the
message: *"This endpoint is deprecated. Update your use case to rely on the new API
endpoints, available under /api/v1/ prefixes."*

**New base URL:** `https://api.todoist.com/api/v1/`

**Breaking changes in v1:**

| Aspect | REST v2 (old) | API v1 (new) |
|--------|---------------|--------------|
| Base URL | `https://api.todoist.com/rest/v2/` | `https://api.todoist.com/api/v1/` |
| Task list response | Bare JSON array `[...]` | Paginated object `{"results": [...], "next_cursor": ...}` |
| Project list response | Bare JSON array | Paginated object `{"results": [...]}` |
| Inbox project field | `is_inbox_project: true` | `inbox_project: true` |
| Sync endpoint | `https://api.todoist.com/sync/v9/sync` | **410 Gone — deprecated.** Use individual `POST /api/v1/tasks/{id}` calls instead. |

**How to handle pagination:** Always call `_get_all_pages()` which loops on
`next_cursor` until exhausted. Never assume a single response contains all items.

**Filter strings:** The `filter` query parameter syntax (`!date | today | overdue`,
`@label`, `p1`, etc.) appears unchanged in v1.

**Duration field:** ~~Still `{"amount": int, "unit": "minute"}` — unchanged.~~
**Superseded by Phase 1 change:** Duration is now read exclusively from task labels,
not from Todoist's native duration field. See "Duration via labels" entry below.

**Deadline field:** Still `{"date": "YYYY-MM-DD"}` — unchanged.

---

### Google Calendar `colorId` — verify on first run

CLAUDE.md lists `"4"` = Flamingo and `"5"` = Banana, but these are *default calendar*
color IDs. If the user has custom calendar themes or events inherit from a non-primary
calendar, the IDs may differ. Run `--check` and inspect the `colorId=` output on every
event before trusting buffer calculations.

---

### `zoneinfo` vs `pytz`

The venv has no `pytz`. Use `from zoneinfo import ZoneInfo` (Python 3.9+ stdlib).
The user's timezone string `"PST/Vancouver"` is not a valid IANA zone — normalize it
to `"America/Vancouver"` at all entry points. A `_TIMEZONE_ALIASES` dict handles this
in both `calendar_client.py` and `scheduler.py`.

---

### Weekend rule is 13:00, not 12:00

CLAUDE.md says "nothing before noon" on Fri/Sat/Sun, but `context.json` has
`"weekend_nothing_before": "13:00"`. **`context.json` is authoritative.** Always read
scheduling rules from `context.json` at runtime, not from the CLAUDE.md prose summary.

---

### Flamingo buffer is 15 min, not 30 min

CLAUDE.md Section 6 mentions "30min buffer" for Flamingo, but the structured
`context.json` `calendar_rules.flamingo` has `buffer_before_minutes: 15` and
`buffer_after_minutes: 15`. Banana (events) have 30 min each side. The structured
data wins — always read from `calendar_rules` in code.

---

## Phase 1 — LLM Chain (2026-04-05)

### Duration is read from labels, not Todoist's native field

**Why:** The user creates tasks directly in Todoist and communicates estimated duration
via labels (`@15min`, `@30min`, `@60min`, `@90min`, `@2h`, `@3h`), not via the native
duration field. Tasks without a duration label are skipped — they are not schedulable.

**Implementation:** `DURATION_LABEL_MAP` in `todoist_client.py`. The matched duration
label is stripped from the `labels` list before the task is passed to the LLM, so it
doesn't appear as a scheduling constraint tag alongside `@deep-work`, `@admin`, etc.

**Tasks without a duration label:** Skipped at the pre-scheduling filter step. The CLI
prints them with a hint: "Add @15min / @30min / ... label in Todoist to schedule these."

---

### Todoist labels have no `@` prefix in API responses

Labels entered as `@30min` in the Todoist UI are stored and returned by the API as
`"30min"` — without the `@`. The `@` is only Todoist's reference syntax for the filter
query language and the UI; it is never part of the stored value.

**Impact:** `DURATION_LABEL_MAP` keys must be `"15min"`, `"30min"`, etc., not `"@15min"`.
Any in-code label comparisons (`"waiting" in t.labels`, not `"@waiting"`) must omit the `@`.
The `context.json` label_vocabulary uses `@label` convention for human readability only.

---

### Task updates use POST, not PATCH

`PATCH /api/v1/tasks/{task_id}` returns **405 Method Not Allowed**.
Use **`POST /api/v1/tasks/{task_id}`** with a partial JSON body for updates.
This is consistent with Todoist's historical REST v2 behaviour (also POST for updates).

---

### Todoist priority inversion — API integer ≠ display label

The Todoist API uses an inverted priority scale:

| Display (Todoist app) | API integer (`priority` field) |
|-----------------------|-------------------------------|
| P1 (urgent)           | 4                             |
| P2 (high)             | 3                             |
| P3 (medium)           | 2                             |
| P4 (default/unset)    | 1                             |

**Gotcha:** A brand-new task with no priority set has `priority: 1` in the API response,
which maps to P4 (the lowest level). It is easy to misread this as "P1 = high priority"
— it is the opposite. Always use `_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}`
for display and `_PRIORITY_API = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}` when writing back.

When writing priority back to Todoist via `PATCH /api/v1/tasks/{task_id}`:
```json
{"priority": 4}   // sets P1
{"priority": 1}   // sets P4 (default)
```

---

### Architecture: LLM produces ordered list, Python does all time math

**Why:** The LLM was outputting arbitrary `start_time`/`end_time` values that violated
free window boundaries (e.g., scheduling at 09:00 on a day where windows start at 13:00).
The LLM cannot reliably do cursor arithmetic across chunked windows with breaks.

**Permanent architecture:**

- **Step 2 LLM output** (`generate_schedule`): `ordered_tasks[]` — a ranked list with
  `duration_minutes`, `can_be_split`, `break_after_minutes`, `block_label`,
  `placement_reason`, `scheduling_flags`. No clock times anywhere.

- **`pack_schedule(ordered_tasks, free_windows, context, target_date)`** in `scheduler.py`:
  Cursor-based algorithm that handles all clock math. Returns
  `(list[ScheduledBlock], auto_pushed)`.

**`pack_schedule` algorithm:**

1. For each task in LLM-ordered list:
2. If `continuous_minutes >= MAX_WINDOW_MINUTES` (90): advance cursor by
   `BREAK_BETWEEN_WINDOWS_MINUTES` (15), reset counter.
3. Call `_advance()` to move cursor into the next valid window slot.
4. Compute `remaining = current_window.end - cursor`.
5. If `duration <= remaining`: schedule in place, advance cursor.
6. Elif `can_be_split and remaining >= 30`: split — part 1 fills current window,
   part 2 goes to next window. Both `ScheduledBlock`s have `split_session=True`.
7. Else: skip to next window; if it fits, schedule there. Otherwise push to tomorrow.
8. Apply `break_after_minutes` if non-zero.

**`_format_windows` in llm.py** now hides clock times from the LLM:
shows only `window_index`, `block_type`, `duration_minutes`, and
`total_available_minutes`. This prevents the model from even attempting time arithmetic.

---

### Window chunking removed — pack_schedule owns all break logic (2026-04-05)

**What changed:** `compute_free_windows()` no longer pre-chunks windows into 90-min
blocks. It returns raw continuous free blocks. A free Sunday afternoon from 13:00–23:00
is now ONE `FreeWindow(start=13:00, end=23:00, duration_minutes=600)`, not 6 chunks.

**Why:** Pre-chunking created phantom windows that didn't correspond to real blocked
time, and made split logic in `pack_schedule` brittle. `pack_schedule` owns all break
insertion via the `continuous_minutes >= MAX_WINDOW_MINUTES` check.

**Effect on tasks:**
- A `@2h` task schedules as a single unbroken 120-min block (no split).
- A `@3h` task schedules as a single 180-min block.
- Splits only happen when a task can't fit in the remaining window at all.

**Constants retained:** `MAX_WINDOW_MINUTES` (90) and `BREAK_BETWEEN_WINDOWS_MINUTES`
(15) remain in `scheduler.py` — still used by `pack_schedule`.

---

### Todoist Sync API v9 also returns 410 Gone (2026-04-05)

`POST https://api.todoist.com/sync/v9/sync` returns **410 Gone** — it is deprecated
alongside REST v2. The previous note marked it as "Unknown — avoid"; that was correct.

**Replacement write-back pattern:** Individual REST v1 calls per task.

`POST /api/v1/tasks/{task_id}` with:
```json
{
  "due_datetime": "2026-04-05T13:00:00-07:00",
  "duration": 120,
  "duration_unit": "minute"
}
```

- `due_datetime` — ISO 8601 with timezone offset. Use `block.start_time.isoformat()`
  (the datetime is already tz-aware, so this produces the correct offset).
- To clear a due date (pushed tasks): `{"due_datetime": null}`.
- Split sessions: write part 1 only. Post split comment via `POST /api/v1/comments`.

**CLAUDE.md Rule 4 is now outdated.** The "single Sync API batch call" rule no longer
applies since Sync v9 is gone. We use individual REST v1 calls, one per task.

---

### --plan-day date argument via dateparser (2026-04-05)

`dateparser.parse(date_str, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False})`
handles "tomorrow", "monday", "next friday", "2026-04-07" naturally.

**argparse pattern for an optional argument value** (not a boolean flag):
```python
parser.add_argument("--plan-day", nargs="?", const="", default=None, metavar="DATE")
```
- `--plan-day` (no arg) → `args.plan_day = ""` (const) → resolves to today
- `--plan-day tomorrow` → `args.plan_day = "tomorrow"` → resolved by dateparser
- not passed → `args.plan_day = None` (default) → flag not active

**Key:** check `args.plan_day is not None` (not truthiness) to detect whether the flag
was passed at all, since `""` (today) is falsy.

---

### task_history insert pattern (2026-04-05)

One row per confirmed scheduled block (skip split_part == 2 to avoid double-logging).
Fields:
- `task_id`, `task_name`, `project_id` — from original TodoistTask
- `estimated_duration_mins` — from the ScheduledBlock (not the original label duration,
  which may differ for split sessions)
- `scheduled_at` — block.start_time.isoformat()
- `day_of_week` — today.strftime("%A")
- `cognitive_load_label` — from enriched dict (Step 1 output), key "cognitive_load"
- `was_late_night_prior` — passed through from GCal detection in main.py

---

### Pre-scheduling flow order: filter → enrich → confirm → schedule

The `--plan-day` pipeline runs in this exact order:

1. **Filter** — split tasks into `schedulable` (has duration label) and `skipped` (no label).
   Only schedulable tasks continue. Skipped tasks are listed with a hint to add a label.

2. **Enrich** (LLM Step 1) — run only on schedulable tasks. For any task with
   `priority == 1` (P4/unset), the model additionally returns `suggested_priority`
   and `suggested_priority_reason`.

3. **Confirm priorities** — if any enriched task has `suggested_priority`, display
   suggestions interactively. User types `y` (accept all) or `1=P3,2=P2` (overrides).
   Accepted priorities are written to Todoist immediately via
   `PATCH /api/v1/tasks/{task_id}` and updated in-memory before Step 2.

4. **Schedule** (LLM Step 2) — runs on schedulable tasks with confirmed priorities only.

---
